"""Guarded canonical data/ manga uploads; no legacy root-catalogue publication.

The title's media arrives as immutable commits. Only the final commit merges the
single candidate entry into the existing catalogue with expected-parent CAS.
All other titles and previously published ReLIFE page paths are untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from .builder import load_json, verify_bundle
from .domain import ControllerError
from .hf_upload import (
    DATASET,
    UploadConflict,
    UploadFile,
    _digest_records,
    _hf_api,
    _json_bytes,
    _read_checkpoint,
)
from .hf_layout import CANONICAL_CATALOGUE, canonical_library, validate_library
from .selected_stage import stable_registry
from .selected_titles import TITLES, SelectedTitle, selected_title

MAX_BATCH_FILES = 150


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record(path: Path, name: str) -> UploadFile:
    if path.is_symlink() or not path.is_file():
        raise ControllerError("Selected manga candidate file is missing or linked")
    digest = hashlib.sha256()
    with path.open("rb") as inp:
        while block := inp.read(1024 * 1024):
            digest.update(block)
    return UploadFile(name, path, digest.hexdigest(), path.stat().st_size)


def candidate_files(
    title: SelectedTitle, bundle: Path, registry_file: Path
) -> tuple[list[UploadFile], list[UploadFile], dict[str, Any]]:
    inventory = verify_bundle(bundle)
    catalogue = load_json(bundle / "catalogue.json")
    if (
        inventory["series"] != 1
        or not isinstance(catalogue, list)
        or len(catalogue) != 1
        or catalogue[0]["title"] != title.name
        or catalogue[0]["direction"] != "vertical"
        or len(catalogue[0]["chapters"]) < title.main_chapters
    ):
        raise ControllerError("Selected manga candidate is not a verified complete single title")
    entry = catalogue[0]
    labels = [chapter["label"] for chapter in entry["chapters"]]
    numbers = {
        label.removeprefix("Chapter ")
        for label in labels
        if isinstance(label, str) and label.startswith("Chapter ")
    }
    if len(labels) != len(numbers):
        raise ControllerError("Selected manga candidate has ambiguous chapter numbers")
    if not all(str(n) in numbers for n in range(1, title.main_chapters + 1)):
        raise ControllerError("Selected manga candidate is missing numbered chapters")
    if registry_file.is_symlink() or not registry_file.is_file():
        raise ControllerError("Selected manga persistent ID registry is missing")
    if load_json(registry_file) != stable_registry(title, numbers):
        raise ControllerError("Selected manga source IDs disagree with deterministic registry")
    assets = sorted(path for path in (bundle / "assets" / "manga").rglob("*") if path.is_file())
    if len(assets) != inventory["pages"] or not assets:
        raise ControllerError("Selected manga image inventory differs from candidate manifest")
    media = [_record(path, "data/" + path.relative_to(bundle).as_posix().removeprefix("assets/")) for path in assets]
    manifests = sorted((bundle / "manifests").glob("*.json"))
    if len(manifests) != len(labels):
        raise ControllerError("Selected manga chapter manifest inventory changed")
    metadata = [_record(path, "data/" + path.relative_to(bundle).as_posix()) for path in manifests]
    metadata.append(_record(registry_file, f"control/{title.slug}-identities.json"))
    return media, metadata, entry


def _repo_state(api: Any, token: str) -> tuple[str, set[str]]:
    info = api.dataset_info(DATASET, token=token)
    if not info.private or not isinstance(info.sha, str) or len(info.sha) < 20:
        raise ControllerError("Selected manga destination must be private and have a valid revision")
    paths = set(api.list_repo_files(DATASET, repo_type="dataset", revision=info.sha, token=token))
    return info.sha, paths


def _old_catalogue(sha: str, paths: set[str], token: str) -> tuple[list[dict[str, Any]], str]:
    """Only append into the already verified canonical Manga Library index."""
    if CANONICAL_CATALOGUE not in paths:
        raise UploadConflict("ReLIFE canonical migration incomplete: data/library.json is missing")
    from huggingface_hub import hf_hub_download

    filename = hf_hub_download(
        repo_id=DATASET, filename=CANONICAL_CATALOGUE, repo_type="dataset",
        revision=sha, token=token
    )
    contents = Path(filename).read_bytes()
    if len(contents) > 4 * 1024 * 1024:
        raise UploadConflict("Canonical manga catalogue exceeds reader size budget")
    try:
        entries = validate_library(json.loads(contents))
    except (ControllerError, ValueError, UnicodeError) as exc:
        raise UploadConflict("Existing canonical manga library failed runtime contract") from exc
    relife = [item for item in entries if item.get("title") == "ReLIFE"]
    if len(relife) != 1:
        raise UploadConflict("Cannot append titles before ReLIFE is in the canonical library")
    for chapter in relife[0]["chapters"]:
        if f"data/manifests/{chapter['id']}.json" not in paths:
            raise UploadConflict("Canonical ReLIFE chapter manifests are incomplete")
    if not any(path.startswith(f"data/manga/{relife[0]['id']}/") for path in paths):
        raise UploadConflict("Canonical ReLIFE page media are missing")
    return entries, _hash(contents)


def _parts(media: list[UploadFile]) -> list[list[UploadFile]]:
    return [media[i : i + MAX_BATCH_FILES] for i in range(0, len(media), MAX_BATCH_FILES)]


def _marker(title: SelectedTitle, idx: int, files: list[UploadFile]) -> tuple[str, bytes]:
    return (
        f"ingest/{title.slug}-v1/part-{idx:03}.json",
        _json_bytes(
            {
                "schemaVersion": 1,
                "slug": title.slug,
                "sourceRun": title.run_id,
                "part": idx,
                "count": len(files),
                "sha256": _digest_records(files),
            }
        ),
    )


def _permission(title: SelectedTitle) -> bytes:
    return _json_bytes(
        {
            "schemaVersion": 1,
            "title": title.name,
            "sourceRun": title.run_id,
            "sourceTitleUrl": f"https://mangadex.org/title/{title.source_id}",
            "personalPrivateUploadRequested": True,
            "permissionStatementDate": "2026-11-20",
            "independentlyVerified": False,
            "privateDestination": DATASET,
        }
    )


def _completion(
    title: SelectedTitle,
    entry: dict[str, Any],
    media: list[UploadFile],
    meta: list[UploadFile],
    parts: list[list[UploadFile]],
) -> tuple[str, bytes]:
    path = f"ingest/{title.slug}-v1/complete.json"
    return path, _json_bytes(
        {
            "schemaVersion": 1,
            "slug": title.slug,
            "sourceRun": title.run_id,
            "seriesId": entry["id"],
            "chapters": len(entry["chapters"]),
            "pages": len(media),
            "totalParts": len(parts),
            "partDigests": [_digest_records(part) for part in parts],
            "metadataDigest": _digest_records(meta),
            "permissionDigest": _hash(_permission(title)),
            "status": "complete",
        }
    )


def inspect_selected(
    api: Any,
    token: str,
    title: SelectedTitle,
    media: list[UploadFile],
    metadata: list[UploadFile],
    entry: dict[str, Any],
) -> tuple[dict[str, object], list[list[UploadFile]], tuple[str, bytes], str, set[str], list[dict[str, Any]]]:
    sha, paths = _repo_state(api, token)
    catalogue, catalogue_sha = _old_catalogue(sha, paths, token)
    parts = _parts(media)
    completed = _completion(title, entry, media, metadata, parts)
    attestation = f"ingest/{title.slug}-v1/attestation.json"
    expected_paths = {item.path for item in [*media, *metadata]}
    if len(expected_paths) != len(media) + len(metadata):
        raise ControllerError("Selected manga candidate contains duplicate target file paths")
    final_paths = {item.path for item in metadata} | {attestation, completed[0]}
    if completed[0] in paths:
        if _read_checkpoint(completed[0], sha, token) != completed[1]:
            raise UploadConflict("Existing selected manga completion marker differs from verified candidate")
        if not (expected_paths | {attestation, completed[0]}).issubset(paths):
            raise UploadConflict("Published selected manga catalogue references missing media")
        matches = [item for item in catalogue if item.get("id") == entry["id"]]
        if matches != [entry]:
            raise UploadConflict("Published selected manga catalogue has changed since this source")
        return (
            {
                "status": "already-complete",
                "slug": title.slug,
                "expectedRevision": sha,
                "catalogueDigest": catalogue_sha,
                "expectedSourceDigest": _digest_records(media),
                "totalParts": len(parts),
                "remainingParts": 0,
                "completeDigest": _hash(completed[1]),
            },
            parts,
            completed,
            sha,
            paths,
            catalogue,
        )
    if any(item.get("id") == entry["id"] or item.get("title") == title.name for item in catalogue):
        raise UploadConflict(
            "This title already exists in the manga catalogue without the expected checkpoint"
        )
    if final_paths & paths:
        raise UploadConflict("Selected title publication metadata already exists without completion")
    incomplete = 0
    for index, part in enumerate(parts, start=1):
        checkpoint, digest_bytes = _marker(title, index, part)
        expected = {file.path for file in part}
        if checkpoint in paths:
            if not expected.issubset(paths):
                raise UploadConflict("Existing selected manga checkpoint references missing pages")
            if _read_checkpoint(checkpoint, sha, token) != digest_bytes:
                raise UploadConflict("Existing selected manga checkpoint differs from source")
        elif expected & paths:
            raise UploadConflict("Partial, uncheckpointed selected manga media already exists")
        else:
            incomplete += 1
    return (
        {
            "status": "append-only-ready",
            "slug": title.slug,
            "expectedRevision": sha,
            "catalogueDigest": catalogue_sha,
            "expectedSourceDigest": _digest_records(media),
            "totalParts": len(parts),
            "remainingParts": incomplete,
            "completeDigest": _hash(completed[1]),
        },
        parts,
        completed,
        sha,
        paths,
        catalogue,
    )


def selected_preview(slug: str, bundle: Path, registry: Path, token: str) -> dict[str, object]:
    if not token:
        raise ControllerError("Missing protected Hugging Face token")
    title = selected_title(slug)
    media, metadata, entry = candidate_files(title, bundle, registry)
    plan, _, _, _, _, _ = inspect_selected(_hf_api(token), token, title, media, metadata, entry)
    return plan


def selected_apply(
    slug: str, bundle: Path, registry: Path, plan_file: Path, token: str, *, approve: bool
) -> dict[str, object]:
    if not approve or not token:
        raise ControllerError("Protected Hugging Face upload must be explicitly approved")
    from huggingface_hub import CommitOperationAdd

    title = selected_title(slug)
    media, metadata, entry = candidate_files(title, bundle, registry)
    api = _hf_api(token)
    plan, parts, completion, head, paths, old_entries = inspect_selected(
        api, token, title, media, metadata, entry
    )
    approved = load_json(plan_file)
    if not isinstance(approved, dict) or approved != plan:
        raise UploadConflict("Private catalogue or verified manga candidate changed since preview")
    if plan["status"] == "already-complete":
        return {"status": "already-complete", "slug": slug, "revision": head, "partsWritten": 0}

    def commit(ops: list[Any], message: str) -> None:
        nonlocal head
        observed, _ = _repo_state(api, token)
        if observed != head:
            raise UploadConflict("Private dataset changed during selected manga upload")
        created = api.create_commit(
            repo_id=DATASET,
            repo_type="dataset",
            operations=ops,
            commit_message=message,
            parent_commit=head,
            token=token,
            num_threads=5,
        )
        result = getattr(created, "oid", None)
        if not isinstance(result, str) or len(result) < 20:
            result = api.dataset_info(DATASET, token=token).sha
        if not isinstance(result, str) or result == head:
            raise UploadConflict("Hugging Face commit did not advance source revision")
        head = result

    done = 0
    for index, part in enumerate(parts, start=1):
        marker, marker_bytes = _marker(title, index, part)
        if marker in paths:
            continue
        ops = [CommitOperationAdd(path_in_repo=record.path, path_or_fileobj=record.local) for record in part]
        ops.append(CommitOperationAdd(path_in_repo=marker, path_or_fileobj=marker_bytes))
        commit(ops, f"Ingest private verified {title.name} pages part {index}/{len(parts)}")
        paths.update(record.path for record in part)
        paths.add(marker)
        done += 1
        print(f"Uploaded private {slug} page batch {index}/{len(parts)}", flush=True)
    # Atomically reveal the title in the existing catalogue only after all pages are committed.
    if os.getenv("TAIYOU_INDEPENDENT_BACKUP_AND_STAGING_VERIFIED") != "yes":
        raise ControllerError(
            "Live selected uploads blocked until independent full-media backup and private staging test are verified"
        )
    updated = sorted([*old_entries, entry], key=lambda item: str(item["title"]).casefold())
    ops = [CommitOperationAdd(path_in_repo=record.path, path_or_fileobj=record.local) for record in metadata]
    ops.append(
        CommitOperationAdd(
            path_in_repo=f"ingest/{title.slug}-v1/attestation.json",
            path_or_fileobj=_permission(title),
        )
    )
    ops.append(CommitOperationAdd(path_in_repo=completion[0], path_or_fileobj=completion[1]))
    ops.append(CommitOperationAdd(path_in_repo=CANONICAL_CATALOGUE, path_or_fileobj=_json_bytes(canonical_library(updated))))
    commit(ops, f"Publish private {title.name} to existing manga catalogue after complete media")
    _, committed_paths = _repo_state(api, token)
    required = {file.path for file in [*media, *metadata]} | {
        CANONICAL_CATALOGUE,
        completion[0],
        f"ingest/{title.slug}-v1/attestation.json",
    }
    if not required.issubset(committed_paths):
        raise UploadConflict("Selected manga commit succeeded but published files are incomplete")
    verified_catalogue, _ = _old_catalogue(head, committed_paths, token)
    if verified_catalogue != updated:
        raise UploadConflict("Selected manga catalogue merge did not persist as planned")
    return {
        "status": "complete",
        "title": title.name,
        "slug": slug,
        "chapters": len(entry["chapters"]),
        "pages": len(media),
        "partsWritten": done,
        "revision": head,
        "private": True,
        "catalogueTitles": len(updated),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Guarded private selected manga HF uploader")
    parser.add_argument("--slug", choices=tuple(TITLES), required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--plan-file", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args(argv)
    try:
        token = os.getenv("HF_TOKEN", "")
        if args.apply:
            output = selected_apply(
                args.slug, args.bundle, args.registry, args.plan_file, token, approve=args.approve
            )
        else:
            output = selected_preview(args.slug, args.bundle, args.registry, token)
            with args.plan_file.open("x", encoding="utf-8") as file:
                json.dump(output, file, sort_keys=True)
                file.write("\n")
        print(json.dumps(output, sort_keys=True))
        return 0
    except (ControllerError, OSError) as exc:
        print(f"Selected manga HF upload refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
