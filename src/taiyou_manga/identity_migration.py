"""Explicit, revision-guarded migration of private local manga identity keys.

A source-path rename must never silently assign fresh IDs to existing chapters.
Only an owner-provided, fully reviewed mapping can change these registry keys.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .builder import _registry, _registry_lock, load_json
from .domain import ControllerError

_MAX_MOVES = 10_000


def _source_path(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 1000
        or value.startswith("/")
        or "\\" in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or (value != "." and any(part in ("", ".", "..") for part in value.split("/")))
    ):
        raise ControllerError("Invalid source path in identity migration")
    return value


def _moves(path: Path) -> list[tuple[str, str, str]]:
    if path.is_symlink() or not path.is_file():
        raise ControllerError("Migration mapping must be a regular local JSON file")
    data = load_json(path)
    if (
        not isinstance(data, dict)
        or set(data) != {"schemaVersion", "moves"}
        or type(data["schemaVersion"]) is not int
        or data["schemaVersion"] != 1
        or not isinstance(data["moves"], list)
        or not 1 <= len(data["moves"]) <= _MAX_MOVES
    ):
        raise ControllerError("Unsupported or empty identity migration mapping")
    result: list[tuple[str, str, str]] = []
    for entry in data["moves"]:
        if not isinstance(entry, dict) or set(entry) != {"kind", "from", "to"}:
            raise ControllerError("Migration entry requires only kind, from and to")
        kind = entry["kind"]
        if kind not in ("series", "chapter"):
            raise ControllerError("Migration kind must be series or chapter")
        old = _source_path(entry["from"])
        new = _source_path(entry["to"])
        if old == new:
            raise ControllerError("Migration cannot map a source path to itself")
        result.append((kind, old, new))
    return result


def _plan(
    registry: dict[str, str], moves: list[tuple[str, str, str]]
) -> tuple[dict[str, str], list[dict[str, str]]]:
    destinations: set[str] = set()
    sources: set[str] = set()
    changes: list[dict[str, str]] = []
    mapped: dict[str, str] = {}
    for kind, old, new in moves:
        source_key = f"{kind}:{old}"
        destination_key = f"{kind}:{new}"
        if source_key in sources:
            raise ControllerError("Duplicate migration source")
        sources.add(source_key)
        if destination_key.casefold() in destinations:
            raise ControllerError("Duplicate migration destination")
        destinations.add(destination_key.casefold())
        if source_key not in registry:
            raise ControllerError(f"Migration source is not present: {source_key}")
        if destination_key in registry:
            raise ControllerError("Migration destination already exists; no overwrite permitted")
        mapped[source_key] = destination_key
        changes.append({"kind": kind, "from": old, "to": new, "preservedId": registry[source_key]})

    # A series-folder rename must explicitly cover its chapter paths as one
    # transaction. Otherwise the next import would silently issue fresh chapter IDs.
    for kind, old, new in moves:
        if kind != "series" or old == ".":
            continue
        for key in registry:
            if key == f"chapter:{old}" or key.startswith(f"chapter:{old}/"):
                target = mapped.get(key)
                if target is None or not (target == f"chapter:{new}" or target.startswith(f"chapter:{new}/")):
                    raise ControllerError("Series migration must also remap every chapter within that series")

    updated = {key: value for key, value in registry.items() if key not in sources}
    for source_key, destination_key in mapped.items():
        updated[destination_key] = registry[source_key]
    if len(updated) != len(registry):
        raise ControllerError("Migration changed registry entry count")
    folded = [key.casefold() for key in updated]
    if len(folded) != len(set(folded)):
        raise ControllerError("Migration would create case-insensitive source collisions")
    return updated, changes


def _json_bytes(value: dict[str, str]) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def _backup_original(path: Path, original: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise ControllerError("Identity backup already exists; refusing overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as target:
            target.write(original)
            target.flush()
            os.fsync(target.fileno())
    except OSError:
        path.unlink(missing_ok=True)
        raise


def _replace_registry(state_file: Path, contents: bytes) -> None:
    fd, filename = tempfile.mkstemp(prefix=".manga-remap-", suffix=".tmp", dir=state_file.parent)
    temporary = Path(filename)
    try:
        with os.fdopen(fd, "wb") as target:
            target.write(contents)
            target.flush()
            os.fsync(target.fileno())
        temporary.replace(state_file)
    finally:
        temporary.unlink(missing_ok=True)


def migrate_identities(
    state_file: Path,
    mapping_file: Path,
    *,
    approve: bool = False,
    expected_revision: str | None = None,
    backup_file: Path | None = None,
) -> dict[str, Any]:
    """Preview by default; apply atomically after explicit approval and a full backup."""
    moves = _moves(mapping_file)
    if state_file.is_symlink() or not state_file.is_file():
        raise ControllerError("Existing private identity registry required for migration")
    with _registry_lock(state_file):
        original = state_file.read_bytes()
        revision = hashlib.sha256(original).hexdigest()
        registry = _registry(state_file)
        updated, changes = _plan(registry, moves)
        updated_bytes = _json_bytes(updated)
        candidate_revision = hashlib.sha256(updated_bytes).hexdigest()
        if not approve:
            return {
                "status": "preview-only",
                "currentRevision": revision,
                "proposedRevision": candidate_revision,
                "moves": changes,
                "requiresBackupAndApproval": True,
            }
        if not isinstance(expected_revision, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_revision):
            raise ControllerError("Approval requires the exact previewed SHA-256 revision")
        if revision != expected_revision:
            raise ControllerError("Stale identity registry revision; preview again")
        if backup_file is None:
            raise ControllerError("Approval requires an unused local backup path")
        if backup_file.resolve() in (state_file.resolve(), mapping_file.resolve()):
            raise ControllerError("Identity backup must be separate from registry and mapping")
        _backup_original(backup_file, original)
        _replace_registry(state_file, updated_bytes)
        return {
            "status": "applied",
            "previousRevision": revision,
            "currentRevision": candidate_revision,
            "moves": changes,
            "backup": str(backup_file),
        }
