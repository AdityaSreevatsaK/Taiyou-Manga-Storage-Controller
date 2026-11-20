"""General, revision-guarded bulk upload of verified CBZ/image manga bundles.

Existing entries may be skipped safely when the chapter structure is identical.
No existing catalogue, manifests, pages, covers or personal metadata are
replaced. Media uploads are checkpointed and resumable, with publication last.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .builder import load_json, verify_bundle
from .domain import ControllerError, validate_manifest_json
from .hf_layout import CANONICAL_CATALOGUE, canonical_library, validate_entries
from .hf_manage import _json_data, _new_file, normalized_title, snapshot
from .hf_upload import DATASET, UploadConflict
from .metadata import cover_asset_path

BATCH_SIZE = 125
BULK_ROOT = "ingest/bulk-v1"
MAX_BUNDLES = 100
MAX_RECORDS = 5000


@dataclass(frozen=True)
class SourceFile:
    remote: str
    local: Path
    checksum: str
    size: int


@dataclass(frozen=True)
class NewManga:
    entry: dict[str, Any]
    files: tuple[SourceFile, ...]
    rights: bytes


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def _source_file(path: Path, root: Path, name: str) -> SourceFile:
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ControllerError("Manga upload references an unsafe local file")
    size = path.stat().st_size
    if not 0 < size <= 25_000_000:
        raise ControllerError("Manga upload input exceeds per-file budget")
    return SourceFile(name, path, _hash_file(path), size)


def discover_bundles(source: Path) -> list[Path]:
    if source.is_symlink() or not source.is_dir():
        raise ControllerError("Select an existing directory of verified manga bundles")
    if (source / "catalogue.json").is_file():
        return [source]
    children = sorted(
        child for child in source.iterdir() if child.is_dir() and (child / "catalogue.json").is_file()
    )
    if not 1 <= len(children) <= MAX_BUNDLES or any(child.is_symlink() for child in children):
        raise ControllerError("Expected 1-100 non-symlinked verified bundle folders")
    return children


def load_bundles(source: Path) -> list[NewManga]:
    result: list[NewManga] = []
    ids: set[str] = set()
    for root in discover_bundles(source):
        verified = verify_bundle(root)
        entries = validate_entries(load_json(root / "catalogue.json"))
        if len(entries) != 1 or verified["series"] != 1:
            raise ControllerError("One manga per bundle is required for rights-aware bulk upload")
        if not verified.get("rightsDeclared") or not (root / "rights.json").is_file():
            raise ControllerError("General manga upload requires verified source rights.json")
        rights_path = root / "rights.json"
        if rights_path.is_symlink():
            raise ControllerError("Symlinked source rights are not allowed")
        rights = rights_path.read_bytes()
        if len(rights) > 10_000:
            raise ControllerError("Source rights record is excessively large")
        rights_doc = json.loads(rights)
        if rights_doc.get("title") != entries[0]["title"]:
            raise ControllerError("Source permissions do not match the immutable manga title")
        entry = entries[0]
        sid = entry["id"]
        if sid in ids:
            raise ControllerError("Repeated local manga ID across bulk bundles")
        ids.add(sid)
        files = []
        for chapter in entry["chapters"]:
            path = root / "manifests" / f"{chapter['id']}.json"
            doc = validate_manifest_json(load_json(path))
            if doc.chapterId != chapter["id"] or len(doc.pages) != chapter["pageCount"]:
                raise ControllerError("Chapter structure differs from the verified source")
            files.append(_source_file(path, root, f"data/manifests/{chapter['id']}.json"))
            for page in doc.pages:
                if not page.assetPath.startswith(f"manga/{sid}/{chapter['id']}/"):
                    raise ControllerError("Uploaded image does not belong to the declared chapter")
                local = root / "assets" / page.assetPath
                record = _source_file(local, root, f"data/{page.assetPath}")
                if record.checksum != page.sha256 or record.size != page.byteSize:
                    raise ControllerError("Source image bytes disagree with verified manifest")
                files.append(record)
        if entry.get("cover"):
            cover_remote = cover_asset_path(entry["cover"], sid)
            cover_local = root / "assets" / entry["cover"]["assetPath"]
            cover_record = _source_file(cover_local, root, cover_remote)
            if cover_record.checksum != entry["cover"]["sha256"]:
                raise ControllerError("Manga cover checksum differs from catalogue")
            files.append(cover_record)
        if len(files) != verified["pages"] + verified["chapters"] + bool(entry.get("cover")):
            raise ControllerError("Local manga bundle contains incomplete media references")
        if len(files) != len({record.remote for record in files}):
            raise ControllerError("Local manga contains duplicated canonical upload paths")
        result.append(NewManga(entry, tuple(sorted(files, key=lambda row: row.remote)), rights))
    return result


def _parts(files: tuple[SourceFile, ...]) -> list[list[SourceFile]]:
    return [list(files[i : i + BATCH_SIZE]) for i in range(0, len(files), BATCH_SIZE)]


def _marker(sid: str, index: int, files: list[SourceFile]) -> tuple[str, bytes]:
    values = [[row.remote, row.size, row.checksum] for row in files]
    return (
        f"{BULK_ROOT}/{sid}/part-{index:04}.json",
        _json_data({"schemaVersion": 1, "id": sid, "part": index, "files": values}),
    )


def _fingerprint(files: tuple[SourceFile, ...]) -> str:
    return _sha(_json_data([[row.remote, row.size, row.checksum] for row in files]))


def _conflicts(item: NewManga, existing: list[dict[str, Any]], paths: set[str]) -> tuple[str, str]:
    sid = item.entry["id"]
    old = next((row for row in existing if row["id"] == sid), None)
    collision = [
        row for row in existing
        if row["id"] != sid and normalized_title(row["title"]) == normalized_title(item.entry["title"])
    ]
    if collision:
        return "conflict", "Normalised manga title already exists with a different immutable ID"
    if old is not None:
        if old["chapters"] != item.entry["chapters"]:
            return "conflict", "Existing manga chapter identity/order differs from local candidate"
        if not all(record.remote in paths for record in item.files):
            return "conflict", "Existing manga is missing files; use restore/integrity workflow"
        return "already-listed", "Existing title and chapters preserved; existing metadata not overwritten"
    completion = f"{BULK_ROOT}/{sid}/complete.json"
    if completion in paths:
        return "conflict", "Previous completion marker exists without a matching title"
    for index, part in enumerate(_parts(item.files), 1):
        path, _ = _marker(sid, index, part)
        targets = {rec.remote for rec in part}
        if path not in paths and targets & paths:
            return "conflict", "Uncheckpointed conflicting media destination exists"
        if path in paths and not targets.issubset(paths):
            return "conflict", "Partial batch checkpoint references missing media"
    return "upload", "New manga, validated and ready to append"


def prepare_plan(
    source: Path,
    sha: str,
    paths: set[str],
    old_catalogue: bytes,
    old_entries: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[NewManga]]:
    bundles = load_bundles(source)
    other_ids = [item.entry["id"] for item in bundles]
    if len(set(other_ids)) != len(other_ids):
        raise ControllerError("Duplicate local manga identifiers")
    by_title: dict[str, str] = {}
    for manga in bundles:
        key = normalized_title(manga.entry["title"])
        previous = by_title.get(key)
        if previous is not None and previous != manga.entry["id"]:
            raise ControllerError("Ambiguous local manga titles would create duplicates")
        by_title[key] = manga.entry["id"]
    rows = []
    for manga in bundles:
        status, reason = _conflicts(manga, old_entries, paths)
        rows.append({
            "id": manga.entry["id"], "title": manga.entry["title"],
            "status": status, "reason": reason, "chapters": len(manga.entry["chapters"]),
            "pages": sum(ch["pageCount"] for ch in manga.entry["chapters"]),
            "fileCount": len(manga.files), "sourceFingerprint": _fingerprint(manga.files),
            "sourceRightsSha256": _sha(manga.rights),
        })
    plan = {
        "schemaVersion": 1, "operation": "append-only-manga-bulk-upload",
        "dataset": DATASET, "expectedRevision": sha,
        "catalogueSha256": _sha(old_catalogue),
        "status": "conflict" if any(row["status"] == "conflict" for row in rows) else "ready",
        "items": rows,
        "new": sum(row["status"] == "upload" for row in rows),
        "unchanged": sum(row["status"] == "already-listed" for row in rows),
        "deleteOperations": 0,
        "overwriteExistingFiles": False,
    }
    return plan, bundles


def plan_upload(token: str, source: Path, output: Path) -> dict[str, Any]:
    _, sha, files, catalogue, entries = snapshot(token)
    plan, _ = prepare_plan(source, sha, files, catalogue, entries)
    _new_file(output, _json_data(plan))
    return plan


def upload(
    token: str, source: Path, plan_file: Path, *, approve: bool
) -> dict[str, object]:
    if not approve:
        raise ControllerError("Explicit --approve is required to upload private manga")
    if plan_file.is_symlink() or not plan_file.is_file():
        raise ControllerError("Approved private bulk-upload preview is missing")
    approved = json.loads(plan_file.read_bytes())
    api, sha, remote_files, catalogue, existing = snapshot(token)
    plan, bundles = prepare_plan(source, sha, remote_files, catalogue, existing)
    if plan != approved:
        raise UploadConflict("Private dataset, bundle bytes, or upload plan changed since approval")
    if plan["status"] != "ready":
        raise UploadConflict("Bulk upload has title, media or identity conflicts")
    from huggingface_hub import CommitOperationAdd
    head = sha

    def commit(operations: list[Any], message: str) -> None:
        nonlocal head
        current = api.dataset_info(DATASET, token=token)
        if current.private is not True or current.sha != head:
            raise UploadConflict("Private dataset revision moved during bulk upload")
        api.create_commit(
            repo_id=DATASET, repo_type="dataset", revision="main", token=token,
            parent_commit=head, operations=operations, commit_message=message,
            num_threads=4,
        )
        updated = api.dataset_info(DATASET, token=token)
        if updated.sha == head:
            raise UploadConflict("Private bulk-upload commit did not advance")
        head = updated.sha

    uploaded = 0
    skipped = 0
    for manga, row in zip(bundles, plan["items"], strict=True):
        if row["status"] == "already-listed":
            skipped += 1
            continue
        sid = manga.entry["id"]
        for idx, part in enumerate(_parts(manga.files), 1):
            marker, body = _marker(sid, idx, part)
            target_set = {file.remote for file in part}
            # Checkpoint comparison is mandatory for resumable uploads.
            if marker in remote_files:
                prior = _read_marker(marker, head, token)
                if prior != body or not target_set.issubset(remote_files):
                    raise UploadConflict("Existing bulk checkpoint differs from source")
                continue
            if target_set & remote_files:
                raise UploadConflict("Uncheckpointed media exists and may not be overwritten")
            operations = [
                CommitOperationAdd(path_in_repo=rec.remote, path_or_fileobj=rec.local)
                for rec in part
            ]
            operations.append(CommitOperationAdd(path_in_repo=marker, path_or_fileobj=body))
            commit(operations, f"Append verified manga {sid} media batch {idx}")
            remote_files.update(target_set | {marker})
            print(f"Verified private batch {idx}/{len(_parts(manga.files))} for {sid}", flush=True)

        # Do not publish until all immutable manga images and manifests are present.
        if not {rec.remote for rec in manga.files}.issubset(remote_files):
            raise UploadConflict("Manga source files incomplete before catalogue publication")
        current_entries = [
            *existing, manga.entry
        ]
        new_catalogue = _json_data(canonical_library(sorted(
            current_entries, key=lambda item: item["title"].casefold()
        )))
        before_path = f"control/bulk-catalogue-backups/{head}/library.json"
        rights_path = f"control/bulk-rights/{sid}.json"
        finished_path = f"{BULK_ROOT}/{sid}/complete.json"
        if any(name in remote_files for name in (before_path, rights_path, finished_path)):
            raise UploadConflict("Bulk metadata backup, rights or completion path already exists")
        completion = _json_data({
            "schemaVersion": 1, "mangaId": sid, "sourceFingerprint": row["sourceFingerprint"],
            "chapters": row["chapters"], "pages": row["pages"], "complete": True,
        })
        commit(
            [
                CommitOperationAdd(path_in_repo=before_path, path_or_fileobj=catalogue),
                CommitOperationAdd(path_in_repo=rights_path, path_or_fileobj=manga.rights),
                CommitOperationAdd(path_in_repo=finished_path, path_or_fileobj=completion),
                CommitOperationAdd(path_in_repo=CANONICAL_CATALOGUE, path_or_fileobj=new_catalogue),
            ],
            f"Publish verified manga {sid} after complete media",
        )
        existing = current_entries
        catalogue = new_catalogue
        remote_files.update({before_path, rights_path, finished_path})
        uploaded += 1
    _, final_head, final_files, _, final_entries = snapshot(token)
    if final_head != head or not remote_files.issubset(final_files):
        raise UploadConflict("Private bulk-upload final catalogue/file verification failed")
    if not {b.entry["id"] for b in bundles}.issubset({e["id"] for e in final_entries}):
        raise UploadConflict("Private bulk upload failed to publish every approved manga")
    return {"status": "complete", "uploaded": uploaded, "skippedExisting": skipped,
            "revision": head, "manga": len(final_entries), "mediaDeleted": 0}


def _read_marker(path: str, sha: str, token: str) -> bytes:
    from .hf_metadata import _read_file
    return _read_file(path, sha, token, 100_000)
