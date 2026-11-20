"""Bounded, conservative manga publication metadata reconciliation.

Candidates are suggestions with provenance, never instructions to relabel series.
Manga, chapter, page, progress and collection identities are left untouched.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .domain import CHECKSUM_RE, ControllerError, safe_text, valid_id
from .hf_layout import canonical_library
from .images import check_bytes, read_limited

CANDIDATE_KIND = "manga-metadata-candidates"
FIELDS = ("aliases", "creators", "creatorRoles", "tags", "synopsis", "publicationStatus", "cover")
LIST_FIELDS = {"aliases": 24, "creators": 24, "tags": 32}
COVER_INPUT = re.compile(r"^covers/[A-Za-z0-9_-]{1,100}\.(png|jpg|jpeg|webp|avif)$")
COVER_ASSET = re.compile(r"^covers/(mng_[A-Za-z0-9_-]{8,64})\.(png|jpg|jpeg|webp|avif)$")
MAX_CANDIDATES = 10000
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_COVER_BYTES = 5 * 1024 * 1024
STATUS_VALUES = {"unknown", "ongoing", "completed", "hiatus"}


def encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _text_list(values: object, maximum: int) -> list[str]:
    if not isinstance(values, list) or len(values) > maximum:
        raise ControllerError("Metadata list exceeds limit or is malformed")
    result = [safe_text(value, 120) for value in values]
    if len({value.casefold() for value in result}) != len(result):
        raise ControllerError("Duplicate publication metadata values")
    return result


def _source(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {
        "provider", "sourceId", "sourceUrl", "retrievedAt"
    }:
        raise ControllerError("Source provenance is mandatory for each metadata candidate")
    provider = safe_text(value["provider"], 60)
    if re.fullmatch(r"[A-Za-z0-9_-]{2,60}", provider) is None:
        raise ControllerError("Unsafe metadata source provider")
    source_id = safe_text(value["sourceId"], 180)
    source_url = safe_text(value["sourceUrl"], 500)
    url = urlsplit(source_url)
    try:
        safe_host = bool(
            url.scheme == "https"
            and url.hostname
            and "." in url.hostname
            and not url.username
            and not url.password
            and not url.query
            and not url.fragment
            and url.port in (None, 443)
        )
    except ValueError as exc:
        raise ControllerError("Malformed HTTPS source provenance") from exc
    if not safe_host:
        raise ControllerError("Provenance must use a plain HTTPS reference, never a signed media URL")
    timestamp = safe_text(value["retrievedAt"], 40)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", timestamp):
        raise ControllerError("Metadata provenance needs a UTC retrieval timestamp")
    return {
        "provider": provider,
        "sourceId": source_id,
        "sourceUrl": source_url,
        "retrievedAt": timestamp,
    }


def validate_candidates(raw: object) -> list[dict[str, Any]]:
    if (
        not isinstance(raw, dict)
        or set(raw) != {"schemaVersion", "mediaKind", "candidates"}
        or raw["schemaVersion"] != 1
        or raw["mediaKind"] != CANDIDATE_KIND
        or not isinstance(raw["candidates"], list)
        or len(raw["candidates"]) > MAX_CANDIDATES
    ):
        raise ControllerError("Unsupported metadata candidates envelope")
    checked: list[dict[str, Any]] = []
    for item in raw["candidates"]:
        if not isinstance(item, dict) or set(item) - {"mangaId", "title", "source", "metadata"}:
            raise ControllerError("Unexpected metadata candidate fields")
        if "mangaId" not in item and "title" not in item:
            raise ControllerError("Candidate requires a manga ID or a title for review")
        record: dict[str, Any] = {"source": _source(item.get("source"))}
        if "mangaId" in item:
            record["mangaId"] = valid_id(item["mangaId"], "mng")
        if "title" in item:
            record["title"] = safe_text(item["title"], 180)
        fields = item.get("metadata")
        if not isinstance(fields, dict) or not fields or set(fields) - set(FIELDS):
            raise ControllerError("Missing or unsupported publication metadata")
        metadata: dict[str, Any] = {}
        for field, maximum in LIST_FIELDS.items():
            if field in fields:
                metadata[field] = _text_list(fields[field], maximum)
        if "synopsis" in fields:
            metadata["synopsis"] = safe_text(fields["synopsis"], 2000)
        if "publicationStatus" in fields:
            if fields["publicationStatus"] not in STATUS_VALUES:
                raise ControllerError("Unsupported manga publication status")
            metadata["publicationStatus"] = fields["publicationStatus"]
        if "creatorRoles" in fields:
            roles = fields["creatorRoles"]
            if not isinstance(roles, list) or len(roles) > 24:
                raise ControllerError("Creator roles exceed limits")
            seen: set[tuple[str, str]] = set()
            resolved = []
            for role in roles:
                if not isinstance(role, dict) or set(role) != {"name", "role"}:
                    raise ControllerError("Malformed author or artist role")
                name = safe_text(role["name"], 120)
                kind = role["role"]
                if kind not in ("author", "artist"):
                    raise ControllerError("Unsupported creator role")
                key = (name.casefold(), kind)
                if key in seen:
                    raise ControllerError("Duplicate creator role")
                seen.add(key)
                resolved.append({"name": name, "role": kind})
            metadata["creatorRoles"] = resolved
            if "creators" not in metadata:
                metadata["creators"] = list(dict.fromkeys(row["name"] for row in resolved))
        if "cover" in fields:
            cover = fields["cover"]
            if not isinstance(cover, dict) or set(cover) != {
                "file", "rightsEvidence", "attribution"
            }:
                raise ControllerError("Cover requires file, permission evidence and attribution")
            relative = safe_text(cover["file"], 140)
            if not COVER_INPUT.fullmatch(relative):
                raise ControllerError("Unsafe relative cover input path")
            metadata["cover"] = {
                "file": relative,
                "rightsEvidence": safe_text(cover["rightsEvidence"], 400),
                "attribution": safe_text(cover["attribution"], 240),
            }
        record["metadata"] = metadata
        checked.append(record)
    return checked


def _cover_file(root: Path, candidate: dict[str, Any], manga_id: str) -> tuple[dict[str, Any], Path]:
    cover = candidate["metadata"]["cover"]
    relative = cover["file"]
    local = root / relative
    if (
        root.is_symlink()
        or local.parent.is_symlink()
        or local.is_symlink()
        or not local.resolve().is_relative_to(root.resolve())
        or not local.is_file()
    ):
        raise ControllerError("Cover candidate file is missing, a symlink or unsafe")
    data = read_limited(local, MAX_COVER_BYTES)
    checked = check_bytes(data, relative)
    if checked.byte_size > MAX_COVER_BYTES:
        raise ControllerError("Cover artwork exceeds private cover budget")
    return {
        "assetPath": f"covers/{manga_id}{checked.extension}",
        "mimeType": checked.mime,
        "width": checked.width,
        "height": checked.height,
        "byteSize": checked.byte_size,
        "sha256": checked.checksum,
    }, local


def cover_asset_path(cover: object, manga_id: str) -> str:
    if not isinstance(cover, dict) or set(cover) != {
        "assetPath", "mimeType", "width", "height", "byteSize", "sha256"
    }:
        raise ControllerError("Malformed canonical manga cover descriptor")
    asset = cover.get("assetPath")
    if not isinstance(asset, str) or not COVER_ASSET.fullmatch(asset):
        raise ControllerError("Unsafe canonical manga cover path")
    if COVER_ASSET.fullmatch(asset).group(1) != manga_id:
        raise ControllerError("Cover does not belong to its immutable manga ID")
    suffix = "." + asset.rsplit(".", 1)[-1]
    from .domain import IMAGE_EXTENSIONS

    if cover["mimeType"] != IMAGE_EXTENSIONS[suffix]:
        raise ControllerError("Cover file type does not match descriptor")
    if (
        type(cover["width"]) is not int
        or type(cover["height"]) is not int
        or not 1 <= cover["width"] <= 16000
        or not 1 <= cover["height"] <= 16000
        or cover["width"] * cover["height"] > 70_000_000
        or type(cover["byteSize"]) is not int
        or not 1 <= cover["byteSize"] <= MAX_COVER_BYTES
        or not isinstance(cover["sha256"], str)
        or not CHECKSUM_RE.fullmatch(cover["sha256"])
    ):
        raise ControllerError("Invalid canonical manga cover size or SHA-256")
    return "data/" + asset


def completeness(entries: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for item in entries:
        missing = [
            name for name in ("cover", "creators", "synopsis", "tags")
            if not item.get(name)
        ]
        if item.get("publicationStatus") == "unknown":
            missing.append("publicationStatus")
        rows.append({"id": item["id"], "title": item["title"], "missing": missing})
    return {
        "series": len(entries),
        "complete": sum(not row["missing"] for row in rows),
        "missingCount": {
            field: sum(field in row["missing"] for row in rows)
            for field in ("cover", "creators", "synopsis", "tags", "publicationStatus")
        },
        "entries": rows,
    }


def reconcile(
    entries: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    cover_root: Path,
    existing_files: set[str],
) -> tuple[list[dict[str, Any]], dict[str, Path], list[dict[str, str]], list[str]]:
    """Fill only genuinely empty fields. Anything ambiguous or populated is protected."""
    result = [dict(entry) for entry in entries]
    by_id = {row["id"]: row for row in result}
    claimed: set[str] = set()
    uploads: dict[str, Path] = {}
    changes: list[dict[str, str]] = []
    conflicts: list[str] = []
    for candidate in candidates:
        series_id = candidate.get("mangaId")
        if series_id is None:
            title = candidate["title"].casefold()
            matches = [
                row for row in result
                if title in {row["title"].casefold(), *(s.casefold() for s in row["aliases"])}
            ]
            label = candidate["title"]
            conflicts.append(
                f"{label}: title-only match requires manual ID review ({len(matches)} possible)"
            )
            continue
        row = by_id.get(series_id)
        if row is None:
            conflicts.append(f"{series_id}: candidate series ID does not exist")
            continue
        if series_id in claimed:
            conflicts.append(f"{series_id}: multiple candidates require manual reconciliation")
            continue
        claimed.add(series_id)
        if "title" in candidate:
            accepted = {row["title"].casefold(), *(s.casefold() for s in row["aliases"])}
            if candidate["title"].casefold() not in accepted:
                conflicts.append(f"{series_id}: mismatched publication title")
                continue
        source = candidate["source"]
        fields = candidate["metadata"]
        origins = dict(row.get("metadataSources", {}))
        if not isinstance(origins, dict):
            conflicts.append(f"{series_id}: existing provenance is invalid")
            continue
        for key in FIELDS:
            if key not in fields:
                continue
            incoming = fields[key]
            if key in LIST_FIELDS or key == "creatorRoles":
                blank = not row.get(key)
            elif key == "publicationStatus":
                blank = row.get(key) == "unknown"
            else:
                blank = not row.get(key)
            if key == "cover":
                cover_info, local = _cover_file(cover_root, candidate, series_id)
                incoming = cover_info
                remote_path = cover_asset_path(cover_info, series_id)
                if remote_path in existing_files and row.get("cover") != incoming:
                    conflicts.append(f"{series_id}: private cover path already occupied")
                    continue
            if not incoming or (key == "publicationStatus" and incoming == "unknown"):
                continue
            if blank:
                row[key] = incoming
                origins[key] = source
                changes.append({"mangaId": series_id, "field": key})
                if key == "cover":
                    uploads[remote_path] = local
            elif row.get(key) != incoming:
                conflicts.append(f"{series_id}: existing {key} is protected; manual review required")
        if origins:
            row["metadataSources"] = origins
    canonical_library(result)
    return result, uploads, changes, conflicts


def load_candidates(path: Path) -> tuple[list[dict[str, Any]], str]:
    if path.is_symlink() or not path.is_file():
        raise ControllerError("Metadata candidate document is missing or unsafe")
    contents = read_limited(path, MAX_INPUT_BYTES)
    try:
        candidate = json.loads(contents)
    except (UnicodeError, ValueError) as exc:
        raise ControllerError("Malformed metadata candidate JSON") from exc
    return validate_candidates(candidate), hashlib.sha256(contents).hexdigest()
