"""The Manga Library's canonical private HF contract and read-only legacy migration.

This module does not write to Hugging Face. It creates a deterministic plan
from an immutable dataset revision, preserves the existing legacy files, and
requires exact content/ID equivalence for a later independently tested migration.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .domain import ControllerError, valid_id, validate_manifest_json

CANONICAL_CATALOGUE = "data/library.json"
LEGACY_CATALOGUE = "catalogue.json"
MEDIA_ROOT = "data/manga"
MANIFEST_ROOT = "data/manifests"
COVER_ROOT = "data/covers"
MANIFEST_RE = re.compile(r"^manifests/(ch_[A-Za-z0-9_-]{8,64})\.json$")
MEDIA_RE = re.compile(
    r"^assets/manga/(mng_[A-Za-z0-9_-]{8,64})/(ch_[A-Za-z0-9_-]{8,64})/"
    r"(pg_[A-Za-z0-9_-]{8,64})\.(?:png|jpg|jpeg|webp|avif)$"
)
MAX_SERIES = 10000
MAX_CHAPTERS_PER_SERIES = 2000
MAX_LIBRARY_BYTES = 4 * 1024 * 1024


def _json_bytes(doc: object) -> bytes:
    return (json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def validate_entries(raw: object) -> list[dict[str, Any]]:
    """Reject malformed IDs and catalogue fields, never generate new IDs."""
    if not isinstance(raw, list) or len(raw) > MAX_SERIES:
        raise ControllerError("Manga catalogue must be a bounded array")
    entries: list[dict[str, Any]] = []
    seen_series: set[str] = set()
    seen_chapters: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict) or entry.get("kind") != "manga":
            raise ControllerError("Invalid manga catalogue record")
        raw_sid = entry.get("id")
        if not isinstance(raw_sid, str):
            raise ControllerError("Missing or unsafe manga series identifier")
        sid = valid_id(raw_sid, "mng")
        title = entry.get("title")
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 180:
            raise ControllerError("Missing or oversized manga title")
        if sid in seen_series:
            raise ControllerError("Duplicate manga series identifier")
        seen_series.add(sid)
        if entry.get("direction") not in ("vertical", "rtl", "ltr"):
            raise ControllerError("Invalid manga reading direction")
        if entry.get("publicationStatus") not in ("unknown", "ongoing", "completed", "hiatus"):
            raise ControllerError("Invalid publication status")
        for key, maximum in (("aliases", 24), ("creators", 24), ("tags", 32)):
            values = entry.get(key)
            if not isinstance(values, list) or len(values) > maximum:
                raise ControllerError("Missing or excessive manga metadata values")
            if not all(isinstance(x, str) and 0 < len(x.strip()) <= 120 for x in values):
                raise ControllerError("Invalid manga metadata text")
        synopsis = entry.get("synopsis")
        if synopsis is not None:
            from .domain import safe_text

            safe_text(synopsis, 2000)
        roles = entry.get("creatorRoles")
        if roles is not None:
            if not isinstance(roles, list) or len(roles) > 24:
                raise ControllerError("Invalid manga author and artist roles")
            seen_roles: set[tuple[str, str]] = set()
            for role in roles:
                if not isinstance(role, dict) or set(role) != {"name", "role"}:
                    raise ControllerError("Invalid creator role object")
                from .domain import safe_text

                role_name = safe_text(role["name"], 120)
                if role["role"] not in ("author", "artist"):
                    raise ControllerError("Unsupported creator role")
                key = (role_name.casefold(), role["role"])
                if key in seen_roles:
                    raise ControllerError("Duplicate creator role")
                seen_roles.add(key)
        cover = entry.get("cover")
        if cover is not None:
            from .metadata import cover_asset_path

            cover_asset_path(cover, sid)
        origins = entry.get("metadataSources")
        if origins is not None:
            from .metadata import FIELDS, _source

            if not isinstance(origins, dict) or set(origins) - set(FIELDS):
                raise ControllerError("Unexpected or malformed metadata provenance")
            for field, source in origins.items():
                if field not in entry:
                    raise ControllerError("Source provenance refers to missing manga metadata")
                _source(source)
        chapters = entry.get("chapters")
        if not isinstance(chapters, list) or len(chapters) > MAX_CHAPTERS_PER_SERIES:
            raise ControllerError("Manga chapters must be a bounded array")
        sequences: set[int] = set()
        for chapter in chapters:
            if not isinstance(chapter, dict):
                raise ControllerError("Invalid manga chapter")
            raw_cid = chapter.get("id")
            if not isinstance(raw_cid, str):
                raise ControllerError("Missing or unsafe manga chapter identifier")
            cid = valid_id(raw_cid, "ch")
            if cid in seen_chapters:
                raise ControllerError("Duplicate cross-series manga chapter ID")
            seen_chapters.add(cid)
            label = chapter.get("label")
            if not isinstance(label, str) or not 1 <= len(label.strip()) <= 120:
                raise ControllerError("Invalid chapter label")
            seq = chapter.get("sequence")
            if type(seq) is not int or not 0 <= seq <= 1_000_000 or seq in sequences:
                raise ControllerError("Manga chapter sequence duplicated or invalid")
            sequences.add(seq)
            count = chapter.get("pageCount")
            if type(count) is not int or not 1 <= count <= 1000:
                raise ControllerError("Manga chapter page count missing or unsafe")
        entries.append(entry)
    if len(_json_bytes({"schemaVersion": 1, "mediaKind": "manga", "entries": entries})) > MAX_LIBRARY_BYTES:
        raise ControllerError("Canonical manga library exceeds reader's 4 MiB limit")
    return entries


def validate_library(raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, dict) or set(raw) != {"schemaVersion", "mediaKind", "entries"}:
        raise ControllerError("Canonical HF manga catalogue must be a complete JSON envelope")
    if raw["schemaVersion"] != 1 or raw["mediaKind"] != "manga":
        raise ControllerError("Unsupported canonical manga library version or media type")
    return validate_entries(raw["entries"])


def canonical_library(entries: object) -> dict[str, Any]:
    return {"schemaVersion": 1, "mediaKind": "manga", "entries": validate_entries(entries)}


def _migration_maps(
    entries: list[dict[str, Any]],
    source_files: set[str],
    manifests: dict[str, Any],
) -> dict[str, str]:
    if not source_files or CANONICAL_CATALOGUE in source_files:
        raise ControllerError("Migration requires a legacy dataset with no canonical library")
    if any(name.startswith("data/") for name in source_files):
        raise ControllerError("Existing canonical data/ tree requires separate recovery")
    if LEGACY_CATALOGUE not in source_files:
        raise ControllerError("The original legacy catalogue is missing")
    map_paths: dict[str, str] = {}
    seen: set[str] = set()
    for entry in entries:
        series_id = entry["id"]
        for chapter in entry["chapters"]:
            chapter_id = chapter["id"]
            legacy_manifest = f"manifests/{chapter_id}.json"
            if legacy_manifest not in source_files or legacy_manifest not in manifests:
                raise ControllerError("Missing legacy chapter manifest")
            doc = validate_manifest_json(manifests[legacy_manifest])
            if doc.chapterId != chapter_id or len(doc.pages) != chapter["pageCount"]:
                raise ControllerError("Legacy chapter metadata or page count mismatch")
            destination = f"data/{legacy_manifest}"
            if destination in seen:
                raise ControllerError("Duplicate target chapter manifest")
            seen.add(destination)
            map_paths[legacy_manifest] = destination
            for page in doc.pages:
                if not page.assetPath.startswith(f"manga/{series_id}/{chapter_id}/"):
                    raise ControllerError("Legacy page does not belong to expected manga or chapter")
                legacy_page = "assets/" + page.assetPath
                destination_page = "data/" + page.assetPath
                if MEDIA_RE.fullmatch(legacy_page) is None or legacy_page not in source_files:
                    raise ControllerError("Missing or invalid legacy image path")
                if destination_page in seen:
                    raise ControllerError("Conflicting private manga page target")
                seen.add(destination_page)
                map_paths[legacy_page] = destination_page
    if not all(path in map_paths for path in source_files if path.startswith("assets/manga/")):
        raise ControllerError("Unreferenced legacy media files require manual recovery")
    if not all(path in map_paths for path in source_files if path.startswith("manifests/")):
        raise ControllerError("Unreferenced legacy chapter manifests require manual recovery")
    if set(map_paths.values()) & source_files:
        raise ControllerError("Migration would overwrite existing private files")
    return map_paths


def legacy_migration_preview(
    raw_entries: object, source_files: set[str], manifests: dict[str, Any], sha: str
) -> dict[str, object]:
    if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise ControllerError("Migration must be pinned to a full Hugging Face dataset commit")
    entries = validate_entries(raw_entries)
    copy_paths = _migration_maps(entries, source_files, manifests)
    document = canonical_library(entries)
    count_chapters = sum(len(entry["chapters"]) for entry in entries)
    media_count = sum(path.startswith("assets/manga/") for path in copy_paths)
    if len(copy_paths) != count_chapters + media_count:
        raise ControllerError("Migration mapping contains unsupported file classes")
    digest = hashlib.sha256()
    for source, destination in sorted(copy_paths.items()):
        digest.update(source.encode() + b"\0" + destination.encode() + b"\n")
    return {
        "mode": "read-only-no-migration",
        "expectedRevision": sha,
        "canonicalPath": CANONICAL_CATALOGUE,
        "legacyPath": LEGACY_CATALOGUE,
        "schemaVersion": 1,
        "mediaKind": "manga",
        "series": len(entries),
        "chapters": count_chapters,
        "pages": media_count,
        "filesToCopyWithoutDeletingLegacy": len(copy_paths),
        "copyMapDigest": digest.hexdigest(),
        "canonicalCatalogueDigest": hashlib.sha256(_json_bytes(document)).hexdigest(),
        "remoteWritesEnabled": False,
        "requiresFullBackup": True,
        "requiresDisposablePrivateDatasetTest": True,
    }


def read_legacy_preview(repo_id: str, token: str) -> dict[str, object]:
    """Read-only private remote inspection; never fetch or expose original image bytes."""
    if repo_id != "AdityaSreevatsaK/Taiyous-Manga" or not token:
        raise ControllerError("Explicit approved private dataset and token required")
    from huggingface_hub import HfApi, hf_hub_download

    api = HfApi(token=token)
    info = api.dataset_info(repo_id, token=token)
    if info.private is not True or not re.fullmatch(r"[a-f0-9]{40}", str(info.sha)):
        raise ControllerError("Dataset is not verified private or revision is invalid")
    revision = str(info.sha)
    files = set(api.list_repo_files(repo_id, repo_type="dataset", revision=revision, token=token))
    if LEGACY_CATALOGUE not in files:
        raise ControllerError("Expected root legacy manga catalogue missing")
    raw_path = hf_hub_download(
        repo_id=repo_id,
        repo_type="dataset",
        revision=revision,
        filename=LEGACY_CATALOGUE,
        token=token,
    )
    raw_bytes = Path(raw_path).read_bytes()
    if len(raw_bytes) > MAX_LIBRARY_BYTES:
        raise ControllerError("Legacy manga catalogue exceeds 4 MiB")
    entries = json.loads(raw_bytes)
    entries = validate_entries(entries)
    manifests: dict[str, Any] = {}
    for entry in entries:
        for chapter in entry["chapters"]:
            name = f"manifests/{chapter['id']}.json"
            if name not in files:
                raise ControllerError("Legacy HF chapter manifest is missing")
            path = hf_hub_download(
                repo_id=repo_id,
                repo_type="dataset",
                revision=revision,
                filename=name,
                token=token,
            )
            bytes_manifest = Path(path).read_bytes()
            if len(bytes_manifest) > 1_000_000:
                raise ControllerError("Legacy chapter manifest exceeds 1 MiB")
            manifests[name] = json.loads(bytes_manifest)
    return legacy_migration_preview(entries, files, manifests, revision)


def main() -> int:
    import argparse
    import os
    import sys

    parser = argparse.ArgumentParser(description="Private read-only HF legacy migration preview")
    parser.add_argument("--repo-id", default="AdityaSreevatsaK/Taiyous-Manga")
    args = parser.parse_args()
    try:
        result = read_legacy_preview(args.repo_id, os.environ.get("HF_TOKEN", ""))
    except (ControllerError, ValueError, OSError) as exc:
        print(f"Private manga migration preview blocked: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
