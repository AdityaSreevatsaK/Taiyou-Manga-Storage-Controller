"""Safe ZIP input adapter for the existing private manga cover/metadata uploader.

No new catalogue schema: the archive contains the established metadata
candidates JSON and original source covers. Extraction is bounded and private.
"""

from __future__ import annotations

import shutil
import stat
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from .domain import ControllerError
from .hf_metadata import _api, apply, preview
from .hf_manage import _json_data, _new_file

MAX_FILES = 201
MAX_TOTAL = 500 * 1024 * 1024
MAX_COVER = 5 * 1024 * 1024
MAX_CANDIDATE = 2 * 1024 * 1024


def _safe_name(name: str) -> bool:
    if (
        not name
        or "\\" in name
        or "\x00" in name
        or "%" in name
        or name.startswith("/")
        or len(name) > 180
        or any(part in ("", ".", "..") for part in name.split("/"))
    ):
        return False
    if name in ("candidates.json", "metadata.json"):
        return True
    if name.startswith("covers/"):
        leaf = name.removeprefix("covers/")
        return bool(
            leaf
            and "/" not in leaf
            and len(leaf) <= 100
            and Path(leaf).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".avif")
        )
    return False


def unpack_verified(zip_path: Path, destination: Path) -> Path:
    if zip_path.is_symlink() or not zip_path.is_file() or zip_path.suffix.lower() != ".zip":
        raise ControllerError("A real ZIP containing metadata.json and covers/ is required")
    if not destination.is_dir() or destination.is_symlink():
        raise ControllerError("A new private temporary destination is required")
    size = 0
    try:
        zf = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ControllerError("Corrupt private cover ZIP archive") from exc
    with zf:
        records = [member for member in zf.infolist() if not member.is_dir()]
        if not 1 <= len(records) <= MAX_FILES:
            raise ControllerError("Unsafe private cover ZIP file count")
        names = [member.filename for member in records]
        if len(names) != len(set(names)) or not all(_safe_name(name) for name in names):
            raise ControllerError("Unsafe private cover ZIP paths or duplicates")
        present = set(names) & {"candidates.json", "metadata.json"}
        if len(present) != 1:
            raise ControllerError("Exactly one metadata.json or candidates.json must be supplied")
        for member in records:
            mode = member.external_attr >> 16
            maximum = MAX_CANDIDATE if member.filename in present else MAX_COVER
            if (
                stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                or member.flag_bits & 1
                or member.file_size <= 0
                or member.file_size > maximum
                or member.file_size > max(member.compress_size, 1) * 100
            ):
                raise ControllerError("Unsafe encrypted, compressed or oversized cover ZIP member")
            size += member.file_size
            if size > MAX_TOTAL:
                raise ControllerError("Private cover ZIP exceeds total extraction budget")
        for member in records:
            target = destination / member.filename
            if target.exists() or target.is_symlink():
                raise ControllerError("Unexpected existing private cover staging path")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
            if target.stat().st_size != member.file_size:
                raise ControllerError("Cover ZIP source was truncated during extraction")
    return destination / next(iter(present))


def cover_zip_upload(
    token: str, archive: Path, plan_path: Path, *, approve: bool = False
) -> dict[str, Any]:
    if not token:
        raise ControllerError("Private Hugging Face token is required")
    api = _api(token)
    with tempfile.TemporaryDirectory(prefix="taiyou-private-cover-") as staging:
        candidates = unpack_verified(archive, Path(staging))
        if approve:
            return apply(api, token, candidates, plan_path, approve=True)
        result = preview(api, token, candidates)
        _new_file(plan_path, _json_data(result))
        return result
