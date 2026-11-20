"""Preview-first private HF metadata amendments; chapter/page files are read-only.

A guarded commit writes new cover images, a byte-identical catalogue backup and
the revised canonical library atomically with an expected parent revision.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from .domain import ControllerError
from .hf_layout import CANONICAL_CATALOGUE, MAX_LIBRARY_BYTES, canonical_library, validate_library
from .hf_upload import DATASET, UploadConflict
from .metadata import (
    MAX_COVER_BYTES,
    completeness,
    cover_asset_path,
    encoded,
    load_candidates,
    reconcile,
)

BACKUP_ROOT = "control/metadata-backups"
HEAD_RE = re.compile(r"^[0-9a-f]{40}$")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _api(token: str) -> Any:
    if not token:
        raise ControllerError("A private Hugging Face token is required")
    from huggingface_hub import HfApi

    return HfApi(token=token)


def _read_file(name: str, revision: str, token: str, limit: int) -> bytes:
    from huggingface_hub import hf_hub_download

    location = hf_hub_download(
        repo_id=DATASET, filename=name, repo_type="dataset", revision=revision, token=token
    )
    with Path(location).open("rb") as handle:
        contents = handle.read(limit + 1)
    if len(contents) > limit:
        raise ControllerError("Remote catalogue or cover exceeds its strict size limit")
    return contents


def _snapshot(api: Any, token: str) -> tuple[str, set[str], bytes, list[dict[str, Any]]]:
    info = api.dataset_info(DATASET, token=token)
    if info.private is not True or not isinstance(info.sha, str) or not HEAD_RE.fullmatch(info.sha):
        raise ControllerError("Canonical metadata can be updated only in the verified private dataset")
    sha = info.sha
    paths = set(api.list_repo_files(DATASET, repo_type="dataset", revision=sha, token=token))
    if CANONICAL_CATALOGUE not in paths:
        raise ControllerError("Canonical data/library.json is missing")
    raw = _read_file(CANONICAL_CATALOGUE, sha, token, MAX_LIBRARY_BYTES)
    try:
        entries = validate_library(json.loads(raw))
    except (ValueError, UnicodeError) as exc:
        raise ControllerError("Existing private manga library is invalid") from exc
    for entry in entries:
        cover = entry.get("cover")
        if cover and cover_asset_path(cover, entry["id"]) not in paths:
            raise ControllerError("Existing catalogue contains a missing private cover")
    return sha, paths, raw, entries


def _planned(
    sha: str,
    paths: set[str],
    raw: bytes,
    entries: list[dict[str, Any]],
    candidates_file: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Path], dict[str, bytes]]:
    candidates, candidate_digest = load_candidates(candidates_file)
    result, uploads, changes, conflicts = reconcile(
        entries, candidates, candidates_file.parent, paths
    )
    dest = canonical_library(result)
    upload_details: list[dict[str, object]] = []
    rights_records: dict[str, bytes] = {}
    for candidate in candidates:
        manga_id = candidate.get("mangaId")
        cover = candidate["metadata"].get("cover")
        if not manga_id or not cover:
            continue
        asset = next(
            (
                (path, item)
                for path, item in uploads.items()
                if path.startswith(f"data/covers/{manga_id}.")
            ),
            None,
        )
        if asset is None:
            continue
        descriptor = next(
            entry["cover"] for entry in result if entry["id"] == manga_id
        )
        record = {
            "schemaVersion": 1,
            "mangaId": manga_id,
            "coverSha256": descriptor["sha256"],
            "source": candidate["source"],
            "rightsEvidence": cover["rightsEvidence"],
            "attribution": cover["attribution"],
        }
        rights_path = (
            f"control/cover-rights/{manga_id}/{descriptor['sha256']}.json"
        )
        if rights_path in rights_records or rights_path in paths:
            conflicts.append(f"{manga_id}: cover rights record already exists")
        rights_records[rights_path] = encoded(record)
    for name, local in sorted(uploads.items()):
        if name in paths:
            conflicts.append(f"Private cover path already exists: {name}")
            continue
        with local.open("rb") as handle:
            contents = handle.read(MAX_COVER_BYTES + 1)
        if len(contents) > MAX_COVER_BYTES:
            raise ControllerError("Cover changed or exceeds bounded upload budget")
        upload_details.append({"path": name, "sha256": _sha(contents), "byteSize": len(contents)})
    for entry in result:
        cover = entry.get("cover")
        if cover:
            path = cover_asset_path(cover, entry["id"])
            if path not in paths and path not in uploads:
                conflicts.append(f"{entry['id']}: metadata cover references an absent file")
    digest = _sha(encoded(dest))
    backup = f"{BACKUP_ROOT}/{sha}/library.json"
    if backup in paths:
        conflicts.append("A metadata catalogue backup already exists at this exact revision")
    if conflicts:
        status = "conflict"
    elif not changes:
        status = "no-op"
    else:
        status = "ready"
    plan = {
        "schemaVersion": 1,
        "kind": "private-manga-metadata-preview",
        "dataset": DATASET,
        "expectedRevision": sha,
        "catalogueSha256": _sha(raw),
        "candidateSha256": candidate_digest,
        "newCatalogueSha256": digest,
        "backupPath": backup,
        "status": status,
        "changes": changes,
        "conflicts": conflicts,
        "coverUploads": upload_details,
        "coverRights": [
            {"path": path, "sha256": _sha(contents)}
            for path, contents in sorted(rights_records.items())
        ],
        "before": completeness(entries),
        "after": completeness(result),
        "deleteOperations": 0,
        "chapterOrPageWrites": 0,
    }
    return plan, result, uploads, rights_records


def preview(api: Any, token: str, candidates_file: Path) -> dict[str, Any]:
    revision, paths, contents, entries = _snapshot(api, token)
    plan, _, _, _ = _planned(revision, paths, contents, entries, candidates_file)
    return plan


def apply(
    api: Any,
    token: str,
    candidates_file: Path,
    plan_file: Path,
    *,
    approve: bool = False,
) -> dict[str, Any]:
    if not approve:
        raise ControllerError("Explicit owner approval is mandatory for private metadata edits")
    if not plan_file.is_file() or plan_file.is_symlink():
        raise ControllerError("Approved metadata preview is missing or unsafe")
    with plan_file.open("rb") as stream:
        approval_bytes = stream.read(MAX_LIBRARY_BYTES + 1)
    if len(approval_bytes) > MAX_LIBRARY_BYTES:
        raise ControllerError("Metadata approval preview exceeds size limit")
    approved = json.loads(approval_bytes)
    sha, paths, old_bytes, entries = _snapshot(api, token)
    plan, merged, covers, rights_records = _planned(
        sha, paths, old_bytes, entries, candidates_file
    )
    if plan != approved:
        raise UploadConflict("Dataset, candidates, or preview changed; approval is stale")
    if plan["status"] == "conflict":
        raise UploadConflict("Metadata reconciliation contains conflicts requiring manual review")
    if plan["status"] == "no-op":
        return {"status": "no-op", "revision": sha, "series": len(entries)}
    if plan["status"] != "ready":
        raise UploadConflict("Unrecognised metadata plan state")

    from huggingface_hub import CommitOperationAdd

    operations: list[Any] = []
    for row in plan["coverUploads"]:
        path = str(row["path"])
        local = covers[path]
        with local.open("rb") as handle:
            image = handle.read(MAX_COVER_BYTES + 1)
        if len(image) != row["byteSize"] or _sha(image) != row["sha256"]:
            raise UploadConflict("Cover artwork changed since preview")
        operations.append(CommitOperationAdd(path_in_repo=path, path_or_fileobj=image))

    operations.extend(
        CommitOperationAdd(path_in_repo=name, path_or_fileobj=body)
        for name, body in sorted(rights_records.items())
    )
    operations.extend(
        [
            CommitOperationAdd(path_in_repo=str(plan["backupPath"]), path_or_fileobj=old_bytes),
            CommitOperationAdd(
                path_in_repo=CANONICAL_CATALOGUE,
                path_or_fileobj=encoded(canonical_library(merged)),
            ),
        ]
    )
    current = api.dataset_info(DATASET, token=token)
    if current.sha != sha or current.private is not True:
        raise UploadConflict("Private dataset changed before approved metadata commit")
    api.create_commit(
        repo_id=DATASET,
        repo_type="dataset",
        operations=operations,
        revision="main",
        parent_commit=sha,
        commit_message="Reconcile verified publication metadata and private cover artwork",
        token=token,
        num_threads=3,
    )
    new_sha, new_files, _, new_entries = _snapshot(api, token)
    if new_sha == sha or new_entries != merged or plan["backupPath"] not in new_files:
        raise UploadConflict("Post-write verification failed for the canonical metadata catalogue")
    if _read_file(str(plan["backupPath"]), new_sha, token, MAX_LIBRARY_BYTES) != old_bytes:
        raise UploadConflict("Original catalogue backup is not byte identical")
    for row in plan["coverRights"]:
        path = str(row["path"])
        if path not in new_files:
            raise UploadConflict("Private cover rights record is missing after commit")
        if _sha(_read_file(path, new_sha, token, MAX_LIBRARY_BYTES)) != row["sha256"]:
            raise UploadConflict("Cover provenance record changed during metadata commit")
    for row in plan["coverUploads"]:
        path = str(row["path"])
        if path not in new_files:
            raise UploadConflict("New private cover image is missing after commit")
        if _sha(_read_file(path, new_sha, token, MAX_COVER_BYTES)) != row["sha256"]:
            raise UploadConflict("New private cover image checksum differs from preview")
    return {
        "status": "complete",
        "previousRevision": sha,
        "revision": new_sha,
        "changes": len(plan["changes"]),
        "coversAdded": len(plan["coverUploads"]),
        "coverRightsStored": len(plan["coverRights"]),
        "catalogueBackup": plan["backupPath"],
        "series": len(merged),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Safe private Manga Library metadata reconciliation")
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--plan-file", type=Path)
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args(argv)
    try:
        token = os.getenv("HF_TOKEN", "")
        api = _api(token)
        if args.report_only:
            revision, paths, _, entries = _snapshot(api, token)
            report = completeness(entries)
            report["revision"] = revision
            report["private"] = True
            report["physicalCoverReferencesVerified"] = bool(paths)
            print(json.dumps(report, sort_keys=True))
            return 0
        if args.candidates is None or args.plan_file is None:
            raise ControllerError("Both --candidates and --plan-file are required")
        if args.apply:
            output = apply(api, token, args.candidates, args.plan_file, approve=args.approve)
        else:
            output = preview(api, token, args.candidates)
            with args.plan_file.open("x", encoding="utf-8") as stream:
                json.dump(output, stream, sort_keys=True)
                stream.write("\n")
        print(json.dumps(output, sort_keys=True))
        return 0 if output.get("status") not in ("conflict",) else 2
    except (ControllerError, ValueError, OSError) as exc:
        print(f"Private manga metadata operation refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
