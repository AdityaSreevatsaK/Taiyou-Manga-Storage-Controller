"""Strict, no-extraction preflight for the ReLIFE GitHub Actions artefact ZIPs.

Metadata-only checks never read manga page bytes. Full verification streams each
CBZ to an isolated temporary file and independently revalidates every image.
Neither mode contacts Hugging Face or writes into the source directory.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
import tempfile
import zipfile
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any

from .domain import IMAGE_EXTENSIONS, ControllerError
from .images import DEFAULT_LIMITS, Limits, check_bytes
from .sources import _safe_member, read_archive

EXPECTED_EXTRAS = frozenset(
    "19.5 37.5 51.5 52.5 68.5 83.5 97.5 111.5 125.5 141.5 150.5 156.5 171.5 186.5 213.5".split()
)
EXPECTED_NUMBERED = frozenset(str(n) for n in range(1, 223))
EXPECTED_CHAPTERS = EXPECTED_NUMBERED | EXPECTED_EXTRAS
EXPECTED_PAGES = 5_606
ARTIFACT_RE = re.compile(r"ReLIFE-Original-Quality-Ch(\d{1,3})-(\d{1,3})\.zip\Z")
CHAPTER_RE = re.compile(r"(?i)\b(?:ch(?:apter)?|act)\.?\s*(\d{1,3}(?:\.\d+)?)\b")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def _chapter_from_name(value: str) -> str:
    matches = CHAPTER_RE.findall(Path(value).stem)
    if len(matches) != 1:
        raise ControllerError("Ambiguous or missing chapter number in CBZ filename")
    number = Decimal(matches[0])
    if not 1 <= number <= 222:
        raise ControllerError("CBZ chapter number outside ReLIFE 1-222")
    canonical = format(number.normalize(), "f")
    if canonical not in EXPECTED_CHAPTERS:
        raise ControllerError("Unexpected ReLIFE decimal/extra chapter")
    return canonical


def _check_archive_info(member: zipfile.ZipInfo, *, is_dir: bool = False) -> None:
    _safe_member(member.filename[:-1] if is_dir else member.filename)
    mode = stat.S_IFMT(member.external_attr >> 16)
    allowed_modes = (0, stat.S_IFDIR) if is_dir else (0, stat.S_IFREG)
    if mode not in allowed_modes:
        raise ControllerError("Artifact contains a symlink or special file")
    if member.flag_bits & 1:
        raise ControllerError("Encrypted artefact entry unsupported")
    if not is_dir and member.file_size > max(1, member.compress_size) * 200:
        raise ControllerError("Suspicious outer artefact compression ratio")


def _get_audit(zf: zipfile.ZipFile, members: dict[str, zipfile.ZipInfo]) -> dict[str, Any]:
    info = members.get("relife_quality_audit.json")
    if info is None or not 0 < info.file_size <= 8_000_000:
        raise ControllerError("Missing or oversized quality audit in ReLIFE artefact")
    with zf.open(info) as handle:
        raw = handle.read(8_000_001)
    if len(raw) != info.file_size:
        raise ControllerError("Truncated ReLIFE audit JSON")
    try:
        data = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise ControllerError("Invalid ReLIFE audit JSON") from exc
    if (
        not isinstance(data, dict)
        or type(data.get("schemaVersion")) is not int
        or data["schemaVersion"] != 1
        or data.get("title") != "ReLIFE"
        or data.get("requestedQuality") != "source-original-not-data-saver"
        or data.get("completeSeriesVerified") is not False
        or not isinstance(data.get("archives"), list)
    ):
        raise ControllerError("ReLIFE quality audit has incompatible metadata")
    return data


def _pages_metadata(record: dict[str, Any]) -> int:
    pages = record.get("pages")
    if not isinstance(pages, list) or not 1 <= len(pages) <= DEFAULT_LIMITS.max_pages:
        raise ControllerError("Invalid audited chapter page list")
    if record.get("verifiedPageCount") != len(pages):
        raise ControllerError("Audited chapter page-count discrepancy")
    names: set[str] = set()
    for page in pages:
        if not isinstance(page, dict):
            raise ControllerError("Malformed audited page")
        name = page.get("name")
        if not isinstance(name, str):
            raise ControllerError("Malformed audited page name")
        _safe_member(name)
        if Path(name).suffix.lower() not in IMAGE_EXTENSIONS:
            raise ControllerError("Unsupported audited image extension")
        if page.get("mimeType") != IMAGE_EXTENSIONS[Path(name).suffix.lower()]:
            raise ControllerError("Audited image MIME does not match extension")
        if name.casefold() in names:
            raise ControllerError("Duplicate audited page name")
        names.add(name.casefold())
        if not isinstance(page.get("sha256"), str) or not SHA256_RE.fullmatch(page["sha256"]):
            raise ControllerError("Missing audited page checksum")
        if (
            type(page.get("byteSize")) is not int
            or not 1 <= page["byteSize"] <= DEFAULT_LIMITS.max_image_bytes
            or type(page.get("width")) is not int
            or type(page.get("height")) is not int
            or not 1 <= page["width"] <= DEFAULT_LIMITS.max_dimension
            or not 1 <= page["height"] <= DEFAULT_LIMITS.max_dimension
            or page["width"] * page["height"] > DEFAULT_LIMITS.max_pixels
        ):
            raise ControllerError("Invalid audited page dimensions/size")
    return len(pages)


def _verify_chapter(
    zf: zipfile.ZipFile, info: zipfile.ZipInfo, audit: dict[str, Any], limits: Limits
) -> None:
    if info.file_size > limits.max_archive_bytes:
        raise ControllerError("CBZ exceeds chapter quota")
    digest = hashlib.sha256()
    with tempfile.TemporaryDirectory(prefix="manga-audit-") as temp:
        destination = Path(temp) / "chapter.cbz"
        total = 0
        with zf.open(info) as source, destination.open("wb") as target:
            while block := source.read(1024 * 1024):
                total += len(block)
                if total > limits.max_archive_bytes:
                    raise ControllerError("CBZ streaming size exceeds quota")
                digest.update(block)
                target.write(block)
        if total != info.file_size or total != audit["archiveByteSize"]:
            raise ControllerError("Truncated or mismatched CBZ media length")
        if digest.hexdigest() != audit["sha256"]:
            raise ControllerError("CBZ SHA-256 does not match Retriever audit")
        pages = read_archive(destination, limits)
        actual: dict[str, dict[str, Any]] = {}
        for page in pages:
            checked = check_bytes(page.data, page.name, limits)
            actual[page.name] = {
                "name": page.name,
                "sha256": checked.checksum,
                "byteSize": checked.byte_size,
                "mimeType": checked.mime,
                "width": checked.width,
                "height": checked.height,
            }
        claimed = {page["name"]: page for page in audit["pages"]}
        if actual != claimed:
            raise ControllerError("Verified CBZ pages disagree with Retriever audit")


def _check_companions(
    zf: zipfile.ZipFile,
    members: dict[str, zipfile.ZipInfo],
    reports: list[dict[str, Any]],
    expected: set[str],
) -> None:
    """Allow only the two documented MangaDex downloader helper files.

    The SQLite tracker is never opened as a database. The cover and tracker
    are not catalogue pages and are never uploaded as source-media records.
    """
    roots = {"ReLIFE"}
    for report in reports:
        relative_parts = PurePosixPath(report["relativePath"]).parts
        if len(relative_parts) > 1:
            roots.add("ReLIFE/" + relative_parts[0])
    companions = set(members) - expected
    if len(companions) > 2:
        raise ControllerError("Too many non-chapter files in ReLIFE artefact")
    allowed_companions = {f"{root}/{name}" for root in roots for name in ("cover.jpg", "download.db")}
    if not companions.issubset(allowed_companions):
        raise ControllerError("Unrecognised source-only ReLIFE helper files")
    kinds: set[str] = set()
    for path in companions:
        info = members[path]
        kind = PurePosixPath(path).name
        if kind in kinds:
            raise ControllerError("Duplicate ReLIFE helper file types")
        kinds.add(kind)
        if kind == "cover.jpg":
            if not 0 < info.file_size <= DEFAULT_LIMITS.max_image_bytes:
                raise ControllerError("ReLIFE cover image exceeds quota")
            with zf.open(info) as source:
                raw = source.read(DEFAULT_LIMITS.max_image_bytes + 1)
            if len(raw) != info.file_size:
                raise ControllerError("Truncated ReLIFE cover image")
            check_bytes(raw, "cover.jpg")
        elif kind == "download.db":
            if not 100 <= info.file_size <= 8_000_000:
                raise ControllerError("ReLIFE download tracker size exceeds quota")
            count = 0
            with zf.open(info) as source:
                header = source.read(16)
                count += len(header)
                if header != b"SQLite format 3\x00":
                    raise ControllerError("Unexpected ReLIFE download tracker signature")
                while data := source.read(1024 * 1024):
                    count += len(data)
                    if count > 8_000_000:
                        raise ControllerError("ReLIFE download tracker exceeds quota")
            if count != info.file_size:
                raise ControllerError("Truncated ReLIFE download tracker")


def audit_relife_artifacts(
    directory: Path, *, deep_verify: bool = False, require_complete: bool = True
) -> dict[str, Any]:
    """Reconcile exactly one known ReLIFE Actions run, fail closed on ambiguous editions."""
    if directory.is_symlink() or not directory.is_dir():
        raise ControllerError("ReLIFE artefact directory must be a normal folder")
    candidates = sorted(directory.iterdir(), key=lambda p: p.name)
    if not candidates or len(candidates) > 12:
        raise ControllerError("Expected up to 12 ReLIFE artefact ZIPs")
    keys: set[str] = set()
    ranges: set[tuple[int, int]] = set()
    pages_count = 0
    total_cbs = 0
    for artifact in candidates:
        if artifact.is_symlink() or not artifact.is_file():
            raise ControllerError("Unexpected non-file in artefact folder")
        match = ARTIFACT_RE.fullmatch(artifact.name)
        if match is None:
            raise ControllerError("Unexpected artefact filename")
        start, end = int(match[1]), int(match[2])
        if not 1 <= start <= end <= 222 or (start, end) in ranges:
            raise ControllerError("Duplicate or unsafe ReLIFE artefact range")
        ranges.add((start, end))
        if artifact.stat().st_size > 500_000_000:
            raise ControllerError("GitHub artefact ZIP exceeds size quota")
        try:
            with zipfile.ZipFile(artifact) as zf:
                all_infos = zf.infolist()
                if not 1 <= len(all_infos) <= 600:
                    raise ControllerError("GitHub artefact member count exceeded")
                members: dict[str, zipfile.ZipInfo] = {}
                seen: set[str] = set()
                for info in all_infos:
                    _check_archive_info(info, is_dir=info.is_dir())
                    if info.is_dir():
                        continue
                    name = info.filename
                    if name.casefold() in seen:
                        raise ControllerError("Duplicate GitHub artefact member")
                    seen.add(name.casefold())
                    members[name] = info
                audit = _get_audit(zf, members)
                if audit.get("requestedRange") != {"start": start, "end": end}:
                    raise ControllerError("ReLIFE artefact requested range mismatch")
                reports = audit["archives"]
                if not 1 <= len(reports) <= 50:
                    raise ControllerError("Invalid number of chapter archives in batch")
                included = set()
                per_batch_pages = 0
                for record in reports:
                    if not isinstance(record, dict):
                        raise ControllerError("Invalid audited chapter record")
                    relative = record.get("relativePath")
                    checksum = record.get("sha256")
                    size = record.get("archiveByteSize")
                    if not isinstance(relative, str) or not relative.lower().endswith(".cbz"):
                        raise ControllerError("Invalid relative CBZ path in audit")
                    _safe_member(relative)
                    if record.get("name") != Path(relative).name:
                        raise ControllerError("Audited CBZ filename mismatch")
                    if not isinstance(checksum, str) or not SHA256_RE.fullmatch(checksum):
                        raise ControllerError("Invalid archived CBZ checksum")
                    if type(size) is not int or not 1 <= size <= DEFAULT_LIMITS.max_archive_bytes:
                        raise ControllerError("Invalid archived CBZ size")
                    number = _chapter_from_name(Path(relative).name)
                    if number in keys or number in included:
                        raise ControllerError("Duplicate chapter identity across ReLIFE batches")
                    if not start <= Decimal(number) <= end:
                        raise ControllerError("Chapter does not belong to expected artefact range")
                    cbz_info = members.get("ReLIFE/" + relative)
                    if cbz_info is None or cbz_info.file_size != size:
                        raise ControllerError("Missing or size-mismatched CBZ inside GitHub artefact")
                    included.add(number)
                    per_batch_pages += _pages_metadata(record)
                    if deep_verify:
                        _verify_chapter(zf, cbz_info, record, DEFAULT_LIMITS)
                    total_cbs += 1
                if audit.get("verifiedArchives") != len(reports):
                    raise ControllerError("CBZ count differs from Retriever audit")
                if audit.get("verifiedPages") != per_batch_pages:
                    raise ControllerError("Page count differs from Retriever audit")
                allowed = {"relife_quality_audit.json", "SOURCE_AND_RIGHTS.txt"}
                allowed.update("ReLIFE/" + record["relativePath"] for record in reports)
                absent = allowed - set(members)
                if absent:
                    raise ControllerError(
                        f"Unexpected or missing files in GitHub artefact range {start}-{end}: "
                        f"missing={len(absent)}"
                    )
                _check_companions(zf, members, reports, allowed)
                if members["SOURCE_AND_RIGHTS.txt"].file_size > 16_384:
                    raise ControllerError("Oversized source attribution file")
                keys.update(included)
                pages_count += per_batch_pages
        except (OSError, zipfile.BadZipFile, RuntimeError, EOFError) as exc:
            raise ControllerError("Unreadable or damaged GitHub artefact ZIP") from exc
    numbered = {key for key in keys if key in EXPECTED_NUMBERED}
    extras = {key for key in keys if key in EXPECTED_EXTRAS}
    missing = sorted(EXPECTED_NUMBERED - numbered, key=lambda x: int(x))
    if require_complete and (keys != EXPECTED_CHAPTERS or pages_count != EXPECTED_PAGES or len(ranges) != 12):
        raise ControllerError("ReLIFE run incomplete or differs from the 237-CBZ/5606-page baseline")
    return {
        "status": "verified-content" if deep_verify else "metadata-only",
        "batchCount": len(ranges),
        "cbzArchives": total_cbs,
        "pages": pages_count,
        "numberedChapters": len(numbered),
        "extras": sorted(extras, key=lambda x: Decimal(x)),
        "missingNumberedChapters": missing,
        "readyForUpload": False,
        "requiresAuthorisedRightsAndUploadReview": True,
    }
