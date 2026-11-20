"""Private, append-only ReLIFE upload with expected-parent commits and durable checkpoints.

Only an owner-approved master-branch workflow may call apply. This module does not
create datasets, modify existing files, delete media or publish repository secrets.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .builder import load_json, verify_bundle
from .domain import ControllerError
from .relife_intake import EXPECTED_CHAPTERS as EXPECTED_CHAPTER_NUMBERS
from .relife_stage import _stable_registry

DATASET = "AdityaSreevatsaK/Taiyous-Manga"
SOURCE_RUN = 44547390262
PREFIX = "ingest/relife-v1"
BATCH_SIZE = 200
EXPECTED_CHAPTERS = 237
EXPECTED_PAGES = 5606


class UploadConflict(ControllerError):
    """Dataset changed, or files already exist with unknown content."""


@dataclass(frozen=True)
class UploadFile:
    path: str
    local: Path
    digest: str
    size: int


def _digest_file(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            sha.update(block)
    return sha.hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _digest_records(records: list[UploadFile]) -> str:
    sha = hashlib.sha256()
    for record in records:
        sha.update(f"{record.path}\0{record.size}\0{record.digest}\n".encode())
    return sha.hexdigest()


def _candidate(bundle: Path, registry: Path) -> tuple[list[UploadFile], list[UploadFile]]:
    result = verify_bundle(bundle)
    if result["chapters"] != EXPECTED_CHAPTERS or result["pages"] != EXPECTED_PAGES:
        raise ControllerError("ReLIFE candidate is not the fully verified 237-chapter / 5606-page edition")
    entries = load_json(bundle / "catalogue.json")
    if len(entries) != 1 or entries[0]["title"] != "ReLIFE":
        raise ControllerError("Only the approved single-series ReLIFE catalogue may be uploaded")
    if entries[0]["direction"] != "vertical":
        raise ControllerError("ReLIFE reading direction has changed")
    if registry.is_symlink() or not registry.is_file():
        raise ControllerError("Private ReLIFE identity registry is missing or unsafe")
    identities = load_json(registry)
    if identities != _stable_registry(set(EXPECTED_CHAPTER_NUMBERS)):
        raise ControllerError("ReLIFE persistent IDs must match the deterministic v1 mapping")
    if identities.get("series:ReLIFE") != entries[0]["id"]:
        raise ControllerError("Persistent ReLIFE series identity mismatch")
    for chapter in entries[0]["chapters"]:
        key = "chapter:ReLIFE/" + chapter["label"] + ".cbz"
        if identities.get(key) != chapter["id"]:
            raise ControllerError("Persistent ReLIFE chapter identity mismatch")

    def record(path: Path, name: str) -> UploadFile:
        if path.is_symlink() or not path.is_file():
            raise ControllerError("Unsafe upload source file")
        return UploadFile(name, path, _digest_file(path), path.stat().st_size)

    # Only these paths are uploaded. No arbitrary contents of the source folder.
    assets = sorted((bundle / "assets" / "manga").rglob("*"))
    assets = [path for path in assets if path.is_file()]
    if len(assets) != EXPECTED_PAGES:
        raise ControllerError("ReLIFE source media count changed")
    media = [record(path, path.relative_to(bundle).as_posix()) for path in assets]
    manifest_paths = sorted((bundle / "manifests").glob("*.json"))
    if len(manifest_paths) != EXPECTED_CHAPTERS:
        raise ControllerError("ReLIFE chapter manifest count changed")
    metadata = [record(path, path.relative_to(bundle).as_posix()) for path in manifest_paths]
    metadata.append(record(bundle / "catalogue.json", "catalogue.json"))
    metadata.append(record(registry, "control/relife-identities.json"))
    return media, metadata


def _attestation() -> dict[str, object]:
    # This is the owner's assertion, not independently verified rights evidence.
    return {
        "schemaVersion": 1,
        "sourceRun": SOURCE_RUN,
        "dataset": DATASET,
        "permissionType": "user-attested",
        "ownerStatement": (
            "User confirmed permission to store these ReLIFE English scans in the private dataset"
        ),
        "affirmedOn": "2026-11-20",
        "independentlyVerified": False,
        "source": "MangaDex ReLIFE English user-uploaded edition; ReLIFE by YayoiSo",
    }


def _partition(files: list[UploadFile]) -> list[list[UploadFile]]:
    return [files[i : i + BATCH_SIZE] for i in range(0, len(files), BATCH_SIZE)]


def _checkpoint(index: int, files: list[UploadFile]) -> tuple[str, bytes]:
    path = f"{PREFIX}/part-{index:03}.json"
    data = {
        "schemaVersion": 1,
        "sourceRun": SOURCE_RUN,
        "part": index,
        "fileCount": len(files),
        "sha256": _digest_records(files),
    }
    return path, _json_bytes(data)


def _final_metadata(records: list[UploadFile], batches: list[list[UploadFile]]) -> tuple[str, bytes]:
    path = f"{PREFIX}/complete.json"
    data = {
        "schemaVersion": 1,
        "sourceRun": SOURCE_RUN,
        "dataset": DATASET,
        "chapters": EXPECTED_CHAPTERS,
        "pages": EXPECTED_PAGES,
        "parts": len(batches),
        "partDigests": [_digest_records(part) for part in batches],
        "metadataDigest": _digest_records(records),
        "status": "complete",
    }
    return path, _json_bytes(data)


def _hf_api(token: str) -> Any:
    try:
        from huggingface_hub import HfApi
    except ImportError as exc:
        raise ControllerError("Install the optional Hugging Face dependency") from exc
    return HfApi(token=token)


def _read_checkpoint(filename: str, sha: str, token: str) -> bytes:
    from huggingface_hub import hf_hub_download

    location = hf_hub_download(
        repo_id=DATASET, filename=filename, repo_type="dataset", revision=sha, token=token
    )
    return Path(location).read_bytes()


def _remote(api: Any, token: str) -> tuple[str, set[str]]:
    info = api.dataset_info(DATASET, token=token)
    if not info.private or not isinstance(info.sha, str) or len(info.sha) < 20:
        raise ControllerError("Hugging Face dataset must be private and have an expected parent revision")
    names = set(api.list_repo_files(DATASET, revision=info.sha, repo_type="dataset", token=token))
    return info.sha, names


def _inspect(
    api: Any, token: str, media: list[UploadFile], metadata: list[UploadFile]
) -> tuple[dict[str, object], list[list[UploadFile]], tuple[str, bytes], str, set[str]]:
    sha, remote_files = _remote(api, token)
    batches = _partition(media)
    extras = _attestation()
    permission_path = f"{PREFIX}/attestation.json"
    metadata_records = [
        *metadata,
        UploadFile(
            permission_path,
            Path("."),
            hashlib.sha256(_json_bytes(extras)).hexdigest(),
            len(_json_bytes(extras)),
        ),
    ]
    completion = _final_metadata(metadata_records, batches)
    final_paths = {item.path for item in metadata_records} | {completion[0]}
    all_paths = {item.path for item in media} | final_paths
    if len(all_paths) != len(media) + len(metadata_records) + 1:
        raise ControllerError("Duplicate source paths in proposed upload")

    # Published catalogues must never be replaced, even when upload was interrupted.
    if "catalogue.json" in remote_files and completion[0] not in remote_files:
        raise UploadConflict("A catalogue already exists without this complete ReLIFE ingestion marker")
    if completion[0] in remote_files:
        if _read_checkpoint(completion[0], sha, token) != completion[1]:
            raise UploadConflict("Existing ReLIFE publication marker does not match this candidate")
        all_checkpoints = {_checkpoint(index, part)[0] for index, part in enumerate(batches, start=1)}
        if not (all_paths | all_checkpoints).issubset(remote_files):
            raise UploadConflict("Published ReLIFE marker refers to missing media or metadata")
        return (
            {
                "status": "already-complete",
                "expectedRevision": sha,
                "totalParts": len(batches),
                "remainingParts": 0,
                "chapters": EXPECTED_CHAPTERS,
                "pages": EXPECTED_PAGES,
                "manifestDigest": json.loads(completion[1])["metadataDigest"],
                "uploadAllowed": True,
            },
            batches,
            completion,
            sha,
            remote_files,
        )
    if any(path in remote_files for path in final_paths):
        raise UploadConflict("Partial or conflicting publication metadata already exists")
    remaining = 0
    for index, batch in enumerate(batches, start=1):
        marker, bytes_marker = _checkpoint(index, batch)
        expected = {item.path for item in batch}
        if marker in remote_files:
            if not expected.issubset(remote_files):
                raise UploadConflict("Committed chunk marker has missing media files")
            if _read_checkpoint(marker, sha, token) != bytes_marker:
                raise UploadConflict("Existing chunk marker differs from local verified source")
        else:
            if expected & remote_files:
                raise UploadConflict("Some media paths exist without the expected atomic chunk marker")
            remaining += 1
    return (
        {
            "status": "append-only-ready",
            "expectedRevision": sha,
            "totalParts": len(batches),
            "remainingParts": remaining,
            "chapters": EXPECTED_CHAPTERS,
            "pages": EXPECTED_PAGES,
            "manifestDigest": json.loads(completion[1])["metadataDigest"],
            "uploadAllowed": True,
        },
        batches,
        completion,
        sha,
        remote_files,
    )


def preview_relife_upload(bundle: Path, registry: Path, token: str) -> dict[str, object]:
    if not token:
        raise ControllerError("HF_TOKEN must be provided as a protected environment secret")
    media, metadata = _candidate(bundle, registry)
    plan, _, _, _, _ = _inspect(_hf_api(token), token, media, metadata)
    return plan


def apply_relife_upload(
    bundle: Path, registry: Path, token: str, approved_plan: Path, *, approve: bool
) -> dict[str, object]:
    """The sole explicit remote-write entrypoint. Every mutation uses parent_commit."""
    if not approve:
        raise ControllerError("Explicit owner approval is required for live HF uploads")
    if not token:
        raise ControllerError("HF_TOKEN is missing")
    from huggingface_hub import CommitOperationAdd

    media, metadata = _candidate(bundle, registry)
    api = _hf_api(token)
    plan, batches, completion, head, paths = _inspect(api, token, media, metadata)
    approval = load_json(approved_plan)
    if (
        not isinstance(approval, dict)
        or approval.get("expectedRevision") != head
        or approval.get("manifestDigest") != plan["manifestDigest"]
        or approval.get("totalParts") != plan["totalParts"]
        or approval.get("remainingParts") != plan["remainingParts"]
        or plan["uploadAllowed"] is not True
    ):
        raise UploadConflict("Source candidate or HF revision changed since approved preview")
    if plan["status"] == "already-complete":
        return {"status": "already-complete", "revision": head, "partsWritten": 0}

    def commit(operations: list[Any], message: str) -> None:
        nonlocal head
        if api.dataset_info(DATASET, token=token).sha != head:
            raise UploadConflict("Private dataset changed during the upload")
        result = api.create_commit(
            repo_id=DATASET,
            repo_type="dataset",
            operations=operations,
            commit_message=message,
            parent_commit=head,
            token=token,
            num_threads=5,
        )
        new_sha = getattr(result, "oid", None)
        if not isinstance(new_sha, str) or len(new_sha) < 20:
            new_sha = api.dataset_info(DATASET, token=token).sha
        if not isinstance(new_sha, str) or new_sha == head:
            raise UploadConflict("Hugging Face commit did not advance the dataset revision")
        head = new_sha

    added = 0
    for index, batch in enumerate(batches, start=1):
        marker, marker_bytes = _checkpoint(index, batch)
        if marker in paths:
            continue
        ops = [CommitOperationAdd(path_in_repo=item.path, path_or_fileobj=item.local) for item in batch]
        ops.append(CommitOperationAdd(path_in_repo=marker, path_or_fileobj=marker_bytes))
        commit(ops, f"Ingest ReLIFE verified pages part {index}/{len(batches)}")
        paths.update(item.path for item in batch)
        paths.add(marker)
        added += 1
        print(f"Uploaded validated private ReLIFE page batch {index}/{len(batches)}", flush=True)

    # This is the atomic publication barrier: the reader cannot see ReLIFE in
    # catalogue.json until all original pages and manifests are in the dataset.
    permission_path = f"{PREFIX}/attestation.json"
    ops = [CommitOperationAdd(path_in_repo=item.path, path_or_fileobj=item.local) for item in metadata]
    ops.append(CommitOperationAdd(path_in_repo=permission_path, path_or_fileobj=_json_bytes(_attestation())))
    ops.append(CommitOperationAdd(path_in_repo=completion[0], path_or_fileobj=completion[1]))
    commit(ops, "Publish verified private ReLIFE catalogue after complete media upload")
    expected = (
        {item.path for item in media} | {item.path for item in metadata} | {permission_path, completion[0]}
    )
    actual = set(api.list_repo_files(DATASET, repo_type="dataset", revision=head, token=token))
    if not expected.issubset(actual):
        raise UploadConflict("HF dataset commit succeeded but post-upload file inventory is incomplete")
    return {
        "status": "complete",
        "revision": head,
        "partsWritten": added,
        "chapters": EXPECTED_CHAPTERS,
        "pages": EXPECTED_PAGES,
        "private": True,
    }


def cli(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Revision-guarded private ReLIFE upload")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--plan-file", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args(argv)
    try:
        token = os.getenv("HF_TOKEN", "")
        if args.apply:
            result = apply_relife_upload(
                args.bundle, args.registry, token, args.plan_file, approve=args.approve
            )
            print(json.dumps(result, sort_keys=True))
        else:
            result = preview_relife_upload(args.bundle, args.registry, token)
            if args.plan_file.exists():
                raise ControllerError("Preview file already exists; refusing overwrite")
            with args.plan_file.open("x", encoding="utf-8") as output:
                json.dump(result, output, sort_keys=True)
                output.write("\n")
            print(json.dumps(result, sort_keys=True))
    except (ControllerError, OSError) as exc:
        print(f"HF import refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
