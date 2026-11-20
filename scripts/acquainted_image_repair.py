"""Private, non-destructive diagnostics for damaged Acquainted manga JPEG pages.

Creates only local diagnostic reports and explicitly reviewed repair *copies*.
Original ZIPs and extracted pages are never modified. A repaired, decodable
JPEG is not proof that lost artwork was recovered: visual review is mandatory.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import warnings
from pathlib import Path
from typing import Any

from PIL import Image, ImageFile

from taiyou_manga.domain import ControllerError
from taiyou_manga.images import DEFAULT_LIMITS, check_bytes

MAX_INSPECT_BYTES = 25_000_000


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _save_verified_candidate(candidate: bytes, filename: str, folder: Path) -> Path:
    checked = check_bytes(candidate, filename)
    if checked.checksum != sha256(candidate):
        raise ControllerError("Recovered JPEG digest verification failed")
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / filename
    if destination.is_symlink():
        raise ControllerError("Symlinked repaired JPEG is not allowed")
    if destination.exists():
        if not destination.is_file() or sha256(destination.read_bytes()) != checked.checksum:
            raise ControllerError(f"Existing repaired JPEG changed: {filename}. Preserve it for review.")
    else:
        with destination.open("xb") as handle:
            handle.write(candidate)
    return destination


def _recover_jpeg(original: bytes, filename: str, work: Path) -> tuple[str, Path] | None:
    """Offer a recovery candidate, never silently accept it for publication."""
    if not filename.lower().endswith((".jpg", ".jpeg")) or not original.startswith(b"\xff\xd8"):
        return None
    repaired_folder = work / "repaired-candidates"

    # Sometimes the JPEG decoder only needs its missing terminal EOI marker.
    if not original.endswith(b"\xff\xd9"):
        appended = original + b"\xff\xd9"
        try:
            return "missing-jpeg-eoi", _save_verified_candidate(appended, filename, repaired_folder)
        except (ControllerError, OSError, SyntaxError, ValueError):
            pass

    # More seriously truncated JPEGs can decode with partially lost visual
    # content. This is a review candidate, never an automatic source replacement.
    previous_setting = ImageFile.LOAD_TRUNCATED_IMAGES
    try:
        ImageFile.LOAD_TRUNCATED_IMAGES = True
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(original)) as image:
                if image.format != "JPEG":
                    return None
                width, height = image.size
                if (
                    not 1 <= width <= DEFAULT_LIMITS.max_dimension
                    or not 1 <= height <= DEFAULT_LIMITS.max_dimension
                    or width * height > DEFAULT_LIMITS.max_pixels
                ):
                    return None
                image.load()
                colour = image.convert("RGB")
                result = io.BytesIO()
                colour.save(result, format="JPEG", quality=95, subsampling=0)
        path = _save_verified_candidate(result.getvalue(), filename, repaired_folder)
        return "tolerant-jpeg-reencode-may-have-missing-artwork", path
    except (
        ControllerError,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
        OSError,
        SyntaxError,
        ValueError,
    ):
        return None
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = previous_setting


def _reason(error: ControllerError) -> str:
    cause = error.__cause__
    if cause is None:
        return str(error)
    return f"{error}: {type(cause).__name__}: {cause}"[:600]


def _write_report(path: Path, value: dict[str, Any]) -> None:
    if path.is_symlink():
        raise ControllerError("Refusing to write diagnostic report through symlink")
    contents = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temp = path.with_name(path.name + ".temporary")
    if temp.exists() or temp.is_symlink():
        raise ControllerError("Unexpected unfinished diagnostic report temporary file")
    try:
        with temp.open("x", encoding="utf-8") as output:
            output.write(contents)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def inspect_and_prepare(
    pages: Path,
    work: Path,
    *,
    use_reviewed_repairs: bool = False,
) -> Path:
    """Inspect every image; provide review candidates, never skip damaged pages.

    A separate --use-reviewed-repairs invocation is required to build from
    staged copies. The original ZIP and initially extracted pages remain intact.
    """
    if not pages.is_dir() or pages.is_symlink() or not work.is_dir():
        raise ControllerError("Invalid private manga staging directories")
    entries = sorted(pages.iterdir(), key=lambda item: item.name.casefold())
    if not entries or any(path.is_symlink() or not path.is_file() for path in entries):
        raise ControllerError("Private extracted manga pages must be regular files")

    issues: list[dict[str, str | None]] = []
    expected: dict[str, Path] = {}
    for file in entries:
        blob = file.read_bytes()
        if not 0 < len(blob) <= MAX_INSPECT_BYTES:
            raise ControllerError(f"Empty or oversized original manga page: {file.name}")
        try:
            check_bytes(blob, file.name)
            expected[file.name] = file
        except ControllerError as exc:
            recovered = _recover_jpeg(blob, file.name, work)
            repair_path = recovered[1] if recovered else None
            issues.append(
                {
                    "file": file.name,
                    "sourceSha256": sha256(blob),
                    "validationError": _reason(exc),
                    "repairMethod": recovered[0] if recovered else None,
                    "candidateFile": str(repair_path) if repair_path else None,
                    "candidateSha256": sha256(repair_path.read_bytes()) if repair_path else None,
                }
            )
            if repair_path:
                expected[file.name] = repair_path

    report_path = work / "image-diagnostics.json"
    report: dict[str, Any] = {
        "mediaKind": "manga-import-diagnostics",
        "sourceImageCount": len(entries),
        "invalidImageCount": len(issues),
        "recoveredCandidateCount": sum(issue["candidateFile"] is not None for issue in issues),
        "issues": issues,
        "originalImagesModified": False,
        "requiresVisualReview": bool(issues),
    }
    _write_report(report_path, report)

    if not issues:
        print(f"Full image validation passed: {len(entries)} original pages", flush=True)
        return pages

    print(f"\nImage validation found {len(issues)} problematic page(s).", flush=True)
    for issue in issues:
        print(f"  {issue['file']}: {issue['validationError']}", flush=True)
        if issue["candidateFile"]:
            print(f"    Inspect candidate: {issue['candidateFile']}", flush=True)
    print(f"Detailed report: {report_path}", flush=True)

    if len(expected) != len(entries):
        raise ControllerError(
            "Some image bytes are not recoverable. Obtain intact originals and rebuild the ZIP; "
            "no chapter will be silently skipped or uploaded."
        )
    if not use_reviewed_repairs:
        raise ControllerError(
            "Review every repaired candidate for missing/blank artwork. "
            "If visually acceptable, rerun with --use-reviewed-repairs. "
            "If not, replace the damaged image in the source ZIP."
        )

    destination = work / "validated-pages"
    if destination.is_symlink():
        raise ControllerError("Refusing a symlinked private manga repair directory")
    destination.mkdir(parents=True, exist_ok=True)
    if set(path.name for path in destination.iterdir()) - set(expected):
        raise ControllerError("Existing repair staging contains stale or unexpected files")
    for filename, source in expected.items():
        target = destination / filename
        checksum = sha256(source.read_bytes())
        if target.is_symlink():
            raise ControllerError("Existing repaired source is a symlink")
        if target.exists():
            if not target.is_file() or sha256(target.read_bytes()) != checksum:
                raise ControllerError("Previously reviewed page differs; do not overwrite")
        else:
            with source.open("rb") as reader, target.open("xb") as writer:
                shutil.copyfileobj(reader, writer, 1024 * 1024)
        check_bytes(target.read_bytes(), filename)
    if len(list(destination.iterdir())) != len(entries):
        raise ControllerError("Incomplete repaired manga staging area")
    print(
        "Using explicitly reviewed repaired JPEG copies. "
        "Original ZIP and extracted source pages are preserved.",
        flush=True,
    )
    return destination
