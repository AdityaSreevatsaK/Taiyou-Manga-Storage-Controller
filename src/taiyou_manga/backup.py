"""Verified full-media ZIP backup and non-destructive local restore."""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import IO

from .builder import verify_bundle
from .domain import ControllerError

INDEX = "BACKUP_INDEX.json"
MAX_BACKUP_BYTES = 5_000_000_000
MAX_BACKUP_FILES = 20_000


def _sha256(stream: IO[bytes]) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    while block := stream.read(1_048_576):
        count += len(block)
        if count > MAX_BACKUP_BYTES:
            raise ControllerError("Backup quota exceeded")
        digest.update(block)
    return digest.hexdigest(), count


def _safe_relative(name: str) -> None:
    if not name or len(name) > 300 or "\\" in name or "\x00" in name or ":" in name:
        raise ControllerError("Unsafe backup member path")
    parts = name.split("/")
    if name.startswith("/") or any(x in ("", ".", "..") for x in parts) or PurePosixPath(name).is_absolute():
        raise ControllerError("Backup archive traversal")


def create_backup(bundle: Path, target: Path) -> dict[str, object]:
    stats = verify_bundle(bundle)
    if target.exists():
        raise ControllerError("Backup target exists; refusing overwrite")
    files = sorted(p for p in bundle.rglob("*") if p.is_file())
    if any(p.is_symlink() for p in bundle.rglob("*")) or len(files) > MAX_BACKUP_FILES:
        raise ControllerError("Unsafe link or excessive files in bundle")
    index: dict[str, dict[str, object]] = {}
    total = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=target.parent, prefix=".backup-", suffix=".tmp", delete=False
    ) as handle:
        staging = Path(handle.name)
    try:
        with zipfile.ZipFile(staging, mode="w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
            for path in files:
                rel = path.relative_to(bundle).as_posix()
                _safe_relative(rel)
                with path.open("rb") as source:
                    checksum, size = _sha256(source)
                total += size
                if total > MAX_BACKUP_BYTES:
                    raise ControllerError("Backup total exceeds quota")
                index[rel] = {"sha256": checksum, "bytes": size}
                zf.write(path, rel)
            zf.writestr(
                INDEX, json.dumps({"backupVersion": 1, "kind": "full-media", "files": index}, sort_keys=True)
            )
        verification = verify_backup(staging)
        staging.rename(target)
        return {**stats, **verification, "path": str(target)}
    finally:
        staging.unlink(missing_ok=True)


def verify_backup(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ControllerError("Backup file missing or linked")
    try:
        with zipfile.ZipFile(path) as zf:
            entries = zf.infolist()
            if not 2 <= len(entries) <= MAX_BACKUP_FILES + 1:
                raise ControllerError("Backup entry count invalid")
            names = set()
            for entry in entries:
                _safe_relative(entry.filename)
                folded = entry.filename.casefold()
                if folded in names or entry.is_dir():
                    raise ControllerError("Duplicate file or directory in backup")
                names.add(folded)
                if stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG):
                    raise ControllerError("Backup contains special file or symlink")
            if INDEX not in zf.namelist():
                raise ControllerError("Missing backup index")
            if zf.getinfo(INDEX).file_size > 5_000_000:
                raise ControllerError("Backup index too large")
            index = json.loads(zf.read(INDEX))
            if (
                not isinstance(index, dict)
                or index.get("backupVersion") != 1
                or index.get("kind") != "full-media"
                or not isinstance(index.get("files"), dict)
            ):
                raise ControllerError("Unknown backup index version")
            expected = index["files"]
            if set(expected) != set(zf.namelist()) - {INDEX}:
                raise ControllerError("Backup file inventory changed")
            total = 0
            for name in expected:
                _safe_relative(name)
                with zf.open(name) as content:
                    checksum, size = _sha256(content)
                if expected[name] != {"sha256": checksum, "bytes": size}:
                    raise ControllerError("Backup checksum mismatch")
                total += size
                if total > MAX_BACKUP_BYTES:
                    raise ControllerError("Backup total exceeds quota")
        return {"verifiedFiles": len(expected), "verifiedBytes": total, "kind": "full-media"}
    except (zipfile.BadZipFile, OSError, EOFError, ValueError, KeyError) as exc:
        if isinstance(exc, ControllerError):
            raise
        raise ControllerError("Backup invalid or corrupted") from exc


def restore_backup(archive: Path, destination: Path, approve: bool = False) -> dict[str, object]:
    inspection = verify_backup(archive)
    if not approve:
        return {**inspection, "operation": "preview", "destinationExists": destination.exists()}
    if destination.exists():
        raise ControllerError("Restore target already exists; never overwrite")
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".restore-stage-", dir=destination.parent))
    try:
        with zipfile.ZipFile(archive) as zf:
            for name in zf.namelist():
                if name == INDEX:
                    continue
                _safe_relative(name)
                target = stage.joinpath(*name.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as source, target.open("xb") as sink:
                    shutil.copyfileobj(source, sink, 1_048_576)
        verify_bundle(stage)
        stage.rename(destination)
        return {**inspection, "operation": "restored", "destination": str(destination)}
    finally:
        if stage.exists():
            shutil.rmtree(stage)
