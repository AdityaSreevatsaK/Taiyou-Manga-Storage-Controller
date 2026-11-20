"""Independent manga checksums, bonus chapter reconciliation and private candidate staging."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .builder import build, load_json, verify_bundle, write_json
from .domain import ControllerError
from .images import DEFAULT_LIMITS
from .relife_intake import _check_archive_info, _safe_member, _verify_chapter
from .relife_stage import _copy_verified_cbz
from .selected_titles import SelectedTitle, selected_title

CHAPTER_NUMBER = re.compile(r"(?i)\bch(?:apter)?\.?\s*(\d{1,3}(?:\.\d+)?)\b")


def _number(filename: str, title: SelectedTitle) -> str:
    matches = CHAPTER_NUMBER.findall(Path(filename).stem)
    if len(matches) != 1:
        raise ControllerError("Unrecognised or ambiguous selected manga chapter label")
    try:
        number = Decimal(matches[0])
    except InvalidOperation as exc:
        raise ControllerError("Invalid selected manga chapter number") from exc
    if number < 0 or number > title.main_chapters:
        raise ControllerError("Selected manga chapter out of approved source bounds")
    canonical = format(number.normalize(), "f")
    return canonical


def stable_registry(title: SelectedTitle, numbers: set[str]) -> dict[str, str]:
    """Deterministic opaque identities independent of runner and import batches."""
    namespace = f"taiyou-manga/v1/selected/{title.slug}"
    registry = {
        f"series:{title.name}": "mng_" + hashlib.sha256((namespace + "/series").encode()).hexdigest()[:24]
    }
    for chapter in sorted(numbers, key=Decimal):
        registry[f"chapter:{title.name}/Chapter {chapter}.cbz"] = (
            "ch_" + hashlib.sha256((namespace + "/chapter/" + chapter).encode()).hexdigest()[:24]
        )
    return registry


def _page_identity(record: dict[str, Any]) -> tuple[tuple[str, str, int], ...]:
    pages = record.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ControllerError("Missing selected manga audited image pages")
    result = []
    for image in pages:
        if not isinstance(image, dict):
            raise ControllerError("Malformed selected manga page record")
        result.append((image["name"], image["sha256"], image["byteSize"]))
    return tuple(result)


def stage_selected_manga(slug: str, artifact_dir: Path, output: Path, registry: Path) -> dict[str, object]:
    """Fail closed if one numbered chapter is missing. Retain all unique bonuses."""
    title = selected_title(slug)
    if artifact_dir.is_symlink() or not artifact_dir.is_dir():
        raise ControllerError("Selected manga source directory is missing or linked")
    if output.exists() or output.is_symlink() or registry.exists() or registry.is_symlink():
        raise ControllerError("Selected manga output or identity registry already exists")
    if (
        output.resolve().is_relative_to(artifact_dir.resolve())
        or registry.resolve().is_relative_to(artifact_dir.resolve())
        or registry.resolve().is_relative_to(output.resolve())
    ):
        raise ControllerError("Selected manga output and IDs must be outside source archives")
    originals = sorted(artifact_dir.iterdir(), key=lambda x: x.name)
    if {path.name for path in originals} != {name + ".zip" for name in title.artifact_names}:
        raise ControllerError("Selected manga source folder contains missing or unexpected artifacts")

    main_found: set[int] = set()
    deduplicated: dict[str, tuple[tuple[str, str, int], ...]] = {}
    duplicates = 0
    archived_pages = 0
    distinct_pages = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".manga-selected-stage-", dir=output.parent) as scratch:
        src = Path(scratch) / "source"
        chapters = src / title.name
        chapters.mkdir(parents=True)
        for outer in originals:
            if outer.is_symlink() or not outer.is_file():
                raise ControllerError("Unsafe selected manga source artifact")
            if outer.stat().st_size > 500_000_000:
                raise ControllerError("Selected manga artifact exceeds outer archive quota")
            ranges = [
                (start, end)
                for start, end in title.ranges
                if outer.name == f"{title.prefix}{start}-{end}.zip"
            ]
            if len(ranges) != 1:
                raise ControllerError("Unexpected selected manga batch range")
            start, end = ranges[0]
            root = f"{slug}-{start}-{end}"
            try:
                with zipfile.ZipFile(outer) as zf:
                    members: dict[str, zipfile.ZipInfo] = {}
                    seen: set[str] = set()
                    for info in zf.infolist():
                        _check_archive_info(info, is_dir=info.is_dir())
                        if info.is_dir():
                            continue
                        if info.filename.casefold() in seen:
                            raise ControllerError("Duplicate selected source ZIP member")
                        seen.add(info.filename.casefold())
                        members[info.filename] = info
                    audit_name = f"{root}/quality_audit.json"
                    if audit_name not in members or members[audit_name].file_size > 8_000_000:
                        raise ControllerError("Selected source audit is missing or oversized")
                    report = json.loads(zf.read(audit_name))
                    if (
                        not isinstance(report, dict)
                        or report.get("schemaVersion") != 1
                        or report.get("slug") != slug
                        or report.get("title") != title.name
                        or report.get("requestedRange") != {"start": start, "end": end}
                        or report.get("qualityRequested") != "original-upload-not-data-saver"
                        or report.get("sourceTitleUrl") != f"https://mangadex.org/title/{title.source_id}"
                        or report.get("completeSeriesVerified") is not False
                        or not isinstance(report.get("archives"), list)
                    ):
                        raise ControllerError("Selected manga audit contains conflicting source metadata")
                    records = report["archives"]
                    if not 1 <= len(records) <= 75:
                        raise ControllerError("Selected source archive member count out of bounds")
                    expected = set(range(start, end + 1))
                    current: set[int] = set()
                    batch_pages = 0
                    allowed = {audit_name, f"{root}/SOURCE_AND_RIGHTS.txt"}
                    if f"{root}/SOURCE_AND_RIGHTS.txt" not in members:
                        raise ControllerError("Missing selected manga source credit statement")
                    if members[f"{root}/SOURCE_AND_RIGHTS.txt"].file_size > 16000:
                        raise ControllerError("Selected manga rights notice exceeds metadata quota")
                    for record in records:
                        if not isinstance(record, dict):
                            raise ControllerError("Malformed selected manga CBZ audit")
                        rel = record.get("relativePath")
                        if not isinstance(rel, str) or not rel.lower().endswith(".cbz"):
                            raise ControllerError("Invalid selected manga archive path")
                        _safe_member(rel)
                        if Path(rel).name != record.get("name"):
                            raise ControllerError("Selected manga chapter audit identity mismatch")
                        filename = f"{root}/chapters/{rel}"
                        if filename not in members:
                            raise ControllerError("Missing selected source CBZ archive")
                        info = members[filename]
                        if record.get("archiveByteSize") != info.file_size:
                            raise ControllerError("Selected manga CBZ byte size mismatch")
                        number = _number(Path(rel).name, title)
                        value = Decimal(number)
                        main = int(value) if value >= 1 and value == value.to_integral_value() else None
                        claimed_main = record.get("mainChapterLabel")
                        if claimed_main != main:
                            raise ControllerError(
                                "Selected manga main chapter classification differs from audit"
                            )
                        if main is not None:
                            if main not in expected or main in current or main in main_found:
                                raise ControllerError("Duplicate or out-of-range numbered manga chapter")
                            current.add(main)
                            main_found.add(main)
                        _verify_chapter(zf, info, record, DEFAULT_LIMITS)
                        pages = _page_identity(record)
                        batch_pages += len(pages)
                        archived_pages += len(pages)
                        allowed.add(filename)
                        if number in deduplicated:
                            if deduplicated[number] != pages or main is not None:
                                raise ControllerError("Inconsistent duplicate selected manga bonus chapter")
                            duplicates += 1
                            continue
                        deduplicated[number] = pages
                        distinct_pages += len(pages)
                        destination = chapters / f"Chapter {number}.cbz"
                        _copy_verified_cbz(zf, filename, destination, record["sha256"], info.file_size)
                    if current != expected:
                        raise ControllerError("Selected manga source batch missing numbered chapters")
                    if report.get("verifiedMainChapterNumbers") != sorted(current):
                        raise ControllerError("Selected manga numbered audit mismatch")
                    if report.get("verifiedMainChapters") != len(current):
                        raise ControllerError("Selected manga main chapter count mismatch")
                    if report.get("verifiedPages") != batch_pages:
                        raise ControllerError("Selected manga batch page count mismatch")
                    if report.get("verifiedArchives") != len(records):
                        raise ControllerError("Selected manga total archive count mismatch")
                    if set(members) != allowed:
                        raise ControllerError("Unexpected non-chapter selected manga source files")
            except ControllerError:
                raise
            except (OSError, ValueError, zipfile.BadZipFile, RuntimeError, EOFError) as exc:
                raise ControllerError(
                    "Selected manga source audit could not be independently verified"
                ) from exc
        if main_found != set(range(1, title.main_chapters + 1)):
            raise ControllerError("Selected manga is missing one or more numbered main chapters")
        if archived_pages != title.audited_pages:
            raise ControllerError("Selected manga total archived page count changed")
        registry.parent.mkdir(parents=True, exist_ok=True)
        write_json(registry, stable_registry(title, set(deduplicated)))
        report = build(src, output, registry, direction="vertical", allow_duplicate_pages=True)
        check = verify_bundle(output)
        if (
            report["series"] != 1
            or check["series"] != 1
            or report["chapters"] != len(deduplicated)
            or check["chapters"] != len(deduplicated)
            or report["pages"] != distinct_pages
            or check["pages"] != distinct_pages
        ):
            raise ControllerError("Staged selected manga data contract failed final check")
        catalogue = load_json(output / "catalogue.json")
        if catalogue[0]["title"] != title.name or catalogue[0]["direction"] != "vertical":
            raise ControllerError("Staged selected manga catalogue has unexpected identity")
        return {
            "status": "verified-selected-candidate",
            "title": title.name,
            "slug": slug,
            "sourceRun": title.run_id,
            "mainChapters": title.main_chapters,
            "uniqueChapters": len(deduplicated),
            "verifiedPages": distinct_pages,
            "auditedSourcePages": archived_pages,
            "duplicateBonusArchivesSkipped": duplicates,
            "persistedIDsDeterministic": True,
            "readyForRemoteUpload": True,
        }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    from .selected_titles import TITLES

    parser = argparse.ArgumentParser(description="Verify and stage one approved manga title locally")
    parser.add_argument("--slug", choices=tuple(TITLES), required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = stage_selected_manga(args.slug, args.artifact_dir, args.output, args.registry)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ControllerError, OSError) as exc:
        print(f"Selected manga source import refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
