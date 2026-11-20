"""Append-only verified ReLIFE canonical migration, first in a private staging branch.

All 5,606 original pages and 237 manifests stay at their legacy paths.
Copies have identical blob identities. The canonical index is published last.
No deletion, force-push, public artefact or local image reconstruction occurs.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from .domain import ControllerError, validate_manifest_json
from .hf_layout import (
    CANONICAL_CATALOGUE,
    LEGACY_CATALOGUE,
    _json_bytes,
    _migration_maps,
    canonical_library,
    legacy_migration_preview,
    validate_entries,
)
from .hf_recovery import BACKUP_BRANCH, DATASET

SOURCE_SHA = "a055b54ee5bdc980f7641bd2beb09e30fca0fb19"
EXPECTED_MAP_DIGEST = "2c43191c36362eac73e0dfd1173e28ec4e082804a7085d46c5bb4fe71b6a6f48"
EXPECTED_CATALOGUE_DIGEST = "3192ed733c480f108ffbc6acff80fe13c11f181505797df533c89bbe79916f97"
STAGING_BRANCH = "migration/relife-canonical-staging-20261120"
BATCH_SIZE = 125
EXPECTED_CHAPTERS = 237
EXPECTED_PAGES = 5606
EXPECTED_FILES = EXPECTED_CHAPTERS + EXPECTED_PAGES
MARKER_PREFIX = "control/migrations/relife-canonical-v1"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _private_revision(api: Any, revision: str, token: str) -> str:
    info = api.dataset_info(DATASET, revision=revision, token=token)
    sha = str(info.sha)
    if info.private is not True or re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        raise ControllerError("Private dataset revision is invalid or not private")
    return sha


def _download_small_file(path: str, revision: str, token: str) -> bytes:
    from huggingface_hub import hf_hub_download

    local = hf_hub_download(
        repo_id=DATASET, repo_type="dataset", filename=path, revision=revision, token=token
    )
    data = Path(local).read_bytes()
    if len(data) > 4 * 1024 * 1024:
        raise ControllerError("Private migration metadata exceeds bounded reader size")
    return data


def _source_plan(api: Any, token: str) -> tuple[dict[str, str], bytes]:
    references = api.list_repo_refs(DATASET, repo_type="dataset", token=token)
    backups = [ref for ref in references.branches if ref.name == BACKUP_BRANCH]
    if len(backups) != 1 or backups[0].target_commit != SOURCE_SHA:
        raise ControllerError("Verified ReLIFE full-history recovery branch is missing or changed")
    if _private_revision(api, BACKUP_BRANCH, token) != SOURCE_SHA:
        raise ControllerError("Protected recovery revision no longer matches original source")

    files = set(api.list_repo_files(DATASET, repo_type="dataset", revision=SOURCE_SHA, token=token))
    raw = json.loads(_download_small_file(LEGACY_CATALOGUE, SOURCE_SHA, token))
    entries = validate_entries(raw)
    if len(entries) != 1 or entries[0]["title"] != "ReLIFE":
        raise ControllerError("Unexpected source catalogue; refusing to migrate other manga")
    if len(entries[0]["chapters"]) != EXPECTED_CHAPTERS:
        raise ControllerError("Source ReLIFE chapter count changed")

    manifests: dict[str, Any] = {}
    for chapter in entries[0]["chapters"]:
        path = f"manifests/{chapter['id']}.json"
        if path not in files:
            raise ControllerError("Original chapter manifest is missing")
        value = json.loads(_download_small_file(path, SOURCE_SHA, token))
        manifest = validate_manifest_json(value)
        if manifest.chapterId != chapter["id"] or len(manifest.pages) != chapter["pageCount"]:
            raise ControllerError("Original chapter manifest does not match source catalogue")
        manifests[path] = value

    plan = legacy_migration_preview(entries, files, manifests, SOURCE_SHA)
    if (
        plan["copyMapDigest"] != EXPECTED_MAP_DIGEST
        or plan["canonicalCatalogueDigest"] != EXPECTED_CATALOGUE_DIGEST
        or plan["chapters"] != EXPECTED_CHAPTERS
        or plan["pages"] != EXPECTED_PAGES
        or plan["filesToCopyWithoutDeletingLegacy"] != EXPECTED_FILES
    ):
        raise ControllerError("Original audited migration inventory differs from pinned preflight")
    mapping = _migration_maps(entries, files, manifests)
    if len(mapping) != EXPECTED_FILES:
        raise ControllerError("Canonical copy path count differs from verified source")
    return mapping, _json_bytes(canonical_library(entries))


def _batches(mapping: dict[str, str]) -> list[list[tuple[str, str]]]:
    ordered = sorted(mapping.items())
    if len(ordered) != len({target for _, target in ordered}):
        raise ControllerError("Duplicate canonical output paths")
    return [ordered[i : i + BATCH_SIZE] for i in range(0, len(ordered), BATCH_SIZE)]


def _marker(phase: str, index: int, batch: list[tuple[str, str]]) -> tuple[str, bytes]:
    if phase not in ("staging", "production") or index < 1 or not batch:
        raise ControllerError("Unsupported private migration marker")
    digest = _sha256(
        b"".join(source.encode() + b"\0" + target.encode() + b"\n" for source, target in batch)
    )
    path = f"{MARKER_PREFIX}/{phase}/batch-{index:03}.json"
    data = _json_bytes(
        {"schemaVersion": 1, "sourceRevision": SOURCE_SHA, "part": index,
         "count": len(batch), "copyMapSha256": digest}
    )
    return path, data


def _verify_namespace(paths: set[str], mapping: dict[str, str]) -> None:
    allowed = set(mapping.values()) | {CANONICAL_CATALOGUE}
    extras = sorted(path for path in paths if path.startswith("data/") and path not in allowed)
    if extras:
        raise ControllerError("Unrecognised private data/ files; refusing migration")
    if not set(mapping).issubset(paths):
        raise ControllerError("Some original ReLIFE media or manifests have disappeared")


def _metadata(api: Any, revision: str, requested: set[str], token: str) -> dict[str, Any]:
    # RepoFile.blob_id and LFS SHA-256 are content-addressed and exposed without
    # downloading the original 1.34 GB of images to GitHub Actions.
    data: dict[str, Any] = {}
    for item in api.list_repo_tree(
        DATASET, repo_type="dataset", revision=revision,
        recursive=True, expand=False, token=token
    ):
        path = getattr(item, "path", None)
        if path in requested and hasattr(item, "blob_id"):
            data[path] = item
    if set(data) != requested:
        raise ControllerError("Remote source or copied file metadata is incomplete")
    return data


def _identity(item: Any) -> tuple[int, str, str]:
    lfs = getattr(item, "lfs", None)
    lfs_sha = lfs.get("sha256") if isinstance(lfs, dict) else getattr(lfs, "sha256", None)
    size, blob_id = getattr(item, "size", None), getattr(item, "blob_id", None)
    if type(size) is not int or size <= 0 or not isinstance(blob_id, str) or not blob_id:
        raise ControllerError("Original or copied file lacks verifiable identity metadata")
    return size, blob_id, str(lfs_sha or "")


def _verify_content_identities(
    api: Any, revision: str, mapping: dict[str, str], token: str
) -> None:
    before = _metadata(api, SOURCE_SHA, set(mapping), token)
    after = _metadata(api, revision, set(mapping.values()), token)
    for original, copied in mapping.items():
        if _identity(before[original]) != _identity(after[copied]):
            raise ControllerError("Copied image or manifest content identity differs from original")
    print(
        json.dumps({"verification": "identical-original-and-copy-metadata",
                    "revision": revision, "verifiedFiles": len(mapping)}),
        flush=True,
    )


def _create_staging_branch(api: Any, token: str) -> None:
    refs = api.list_repo_refs(DATASET, repo_type="dataset", token=token)
    existing = [ref for ref in refs.branches if ref.name == STAGING_BRANCH]
    if len(existing) > 1:
        raise ControllerError("Ambiguous private staging revision")
    if not existing:
        api.create_branch(
            repo_id=DATASET, repo_type="dataset", branch=STAGING_BRANCH,
            revision=SOURCE_SHA, token=token, exist_ok=False
        )
        print("Created isolated private migration staging branch", flush=True)


def _copy_phase(
    api: Any, token: str, phase: str, branch: str,
    mapping: dict[str, str], catalogue: bytes
) -> str:
    from huggingface_hub import CommitOperationAdd, CommitOperationCopy

    sha = _private_revision(api, branch, token)
    paths = set(api.list_repo_files(DATASET, repo_type="dataset", revision=sha, token=token))
    _verify_namespace(paths, mapping)
    batches = _batches(mapping)
    for idx, batch in enumerate(batches, 1):
        marker_path, marker_content = _marker(phase, idx, batch)
        targets = {target for _, target in batch}
        if marker_path in paths:
            if not targets.issubset(paths):
                raise ControllerError("A prior migration checkpoint references missing copied pages")
            if _download_small_file(marker_path, sha, token) != marker_content:
                raise ControllerError("A migration checkpoint does not match pinned source files")
            continue
        if targets & paths:
            raise ControllerError("Uncheckpointed canonical files present; refusing overwrite")
        if _private_revision(api, branch, token) != sha:
            raise ControllerError("Private dataset branch changed unexpectedly during migration")
        ops = [
            CommitOperationCopy(
                src_path_in_repo=src, path_in_repo=dst, src_revision=SOURCE_SHA
            )
            for src, dst in batch
        ]
        ops.append(CommitOperationAdd(path_in_repo=marker_path, path_or_fileobj=marker_content))
        api.create_commit(
            repo_id=DATASET, repo_type="dataset", revision=branch, token=token,
            parent_commit=sha, operations=ops, num_threads=5,
            commit_message=f"Canonical ReLIFE {phase} copy {idx}/{len(batches)}"
        )
        next_sha = _private_revision(api, branch, token)
        if next_sha == sha:
            raise ControllerError("Private migration commit did not advance revision")
        sha = next_sha
        paths.update(targets)
        paths.add(marker_path)
        print(
            json.dumps({"phase": phase, "batchesDone": idx, "batchesTotal": len(batches),
                        "copiedFiles": len(targets)}), flush=True
        )

    if not set(mapping.values()).issubset(paths):
        raise ControllerError("Private dataset canonical content is incomplete")
    _verify_content_identities(api, sha, mapping, token)
    if CANONICAL_CATALOGUE in paths:
        if _download_small_file(CANONICAL_CATALOGUE, sha, token) != catalogue:
            raise ControllerError("Existing canonical library differs from verified ReLIFE metadata")
    else:
        if _private_revision(api, branch, token) != sha:
            raise ControllerError("Private dataset changed before canonical library publication")
        api.create_commit(
            repo_id=DATASET, repo_type="dataset", revision=branch, token=token,
            parent_commit=sha, operations=[
                CommitOperationAdd(path_in_repo=CANONICAL_CATALOGUE, path_or_fileobj=catalogue)
            ],
            commit_message=f"Publish verified ReLIFE canonical library ({phase})"
        )
        sha = _private_revision(api, branch, token)
        if _download_small_file(CANONICAL_CATALOGUE, sha, token) != catalogue:
            raise ControllerError("Canonical library publication failed read-back verification")
    final_paths = set(api.list_repo_files(DATASET, repo_type="dataset", revision=sha, token=token))
    if not set(mapping).issubset(final_paths):
        raise ControllerError("Legacy original paths are missing after migration")
    if not set(mapping.values()).issubset(final_paths):
        raise ControllerError("Canonical copied paths are missing after migration")
    print(json.dumps({"phase": phase, "status": "complete",
                      "revision": sha, "pages": EXPECTED_PAGES,
                      "manifests": EXPECTED_CHAPTERS, "legacyPreserved": True}), flush=True)
    return sha


def migrate(token: str) -> dict[str, object]:
    from huggingface_hub import HfApi

    if not token:
        raise ControllerError("Protected Hugging Face token is required")
    api = HfApi(token=token)
    mapping, catalogue = _source_plan(api, token)
    _create_staging_branch(api, token)
    staging_sha = _copy_phase(api, token, "staging", STAGING_BRANCH, mapping, catalogue)
    # The user explicitly authorised an append-only production migration.
    # No existing media, catalogue, control files or snapshots are deleted.
    production_sha = _copy_phase(api, token, "production", "main", mapping, catalogue)
    return {"status": "canonical-migration-complete", "private": True,
            "recoveryRevision": SOURCE_SHA, "stagingRevision": staging_sha,
            "productionRevision": production_sha, "originalFilesPreserved": EXPECTED_FILES,
            "canonicalFilesVerified": EXPECTED_FILES + 1, "mainModified": True}


def main() -> int:
    try:
        result = migrate(os.getenv("HF_TOKEN", ""))
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0
    except Exception as exc:
        # Never expose credentials, temporary URLs, or private source data in logs.
        if isinstance(exc, ControllerError):
            print(f"Canonical private migration halted safely: {exc}", file=sys.stderr)
        else:
            print(f"Canonical private migration halted ({type(exc).__name__})", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
