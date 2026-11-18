"""Build a private local candidate bundle with immutable identities."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from .domain import Chapter, ChapterManifest, ControllerError, Page, safe_text, valid_id, validate_manifest_json
from .images import Limits, check_bytes, read_limited
from .sources import ChapterSource, discover, natural_key


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ControllerError(f"Cannot read valid JSON: {path.name}") from exc


def _registry(state_file: Path) -> dict[str, str]:
    if not state_file.exists():
        return {}
    data = load_json(state_file)
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        raise ControllerError("Invalid local identity registry")
    for key, value in data.items():
        valid_id(value, "ch" if key.startswith("chapter:") else "mng")
    return data


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(12)}"


def _id_for(registry: dict[str, str], key: str, prefix: str) -> str:
    if key not in registry:
        registry[key] = _new_id(prefix)
    return valid_id(registry[key], prefix)


def _page_id(chapter_id: str, checksum: str) -> str:
    return "pg_" + hashlib.sha256((chapter_id + ":" + checksum).encode("ascii")).hexdigest()[:24]


def _number_warnings(pages: ChapterSource) -> list[str]:
    stems = [Path(page.name).stem for page in pages.pages]
    nums = []
    for stem in stems:
        match = re.search(r"(\d+)$", stem)
        if not match:
            return []  # numbering not configured for this input
        nums.append(int(match.group(1)))
    unique = set(nums)
    if len(unique) != len(nums):
        return [f"{pages.key}: repeated page numbers"]
    if sorted(unique) != list(range(min(unique), max(unique) + 1)):
        return [f"{pages.key}: missing page numbers"]
    return []


def parse_rights(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    data = load_json(path)
    if not isinstance(data, dict) or set(data) != {"schemaVersion", "sourceType", "title", "permissionEvidence", "attribution", "recordedAt"}:
        raise ControllerError("Rights evidence does not match v1 SourceRights")
    if data["schemaVersion"] != 1 or data["sourceType"] not in ("original", "owned", "licensed"):
        raise ControllerError("Unsupported rights declaration")
    for name, maximum in (("title", 180), ("permissionEvidence", 400), ("attribution", 400)):
        safe_text(data[name], maximum)
    if not isinstance(data["recordedAt"], str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", data["recordedAt"]):
        raise ControllerError("Rights timestamp must be UTC ISO-8601")
    return data


def _build(source: Path, output: Path, state_file: Path, title: str | None, direction: str,
           rights: dict[str, Any] | None, limits: Limits) -> dict[str, Any]:
    if direction not in ("rtl", "ltr", "vertical"):
        raise ControllerError("Reading direction must be rtl, ltr or vertical")
    if title:
        safe_text(title, 180)
    if output.exists():
        raise ControllerError("Output already exists; never overwrite an existing bundle")
    if output.resolve().is_relative_to(source.resolve()) and source.is_dir():
        raise ControllerError("Output must be outside the source folder")
    if state_file.resolve().is_relative_to(source.resolve()) and source.is_dir():
        raise ControllerError("Identity registry must be outside the source folder")
    registry = _registry(state_file)
    sources = list(discover(source, limits))
    if not sources:
        raise ControllerError("No chapters")
    keys = [s.key.casefold() for s in sources]
    if len(keys) != len(set(keys)):
        raise ControllerError("Duplicate chapter locations")
    series: dict[str, list[tuple[Chapter, ChapterManifest]]] = defaultdict(list)
    titles: dict[str, str] = {}
    seen_fingerprints: dict[tuple[str, str], str] = {}
    warnings: list[str] = []
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".manga-stage-", dir=output.parent))
    try:
        for item in sources:
            series_id = _id_for(registry, "series:" + item.series_key, "mng")
            chapter_id = _id_for(registry, "chapter:" + item.key, "ch")
            titles[series_id] = safe_text(title if title and len(sources) == 1 else item.series_title, 180)
            warnings.extend(_number_warnings(item))
            pages: list[Page] = []
            checksums: set[str] = set()
            for raw in sorted(item.pages, key=lambda page: natural_key(page.name)):
                checked = check_bytes(raw.data, raw.name, limits)
                if checked.checksum in checksums:
                    raise ControllerError(f"Exact duplicate image in chapter: {item.key}")
                checksums.add(checked.checksum)
                page_id = _page_id(chapter_id, checked.checksum)
                asset_path = f"manga/{series_id}/{chapter_id}/{page_id}{checked.extension}"
                page = Page(page_id, asset_path, checked.mime, checked.width, checked.height,
                            checked.byte_size, checked.checksum)
                pages.append(page)
                destination = stage / "assets" / asset_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(raw.data)
                fingerprint = (series_id, checked.checksum)
                if fingerprint in seen_fingerprints:
                    warnings.append(f"Duplicate page contents across chapters: {item.key}")
                else:
                    seen_fingerprints[fingerprint] = item.key
            manifest = ChapterManifest(chapter_id, tuple(pages))
            manifest.validate()
            write_json(stage / "manifests" / f"{chapter_id}.json", manifest.as_json())
            series[series_id].append((Chapter(chapter_id, safe_text(item.chapter_label, 120), 0,
                                                   safe_text(item.volume, 60) if item.volume else None,
                                                   len(pages)), manifest))
        catalogue = []
        for sid, chapters in sorted(series.items(), key=lambda pair: titles[pair[0]].casefold()):
            ordered = sorted(chapters, key=lambda pair: natural_key((pair[0].volume or "") + "/" + pair[0].label))
            catalogue.append({"kind": "manga", "id": sid, "title": titles[sid], "aliases": [], "creators": [],
                              "tags": [], "publicationStatus": "unknown", "direction": direction,
                              "chapters": [Chapter(c.id, c.label, i, c.volume, c.pageCount).as_json()
                                           for i, (c, _) in enumerate(ordered)]})
        inventory: dict[str, Any] = {"controllerCandidateVersion": 1, "mediaKind": "manga",
                                     "state": "local-draft-not-approved-persisted-schema",
                                     "series": len(catalogue), "chapters": len(sources),
                                     "pages": sum(len(m.pages) for chapters in series.values() for _, m in chapters),
                                     "warnings": sorted(set(warnings)), "rightsVerified": rights is not None}
        write_json(stage / "catalogue.json", catalogue)
        write_json(stage / "inventory.json", inventory)
        if rights:
            write_json(stage / "rights.json", rights)
        stage.rename(output)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        # Never replace an existing registry without an atomic file switch.
        temp_registry = state_file.with_suffix(state_file.suffix + ".tmp")
        write_json(temp_registry, registry)
        temp_registry.replace(state_file)
        return inventory
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def build(source: Path, output: Path, state_file: Path, title: str | None = None,
          direction: str = "rtl", rights_path: Path | None = None,
          limits: Limits = Limits()) -> dict[str, Any]:
    return _build(source, output, state_file, title, direction, parse_rights(rights_path), limits)


def verify_bundle(bundle: Path, limits: Limits = Limits()) -> dict[str, Any]:
    if bundle.is_symlink() or not bundle.is_dir():
        raise ControllerError("Bundle directory missing or unsafe")
    inventory = load_json(bundle / "inventory.json")
    catalogue = load_json(bundle / "catalogue.json")
    if not isinstance(inventory, dict) or inventory.get("controllerCandidateVersion") != 1:
        raise ControllerError("Unknown candidate inventory version")
    if not isinstance(catalogue, list):
        raise ControllerError("Invalid catalogue")
    series_ids = set()
    chapter_ids = set()
    paths: set[Path] = set()
    pages_count = 0
    for entry in catalogue:
        if not isinstance(entry, dict) or entry.get("kind") != "manga" or entry.get("direction") not in ("ltr", "rtl", "vertical"):
            raise ControllerError("Invalid catalogue entry")
        sid = valid_id(entry["id"], "mng")
        if sid in series_ids:
            raise ControllerError("Duplicate series ID")
        series_ids.add(sid)
        safe_text(entry["title"], 180)
        sequences = set()
        for chapter in entry["chapters"]:
            cid = valid_id(chapter["id"], "ch")
            if cid in chapter_ids or chapter["sequence"] in sequences:
                raise ControllerError("Duplicate chapter identity or sequence")
            sequences.add(chapter["sequence"])
            chapter_ids.add(cid)
            manifest = validate_manifest_json(load_json(bundle / "manifests" / f"{cid}.json"))
            if manifest.chapterId != cid or chapter["pageCount"] != len(manifest.pages):
                raise ControllerError("Chapter/manifest mismatch")
            for page in manifest.pages:
                if not page.assetPath.startswith(f"manga/{sid}/{cid}/"):
                    raise ControllerError("Page asset does not belong to chapter")
                target = bundle / "assets" / page.assetPath
                if target.is_symlink() or not target.is_file() or target in paths:
                    raise ControllerError("Missing, linked or duplicated page asset")
                checked = check_bytes(read_limited(target, limits.max_image_bytes), page.assetPath, limits)
                if ((checked.checksum, checked.byte_size, checked.mime, checked.width, checked.height)
                        != (page.sha256, page.byteSize, page.mimeType, page.width, page.height)):
                    raise ControllerError("Page checksum or decoded metadata changed")
                paths.add(target)
                pages_count += 1
    assets = set((bundle / "assets" / "manga").rglob("*")) if (bundle / "assets" / "manga").exists() else set()
    actual_files = {p for p in assets if p.is_file()}
    if actual_files != paths or any(p.is_symlink() for p in assets):
        raise ControllerError("Orphaned, missing or linked page assets")
    if (len(series_ids), len(chapter_ids), pages_count) != (inventory.get("series"), inventory.get("chapters"), inventory.get("pages")):
        raise ControllerError("Inventory totals differ from verified files")
    rights_path = bundle / "rights.json"
    if rights_path.exists():
        parse_rights(rights_path)
    if inventory.get("rightsVerified") != rights_path.exists():
        raise ControllerError("Rights evidence state mismatched")
    return {"series": len(series_ids), "chapters": len(chapter_ids), "pages": pages_count,
            "rightsDeclared": rights_path.exists(), "warnings": inventory.get("warnings", [])}
