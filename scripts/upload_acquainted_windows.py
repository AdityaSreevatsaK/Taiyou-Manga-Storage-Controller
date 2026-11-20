"""Windows upload assistant for Acquainted: Encounter Spin-Off.

Input: a folder containing the chapter-page ZIP, a metadata ZIP containing
metadata.json/metaddata.json and candidates.json, and a separate original
cover JPG/PNG/WebP/AVIF image. Requires an authorised source-rights declaration.

Run: py -3.11 scripts/upload_acquainted_windows.py --folder D:/Manga/Acquainted

This uses the existing verified flat builder, private HF append-only uploader
and revision-guarded metadata/cover reconciliation. No alternate schema, no
public cover uploads, no replacement of existing chapters or media.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

NAME = "Acquainted: Encounter Spin-Off"
DATASET = "AdityaSreevatsaK/Taiyous-Manga"
SOURCE_KEY = "acquainted-encounter-spin-off"
PAGE_NAME = re.compile(r"(?P<chapter>[0-9]+)_(?P<page>[0-9]+)\.(?:jpg|jpeg|png|webp|avif)$", re.I)
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
META_NAMES = {"metadata.json", "metaddata.json"}
MAX_ARCHIVE_FILES = 20000
MAX_ARCHIVE_BYTES = 5_000_000_000
MAX_PAGE_BYTES = 25_000_000


def fail(message: str) -> None:
    raise RuntimeError(message)


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as reader:
        for chunk in iter(lambda: reader.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_zip_member(item: zipfile.ZipInfo) -> str:
    name = item.filename
    parts = PurePosixPath(name).parts
    if (
        not name
        or name.startswith("/")
        or "\\" in name
        or "\x00" in name
        or any(part in ("", ".", "..") for part in parts)
        or ":" in name
        or item.flag_bits & 1
    ):
        fail(f"Unsafe ZIP member path or encryption: {name!r}")
    mode = item.external_attr >> 16
    if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
        fail(f"Unsupported ZIP file type: {name!r}")
    if item.file_size > 0 and item.file_size > max(1, item.compress_size) * 250:
        fail(f"Suspiciously compressed ZIP entry: {name!r}")
    return parts[-1]


def discover(root: Path, explicit_images: str | None, explicit_metadata: str | None) -> tuple[Path, Path]:
    candidates = list(root.glob("*.zip"))
    if not candidates:
        fail(f"No ZIP files found in {root}")
    image_choices = []
    metadata_choices = []
    for path in candidates:
        with zipfile.ZipFile(path) as archive:
            files = [i for i in archive.infolist() if not i.is_dir()]
            if len(files) > MAX_ARCHIVE_FILES:
                fail("Archive contains too many files")
            basenames = [check_zip_member(i).lower() for i in files]
            image_count = sum(PAGE_NAME.fullmatch(name) is not None for name in basenames)
            if image_count:
                image_choices.append((path, image_count))
            if any(name in META_NAMES for name in basenames):
                metadata_choices.append(path)
    images = Path(explicit_images).resolve() if explicit_images else None
    metadata = Path(explicit_metadata).resolve() if explicit_metadata else None
    if images is None:
        if len(image_choices) != 1:
            fail(f"Cannot uniquely identify chapter ZIP: {image_choices}; pass --images-zip")
        images = image_choices[0][0]
    if metadata is None:
        if len(metadata_choices) != 1:
            fail(f"Cannot uniquely identify metadata ZIP: {metadata_choices}; pass --metadata-zip")
        metadata = metadata_choices[0]
    if images == metadata or not images.is_file() or not metadata.is_file():
        fail("Chapter images and metadata must be distinct readable ZIP files")
    return images, metadata


def read_metadata(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    with zipfile.ZipFile(path) as archive:
        files = [i for i in archive.infolist() if not i.is_dir()]
        named: dict[str, zipfile.ZipInfo] = {}
        for item in files:
            basename = check_zip_member(item).lower()
            if basename in META_NAMES | {"candidates.json"}:
                if basename in named:
                    fail(f"Duplicate metadata ZIP item: {basename}")
                named[basename] = item
        original = named.get("metadata.json") or named.get("metaddata.json")
        if original is None:
            fail("Metadata ZIP must include metadata.json or metaddata.json")
        if original.file_size > 2_000_000:
            fail("Metadata JSON too large")
        doc = json.loads(archive.read(original))
        if not isinstance(doc, dict) or doc.get("title") != NAME:
            fail("Metadata ZIP title differs from Acquainted: Encounter Spin-Off")
        candidate = {}
        if "candidates.json" in named:
            item = named["candidates.json"]
            if item.file_size > 2_000_000:
                fail("Candidates JSON too large")
            payload = json.loads(archive.read(item))
            rows = payload.get("candidates", [])
            if len(rows) != 1:
                fail("Expected exactly one metadata candidate")
            candidate = rows[0]
            if candidate.get("title") != NAME:
                fail("Candidate title differs from the supplied metadata")
        return doc, candidate


def find_cover(root: Path, explicit: str | None, images: Path, metadata: Path) -> Path:
    if explicit:
        cover = Path(explicit).resolve()
        if not cover.is_file() or cover.suffix.lower() not in IMAGE_SUFFIXES:
            fail("Specified cover path is missing or not a supported image")
        return cover
    options = [
        file
        for file in root.iterdir()
        if file.is_file()
        and not file.is_symlink()
        and file.suffix.lower() in IMAGE_SUFFIXES
        and file not in (images, metadata)
        and PAGE_NAME.fullmatch(file.name) is None
    ]
    if len(options) != 1:
        fail(f"Expected exactly one separate cover image in {root}; found {len(options)}. Use --cover")
    return options[0]


def extract_pages(archive_path: Path, output: Path) -> int:
    output.mkdir(parents=True, exist_ok=True)
    seen_numbers: set[tuple[int, int]] = set()
    count = 0
    total = 0
    with zipfile.ZipFile(archive_path) as archive:
        files = [i for i in archive.infolist() if not i.is_dir()]
        if len(files) > MAX_ARCHIVE_FILES:
            fail("Excessive image ZIP file count")
        for info in files:
            name = check_zip_member(info)
            matched = PAGE_NAME.fullmatch(name)
            if not matched:
                if Path(name).suffix.lower() in IMAGE_SUFFIXES and name.lower() not in {
                    "cover.jpg",
                    "cover.jpeg",
                    "cover.png",
                    "cover.webp",
                    "cover.avif",
                }:
                    fail(f"Unrecognised page image, refusing to skip: {name}")
                continue
            key = (int(matched["chapter"]), int(matched["page"]))
            if key in seen_numbers:
                fail(f"Repeated chapter and page numbers in ZIP: {key}")
            seen_numbers.add(key)
            if not 0 < info.file_size <= MAX_PAGE_BYTES:
                fail(f"Invalid or oversized page image: {name}")
            total += info.file_size
            if total > MAX_ARCHIVE_BYTES:
                fail("Uncompressed manga exceeds the 5 GB safety limit")
            target = output / name
            digest = hashlib.sha256()
            with archive.open(info) as source:
                if target.exists():
                    if target.is_symlink() or not target.is_file() or target.stat().st_size != info.file_size:
                        fail(f"Existing page extraction differs: {target}")
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(block)
                    if sha_file(target) != digest.hexdigest():
                        fail(f"Existing extracted page has changed: {name}")
                else:
                    # New-file mode avoids overwriting anything during retries.
                    with target.open("xb") as sink:
                        for block in iter(lambda: source.read(1024 * 1024), b""):
                            digest.update(block)
                            sink.write(block)
                    if target.stat().st_size != info.file_size:
                        fail(f"ZIP page was truncated: {name}")
            count += 1
    if count == 0:
        fail("No <chapter>_<page>.jpg files found in chapter ZIP")
    if len(list(output.iterdir())) != count:
        fail("The extraction directory contains stale or unexpected files")
    print(f"Verified ZIP extraction: {count} numbered images ({total / 1_000_000:.1f} MB)")
    return count


def source_rights(work: Path, title: str, supplied: str | None) -> Path:
    path = work / "rights.json"
    if supplied:
        original = Path(supplied).resolve()
        if not original.is_file():
            fail("Supplied --rights-json file does not exist")
        if path.exists() and path.read_bytes() != original.read_bytes():
            fail("A different source rights file was used previously; inspect the private work directory")
        if not path.exists():
            shutil.copy2(original, path)
        return path
    if path.exists():
        return path
    print("\nThe Controller requires a truthful declaration of rights to store the chapter images.")
    print("Having downloaded files does not itself establish copyright permission.")
    print("Choose: original (you created them), owned (you own the rights),")
    print("or licensed (you have permission for this private storage).")
    kind = input("Rights type [original/owned/licensed]: ").strip().lower()
    if kind not in {"original", "owned", "licensed"}:
        fail("Cannot upload without a valid and truthful source-rights declaration")
    evidence = input("Describe the actual permission/rights evidence: ").strip()
    if len(evidence) < 12:
        fail("Permission evidence is required; do not invent permission")
    record = {
        "schemaVersion": 1,
        "sourceType": kind,
        "title": title,
        "permissionEvidence": evidence,
        "attribution": "Perilla (Deulkkae), PAMBA / original rights holders",
        "recordedAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def metadata_candidate(
    meta: dict[str, Any],
    supplied: dict[str, Any],
    manga_id: str,
    cover: Path,
    work: Path,
) -> Path:
    from taiyou_manga.images import check_bytes

    meta_root = work / "metadata"
    cover_root = meta_root / "covers"
    cover_root.mkdir(parents=True, exist_ok=True)
    if cover.stat().st_size > 5_000_000:
        fail("Cover exceeds Controller's 5 MB private cover limit")
    target = cover_root / ("acquainted_encounter_spin_off" + cover.suffix.lower())
    checked = check_bytes(cover.read_bytes(), target.name)
    if target.exists():
        if sha_file(target) != checked.checksum:
            fail("Existing staged cover differs from the owner-supplied cover")
    else:
        shutil.copy2(cover, target)

    source = supplied.get("source") or {
        "provider": "tapas",
        "sourceId": "acquainted-encounter-spin-off",
        "sourceUrl": meta["references"]["officialEnglishPublisher"],
        "retrievedAt": meta.get("retrievedOn", "2026-11-20") + "T17:00:00Z",
    }
    source_fields = supplied.get("metadata", {})
    aliases = source_fields.get("aliases", meta.get("aliases", []))
    tags = source_fields.get("tags") or [*meta.get("genreTags", []), *meta.get("descriptiveTags", [])]
    creators = meta.get("creators") or [r["name"] for r in meta["creatorRoles"]]
    fields = {
        "aliases": aliases,
        "creators": creators,
        "creatorRoles": source_fields.get("creatorRoles", meta["creatorRoles"]),
        "tags": list(dict.fromkeys(tags)),
        "publicationStatus": source_fields.get("publicationStatus", meta["publicationStatus"]),
        "synopsis": source_fields.get("synopsis", meta["synopsis"]),
        "cover": {
            "file": f"covers/{target.name}",
            "rightsEvidence": (
                "Owner supplied the original cover for a private personal library; "
                "redistribution permission has not been independently verified."
            ),
            "attribution": meta.get("publicationCredits", "Perilla / PAMBA"),
        },
    }
    payload = {
        "schemaVersion": 1,
        "mediaKind": "manga-metadata-candidates",
        "candidates": [{"mangaId": manga_id, "title": meta["title"], "source": source, "metadata": fields}],
    }
    destination = meta_root / "candidates.json"
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    from taiyou_manga.metadata import load_candidates

    parsed, _ = load_candidates(destination)
    if len(parsed) != 1:
        fail("Metadata candidate did not pass the Controller's strict schema validation")
    return destination


def unique_plan(work: Path, prefix: str) -> Path:
    plans = work / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    return plans / f"{prefix}-{uuid.uuid4().hex[:12]}.json"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Upload Acquainted: Encounter Spin-Off to private canonical Hugging Face"
    )
    parser.add_argument("--folder", type=Path, default=Path("."))
    parser.add_argument("--images-zip", help="Explicit images ZIP (only if auto-discovery ambiguous)")
    parser.add_argument("--metadata-zip", help="Explicit metadata ZIP (only if auto-discovery ambiguous)")
    parser.add_argument("--cover", help="Separate owner-supplied cover JPG/PNG/WebP/AVIF")
    parser.add_argument("--rights-json", help="Existing truthful v1 source-rights JSON (optional)")
    parser.add_argument(
        "--use-reviewed-repairs",
        action="store_true",
        help="Use explicitly inspected, visually approved local JPEG repair copies",
    )
    parser.add_argument(
        "--refresh-source-images",
        action="store_true",
        help="Archive previous local extracted pages and bundle after repairing the source ZIP",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Build locally and preview, but do not write HF"
    )
    args = parser.parse_args()

    root = args.folder.resolve()
    if not root.is_dir():
        fail(f"Missing input folder: {root}")
    images_zip, metadata_zip = discover(root, args.images_zip, args.metadata_zip)
    meta, candidate = read_metadata(metadata_zip)
    cover = find_cover(root, args.cover, images_zip, metadata_zip)
    print(f"Title: {NAME}\nChapter ZIP: {images_zip.name}")
    print(f"Metadata ZIP: {metadata_zip.name}\nCover: {cover.name}")
    print(f"Private target: {DATASET}")
    work = root / ".acquainted-private-import"
    work.mkdir(parents=True, exist_ok=True)
    if args.refresh_source_images:
        for directory in ("pages", "validated-pages", "bundle"):
            previous = work / directory
            if previous.exists() or previous.is_symlink():
                if previous.is_symlink() or not previous.is_dir():
                    fail(f"Invalid existing private import directory: {previous}")
                backup = work / f"previous-{directory}-{uuid.uuid4().hex[:12]}"
                previous.rename(backup)
                print(f"Preserved prior {directory} at {backup}", flush=True)
    pages = work / "pages"
    total_pages = extract_pages(images_zip, pages)
    if __package__:
        from .acquainted_image_repair import inspect_and_prepare
    else:
        from acquainted_image_repair import inspect_and_prepare

    selected_pages = inspect_and_prepare(
        pages, work, use_reviewed_repairs=args.use_reviewed_repairs
    )
    rights = source_rights(work, NAME, args.rights_json)

    from taiyou_manga.builder import build, load_json, verify_bundle
    from taiyou_manga.flat_import import flat_preview
    from taiyou_manga.hf_bulk import DATASET as BULK_DATASET
    from taiyou_manga.hf_bulk import plan_upload, upload
    from taiyou_manga.hf_manage import snapshot
    from taiyou_manga.hf_metadata import _api
    from taiyou_manga.hf_metadata import apply as apply_metadata
    from taiyou_manga.hf_metadata import preview as preview_metadata

    if BULK_DATASET != DATASET:
        fail("Controller HF dataset target differs from the intended private repository")
    summary = flat_preview(selected_pages, NAME)
    if summary["pages"] != total_pages:
        fail("Flat preview page count differs from extracted images")
    print(f"Chapters detected: {summary['chapters']}; pages: {summary['pages']}")
    print(f"Missing chapter numbers (review): {summary['missingChapterNumbers']}")
    bundle = work / "bundle"
    if bundle.exists():
        checked = verify_bundle(bundle)
    else:
        checked = build(
            selected_pages,
            bundle,
            work / "ids.json",
            NAME,
            "vertical",
            rights,
            allow_duplicate_pages=True,
            flat_numbered=True,
            manga_key=SOURCE_KEY,
        )
    if checked["pages"] != total_pages or checked["chapters"] != summary["chapters"]:
        fail("Local canonical bundle failed chapter/page count verification")
    entry = load_json(bundle / "catalogue.json")[0]
    manga_id = entry["id"]
    print(f"Canonical local bundle verified: {manga_id} ({total_pages} pages)")
    candidate_file = metadata_candidate(meta, candidate, manga_id, cover, work)
    if args.dry_run:
        print(f"Dry run complete. No HF writes. Bundle: {bundle}")
        print(f"Private metadata candidate: {candidate_file}")
        return 0

    token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        token = getpass.getpass("Private Hugging Face write token (hidden input): ").strip()
    if not token:
        fail("Missing HF_TOKEN; private upload not attempted")
    api = _api(token)
    info = api.dataset_info(DATASET, token=token)
    if info.private is not True:
        fail("Target dataset is not private; refusing any upload")

    before_api, before_sha, _, _, before_entries = snapshot(token)
    known = {existing["id"]: existing for existing in before_entries}
    if manga_id in known and known[manga_id]["chapters"] != entry["chapters"]:
        fail("Existing manga chapter IDs differ; refusing to replace published pages")
    print(f"Current private dataset revision: {before_sha}")

    upload_plan = unique_plan(work, "chapter-upload")
    proposed = plan_upload(token, bundle, upload_plan)
    if proposed.get("status") != "ready":
        fail(f"Upload preview requires review: {proposed['items']}")
    if proposed.get("new", 0) > 1:
        fail("This script may upload only one newly published manga")
    print(
        f"Verified chapter-upload preview: {proposed['new']} new, "
        f"{proposed['unchanged']} unchanged; no existing files overwritten."
    )
    result = upload(token, bundle, upload_plan, approve=True)
    print(f"Chapter upload: {result['status']}; dataset revision: {result['revision']}")

    metadata_plan = unique_plan(work, "metadata")
    meta_preview = preview_metadata(api, token, candidate_file)
    metadata_plan.write_text(
        json.dumps(meta_preview, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    if meta_preview["status"] == "conflict":
        fail(f"Chapter upload completed, but metadata has review conflicts: {meta_preview['conflicts']}")
    if meta_preview["status"] == "ready":
        meta_result = apply_metadata(api, token, candidate_file, metadata_plan, approve=True)
        print(
            f"Metadata and private cover: {meta_result['status']}, covers added: {meta_result['coversAdded']}"
        )
    else:
        print("Metadata already present; nothing to overwrite.")

    _, final_sha, final_files, _, entries = snapshot(token)
    found = [item for item in entries if item["id"] == manga_id]
    if len(found) != 1:
        fail("Post-write verification failed: manga ID missing or duplicated")
    final = found[0]
    if final["chapters"] != entry["chapters"]:
        fail("Post-write verification failed: chapter IDs or page counts changed")
    if not all(final.get(field) for field in ("cover", "creators", "synopsis", "tags")):
        fail("Post-write verification failed: publication metadata is incomplete")
    if f"data/{final['cover']['assetPath']}" not in final_files:
        fail("Post-write verification failed: cover image is missing")
    if any(entries_id not in {e["id"] for e in entries} for entries_id in known):
        fail("Post-write verification failed: pre-existing manga disappeared")
    if any(next(e for e in entries if e["id"] == sid) != old for sid, old in known.items()):
        fail("Post-write verification failed: a pre-existing manga changed")
    print(
        json.dumps(
            {
                "status": "verified",
                "dataset": DATASET,
                "revision": final_sha,
                "mangaId": manga_id,
                "chapters": len(final["chapters"]),
                "pages": sum(ch["pageCount"] for ch in final["chapters"]),
                "cover": "verified-private",
                "existingMangaPreserved": len(known),
                "privateWorkDirectory": str(work),
            },
            indent=2,
        )
    )
    print("SUCCESS: Canonical manga images, publication metadata and cover uploaded.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, OSError, zipfile.BadZipFile, KeyError) as exc:
        print(f"\nUPLOAD NOT VERIFIED: {exc}", file=sys.stderr)
        print("Keep the private working folder intact. Re-run after resolving the issue.", file=sys.stderr)
        sys.exit(2)
