"""Stage an existing verified manga bundle privately for an agent-triggered GitHub upload.

No original manga assets are ever sent to GitHub. This stages an immutable,
SHA-256-pinned package inside the *already private* owner Hugging Face dataset.
The separate protected GitHub workflow reads it later using HF_TOKEN.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any

from taiyou_manga.builder import load_json, verify_bundle
from taiyou_manga.domain import ControllerError
from taiyou_manga.hf_upload import DATASET
from taiyou_manga.metadata import load_candidates

ROOT = "ingest/agent-queue"
TICKET = re.compile(r"^[a-f0-9]{32}$")
MAX_FILES = 5500
MAX_TOTAL_BYTES = 5_000_000_000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_paths(bundle: Path, candidates_path: Path) -> list[tuple[Path, str]]:
    """Include all validated bundle files and *only referenced* metadata cover files."""
    inventory = verify_bundle(bundle)
    if inventory["series"] != 1:
        raise ControllerError("Staging supports one complete manga bundle per ticket")
    if not (bundle / "rights.json").is_file():
        raise ControllerError("Private staging requires the existing source rights record")
    entries = load_json(bundle / "catalogue.json")
    candidates, _ = load_candidates(candidates_path)
    if len(entries) != 1 or not 1 <= len(candidates) <= 1:
        raise ControllerError("Stage exactly one manga and one source metadata candidate")
    item = entries[0]
    if candidates[0].get("mangaId") != item["id"]:
        raise ControllerError("Metadata candidate must target the verified immutable manga ID")
    if candidates[0].get("title") not in (None, item["title"]):
        raise ControllerError("Source metadata title differs from bundle's manga title")

    include: list[tuple[Path, str]] = []
    for file in sorted(bundle.rglob("*")):
        if file.is_symlink():
            raise ControllerError("Symlink inside private bundle")
        if file.is_dir():
            continue
        if not file.is_file() or not file.resolve().is_relative_to(bundle.resolve()):
            raise ControllerError("Unsafe private bundle file")
        include.append((file, "bundle/" + file.relative_to(bundle).as_posix()))

    include.append((candidates_path, "metadata/candidates.json"))
    field = candidates[0]["metadata"].get("cover")
    if field:
        relative = field["file"]
        from taiyou_manga.metadata import COVER_INPUT

        if not COVER_INPUT.fullmatch(relative):
            raise ControllerError("Unsafe candidate cover path")
        cover = candidates_path.parent / relative
        if cover.is_symlink() or not cover.is_file() or not cover.resolve().is_relative_to(
            candidates_path.parent.resolve()
        ):
            raise ControllerError("Missing or unsafe private source cover")
        include.append((cover, "metadata/" + relative))

    if len(include) > MAX_FILES:
        raise ControllerError("Too many media files for a single staging ticket")
    total = 0
    seen: set[str] = set()
    for file, arcname in include:
        if file.is_symlink() or not file.is_file():
            raise ControllerError("Unsafe staged source")
        if arcname.casefold() in seen:
            raise ControllerError("Duplicate staged filename")
        seen.add(arcname.casefold())
        total += file.stat().st_size
        if total > MAX_TOTAL_BYTES:
            raise ControllerError("Staging exceeds the 5 GB maximum")
    return include


def write_package(package: Path, source: list[tuple[Path, str]]) -> None:
    if package.exists() or package.is_symlink():
        raise ControllerError("Refusing to overwrite an existing private staging package")
    with zipfile.ZipFile(package, "x", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for file, arcname in source:
            archive.write(file, arcname)


def stage(work: Path, token: str, *, ticket: str | None = None) -> dict[str, Any]:
    from huggingface_hub import CommitOperationAdd, HfApi

    if not token:
        raise ControllerError("A private Hugging Face write token is required to stage originals")
    if not work.is_dir() or work.is_symlink():
        raise ControllerError("The private local import work directory does not exist")
    bundle = work / "bundle"
    candidates_path = work / "metadata" / "candidates.json"
    if not candidates_path.is_file() or candidates_path.is_symlink():
        raise ControllerError(
            "Missing verified local metadata; run upload_acquainted_windows.py --dry-run first"
        )
    sources = source_paths(bundle, candidates_path)
    job_id = ticket or uuid.uuid4().hex
    if not TICKET.fullmatch(job_id):
        raise ControllerError("Staging ticket must consist of 32 lowercase hexadecimal characters")
    api = HfApi(token=token)
    info = api.dataset_info(DATASET, token=token)
    if info.private is not True or not isinstance(info.sha, str):
        raise ControllerError("Refusing to stage media unless the exact dataset is private")
    prefix = f"{ROOT}/{job_id}"
    existing = set(api.list_repo_files(DATASET, repo_type="dataset", revision=info.sha, token=token))
    if f"{prefix}/package.zip" in existing or f"{prefix}/manifest.json" in existing:
        raise ControllerError("Ticket already staged; never replace an existing private source package")
    entry = load_json(bundle / "catalogue.json")[0]
    inventory = verify_bundle(bundle)
    with tempfile.TemporaryDirectory(prefix="taiyou-stage-") as tmp:
        package = Path(tmp) / "package.zip"
        write_package(package, sources)
        archive_sha = sha256_file(package)
        manifest = {
            "schemaVersion": 1,
            "kind": "private-manga-github-stage",
            "ticket": job_id,
            "packageSha256": archive_sha,
            "packageBytes": package.stat().st_size,
            "mangaId": entry["id"],
            "chapters": inventory["chapters"],
            "pages": inventory["pages"],
            "metadataSha256": sha256_file(candidates_path),
        }
        result = api.create_commit(
            repo_id=DATASET,
            repo_type="dataset",
            revision="main",
            parent_commit=info.sha,
            token=token,
            operations=[
                CommitOperationAdd(path_in_repo=f"{prefix}/package.zip", path_or_fileobj=str(package)),
                CommitOperationAdd(
                    path_in_repo=f"{prefix}/manifest.json",
                    path_or_fileobj=(json.dumps(manifest, sort_keys=True) + "\n").encode("utf-8"),
                ),
            ],
            commit_message=f"Stage immutable private manga package for GitHub agent ticket {job_id}",
            num_threads=2,
        )
    revision = getattr(result, "oid", None) or api.dataset_info(DATASET, token=token).sha
    return {
        "status": "private-stage-complete",
        "ticket": job_id,
        "revision": revision,
        "chapters": inventory["chapters"],
        "pages": inventory["pages"],
        "private": True,
        "canonicalCatalogueChanged": False,
        "nextCommand": f"/manga-import {job_id} preview",
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Stage a verified manga privately for GitHub agent upload")
    p.add_argument(
        "--work-dir",
        required=True,
        type=Path,
        help="Existing .acquainted-private-import directory containing bundle/ and metadata/",
    )
    p.add_argument("--ticket", help="Optional 32-char stable staging ticket; normally autogenerated")
    args = p.parse_args(argv)
    token = os.getenv("HF_TOKEN", "").strip() or getpass.getpass("Private Hugging Face token: ").strip()
    try:
        result = stage(args.work_dir.resolve(), token, ticket=args.ticket)
    except (ControllerError, OSError, ValueError) as exc:
        print(f"Private staging failed safely: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
