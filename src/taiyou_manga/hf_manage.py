"""Private manga library management, inspired by Novel Storage Controller tools.

No operations in this module delete private media, reset a dataset, rewrite
chapter manifests or mutate bookmarks. Remote reads are pinned to the same
immutable HF revision. Side effects require an explicit separate approval.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import os
import re
import shutil
import tempfile
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from .builder import load_json, verify_bundle
from .domain import ControllerError, validate_manifest_json
from .hf_layout import CANONICAL_CATALOGUE, canonical_library
from .hf_metadata import _api, _read_file, _snapshot
from .hf_upload import DATASET, UploadConflict
from .metadata import completeness, cover_asset_path

MAX_REPORT_BYTES = 4 * 1024 * 1024
MANGA_ROOT = re.compile(r"^data/manga/(mng_[A-Za-z0-9_-]{8,64})/")
TITLE_SEPARATOR = re.compile(r"[\W_]+", flags=re.UNICODE)


def normalized_title(title: str) -> str:
    return TITLE_SEPARATOR.sub("", unicodedata.normalize("NFKC", title).casefold())


def safe_report_string(value: object) -> str:
    raw = str(value)
    return "'" + raw if raw.lstrip().startswith(("=", "+", "-", "@")) else raw


def _new_file(path: Path, data: bytes) -> None:
    if path.is_symlink() or path.exists():
        raise ControllerError("Output already exists; this tool never overwrites private exports")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def _json_data(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _csv_file(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    if path.is_symlink() or path.exists():
        raise ControllerError("Report destination already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: safe_report_string(row.get(name, "")) for name in fields})


def _totals(entries: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "series": len(entries),
        "chapters": sum(len(item["chapters"]) for item in entries),
        "pages": sum(chapter["pageCount"] for item in entries for chapter in item["chapters"]),
    }


def list_entries(entries: list[dict[str, Any]]) -> list[dict[str, object]]:
    return [
        {
            "id": item["id"],
            "title": item["title"],
            "authorsAndArtists": ", ".join(item["creators"]),
            "chapters": len(item["chapters"]),
            "pages": sum(c["pageCount"] for c in item["chapters"]),
            "publicationStatus": item["publicationStatus"],
            "cover": "yes" if item.get("cover") else "no",
        }
        for item in sorted(entries, key=lambda row: row["title"].casefold())
    ]


def title_conflicts(entries: list[dict[str, Any]]) -> list[dict[str, object]]:
    keys: dict[str, set[str]] = {}
    for item in entries:
        for name in [item["title"], *item["aliases"]]:
            key = normalized_title(name)
            if key:
                keys.setdefault(key, set()).add(item["id"])
    return [
        {"normalisedTitle": name, "mangaIds": sorted(ids), "count": len(ids)}
        for name, ids in sorted(keys.items())
        if len(ids) > 1
    ]


def quick_integrity(
    entries: list[dict[str, Any]], files: set[str]
) -> dict[str, object]:
    missing_manifests: list[str] = []
    missing_covers: list[str] = []
    missing_page_series: list[str] = []
    indexed_manga = {entry["id"] for entry in entries}
    seen_paths = {path.split("/")[2] for path in files if MANGA_ROOT.fullmatch(path[:path.rfind("/") + 1])}
    for item in entries:
        if item["id"] not in seen_paths:
            missing_page_series.append(item["id"])
        for chapter in item["chapters"]:
            path = f"data/manifests/{chapter['id']}.json"
            if path not in files:
                missing_manifests.append(chapter["id"])
        if item.get("cover") and cover_asset_path(item["cover"], item["id"]) not in files:
            missing_covers.append(item["id"])
    orphans = sorted(
        {
            match.group(1)
            for path in files
            if (match := MANGA_ROOT.match(path)) and match.group(1) not in indexed_manga
        }
    )
    return {
        **_totals(entries),
        "missingManifests": sorted(missing_manifests),
        "missingCovers": sorted(missing_covers),
        "missingPageSeries": sorted(missing_page_series),
        "orphanMediaSeries": orphans,
        "titleConflicts": title_conflicts(entries),
        "metadataCompleteness": completeness(entries)["missingCount"],
        "mode": "quick-file-listing-not-byte-level",
        "complete": not any(
            (missing_manifests, missing_covers, missing_page_series, orphans, title_conflicts(entries))
        ),
    }


def _manifest(api: Any, token: str, sha: str, item: dict[str, Any], chapter: dict[str, Any]) -> Any:
    name = f"data/manifests/{chapter['id']}.json"
    raw = _read_file(name, sha, token, 1_000_000)
    manifest = validate_manifest_json(json.loads(raw))
    if manifest.chapterId != chapter["id"] or len(manifest.pages) != chapter["pageCount"]:
        raise ControllerError("Remote manga chapter manifest differs from canonical catalogue")
    for page in manifest.pages:
        if not page.assetPath.startswith(f"manga/{item['id']}/{chapter['id']}/"):
            raise ControllerError("Manifest page belongs to the wrong manga or chapter")
    return manifest


def verified_integrity(
    api: Any, token: str, sha: str, files: set[str],
    entries: list[dict[str, Any]], *, deep: bool = False
) -> dict[str, object]:
    result = quick_integrity(entries, files)
    failures: list[str] = []
    verified_chapters = 0
    verified_pages = 0
    verified_bytes = 0
    for item in entries:
        for chapter in item["chapters"]:
            if f"data/manifests/{chapter['id']}.json" not in files:
                continue
            try:
                doc = _manifest(api, token, sha, item, chapter)
                verified_chapters += 1
                for page in doc.pages:
                    target = f"data/{page.assetPath}"
                    if target not in files:
                        failures.append(f"Missing media: {target}")
                        continue
                    if deep:
                        from .images import check_bytes
                        blob = _read_file(target, sha, token, 25_000_000)
                        checked = check_bytes(blob, target)
                        if (checked.checksum != page.sha256 or checked.byte_size != page.byteSize
                                or checked.width != page.width or checked.height != page.height
                                or checked.mime != page.mimeType):
                            failures.append(f"Image checksum, dimensions or MIME mismatch: {target}")
                            continue
                        verified_bytes += len(blob)
                    verified_pages += 1
            except (ControllerError, ValueError, OSError, KeyError) as exc:
                failures.append(f"Invalid remote chapter {chapter['id']}: {type(exc).__name__}")
    result.update({
        "mode": "full-image-sha256-and-decode" if deep else "manifest-and-path-check",
        "verifiedChapters": verified_chapters,
        "verifiedPages": verified_pages,
        "verifiedImageBytes": verified_bytes,
        "failures": failures,
        "complete": bool(result["complete"]) and not failures
            and verified_chapters == result["chapters"]
            and verified_pages == result["pages"],
    })
    return result


def snapshot(token: str) -> tuple[Any, str, set[str], bytes, list[dict[str, Any]]]:
    api = _api(token)
    sha, files, raw, entries = _snapshot(api, token)
    return api, sha, files, raw, entries


def catalogue_backup(token: str, output: Path) -> dict[str, object]:
    _, sha, _, contents, entries = snapshot(token)
    # A catalogue backup is NOT a backup of original manga media.
    _new_file(output, contents)
    return {
        "status": "catalogue-backed-up", "revision": sha, "entries": len(entries),
        "sha256": hashlib.sha256(contents).hexdigest(), "path": str(output),
        "mediaFilesBackedUp": False,
    }


def export_list(token: str, output: Path) -> dict[str, object]:
    _, sha, _, _, entries = snapshot(token)
    rows = list_entries(entries)
    if output.suffix.casefold() != ".csv":
        raise ControllerError("Manga catalogue export must use .csv")
    fields = ["id", "title", "authorsAndArtists", "chapters", "pages", "publicationStatus", "cover"]
    _csv_file(output, rows, fields)
    return {"status": "listed", "revision": sha, **_totals(entries), "report": str(output)}


def export_report(token: str, output: Path, *, depth: str = "quick") -> dict[str, object]:
    api, sha, files, _, entries = snapshot(token)
    if depth not in ("quick", "manifest", "deep"):
        raise ControllerError("Unsupported private manga integrity verification mode")
    report = (
        quick_integrity(entries, files) if depth == "quick"
        else verified_integrity(api, token, sha, files, entries, deep=depth == "deep")
    )
    report["revision"] = sha
    if output.suffix.casefold() == ".json":
        _new_file(output, _json_data(report))
    elif output.suffix.casefold() == ".csv":
        rows = [
            {"id": row["id"], "title": row["title"], "missing": ", ".join(row["missing"])}
            for row in completeness(entries)["entries"]
        ]
        _csv_file(output, rows, ["id", "title", "missing"])
    elif output.suffix.casefold() == ".html":
        # A private offline dashboard, HTML-escaped; no remote media URLs or scripts.
        boxes = "".join(
            "<tr><td>" + html.escape(str(row["id"])) + "</td><td>"
            + html.escape(row["title"]) + "</td><td>"
            + html.escape(", ".join(row["missing"]) or "Complete") + "</td></tr>"
            for row in completeness(entries)["entries"]
        )
        doc = (
            '<!doctype html><html lang="en"><meta charset="utf-8"><title>Manga library health</title>'
            '<style>body{font:16px system-ui;margin:3rem auto;max-width:950px;line-height:1.5}'
            'th,td{padding:.55rem;border-bottom:1px solid #aaa;text-align:left}</style>'
            "<h1>Private manga library health</h1><p>Verified revision: "
            + html.escape(sha) + "</p><p>Series: " + str(report["series"])
            + "; Chapters: " + str(report["chapters"]) + "; Pages: " + str(report["pages"])
            + '</p><table><tr><th>ID</th><th>Title</th><th>Missing metadata</th></tr>'
            + boxes + "</table></html>"
        )
        _new_file(output, doc.encode("utf-8"))
    else:
        raise ControllerError("Choose .json, .csv or .html for the report")
    return {
        "status": "report-created", "revision": sha, "report": str(output),
        "series": report["series"], "chapters": report["chapters"],
        "pages": report["pages"], "complete": report["complete"],
        "verificationMode": depth,
    }


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _download_file(name: str, sha: str, token: str) -> Path:
    from huggingface_hub import hf_hub_download
    return Path(hf_hub_download(
        repo_id=DATASET, filename=name, repo_type="dataset", revision=sha, token=token
    ))


def _series_archive(
    token: str, sha: str, files: set[str], item: dict[str, Any], output: Path,
    *, catalogue: bytes
) -> dict[str, object]:
    if output.exists() or output.is_symlink():
        return {"status": "skipped-existing", "id": item["id"], "path": str(output)}
    originals: dict[str, str] = {}
    for chapter in item["chapters"]:
        name = f"data/manifests/{chapter['id']}.json"
        if name not in files:
            raise ControllerError("Cannot export a manga with missing chapter manifests")
        manifest = _manifest(None, token, sha, item, chapter)
        for page in manifest.pages:
            remote = f"data/{page.assetPath}"
            if remote not in files:
                raise ControllerError("Cannot export a manga with missing page media")
            originals[remote] = page.sha256
        originals[name] = ""
    if item.get("cover"):
        name = cover_asset_path(item["cover"], item["id"])
        if name not in files:
            raise ControllerError("Cannot export a manga with missing cover image")
        originals[name] = item["cover"]["sha256"]
    if not originals:
        raise ControllerError("No manga source media found")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".part", prefix="manga-backup-", dir=output.parent, delete=False
        ) as writable:
            temp = Path(writable.name)
        manifest_rows = []
        with zipfile.ZipFile(temp, mode="w", compression=zipfile.ZIP_STORED, allowZip64=True) as zipout:
            for name, expected in sorted(originals.items()):
                path = _download_file(name, sha, token)
                digest = _file_digest(path)
                if expected and digest != expected:
                    raise ControllerError("Manga image changed or differs from its catalogue SHA-256")
                zipout.write(path, arcname=name)
                manifest_rows.append({"path": name, "sha256": digest, "bytes": path.stat().st_size})
            zipout.writestr("catalogue/entry.json", _json_data(item))
            zipout.writestr("catalogue/source-library.json", catalogue)
            zipout.writestr(
                "backup-manifest.json",
                _json_data({
                    "schemaVersion": 1, "mediaKind": "manga",
                    "revision": sha, "mangaId": item["id"],
                    "files": manifest_rows, "complete": True,
                }),
            )
        with zipfile.ZipFile(temp, "r") as zipcheck:
            if zipcheck.testzip() is not None:
                raise ControllerError("Private manga archive failed post-write CRC verification")
        temp.replace(output)
        return {"status": "downloaded", "id": item["id"], "path": str(output),
                "files": len(originals), "sha256": _file_digest(output)}
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def download_all(
    token: str, directory: Path, *, manga_id: str | None = None
) -> dict[str, object]:
    _, sha, files, catalogue, entries = snapshot(token)
    if directory.is_symlink():
        raise ControllerError("Private manga download destination may not be a symlink")
    if manga_id:
        entries = [entry for entry in entries if entry["id"] == manga_id]
        if not entries:
            raise ControllerError("Unknown manga ID for download")
    if not entries:
        raise ControllerError("Private manga catalogue contains no downloadable manga")
    directory.mkdir(parents=True, exist_ok=True)
    results = []
    for item in sorted(entries, key=lambda value: value["title"].casefold()):
        # Immutable ID avoids path traversal and title rename collisions.
        target = directory / f"{item['id']}.zip"
        results.append(_series_archive(token, sha, files, item, target, catalogue=catalogue))
    _new_file(
        directory / f"download-report-{sha[:12]}.json",
        _json_data({"sourceRevision": sha, "series": len(results), "results": results}),
    )
    return {
        "status": "download-finished", "revision": sha,
        "downloaded": sum(item["status"] == "downloaded" for item in results),
        "skipped": sum(item["status"] == "skipped-existing" for item in results),
        "directory": str(directory), "series": len(results),
    }


def local_sync(token: str, bundles: Path, report: Path) -> dict[str, object]:
    _, sha, _, _, entries = snapshot(token)
    if not bundles.is_dir() or bundles.is_symlink():
        raise ControllerError("Local manga bundles folder missing or unsafe")
    by_id = {e["id"]: e for e in entries}
    rows = []
    for folder in sorted(path for path in bundles.iterdir() if path.is_dir()):
        if folder.is_symlink():
            raise ControllerError("Symlinked private manga input is unsafe")
        candidate = folder / "catalogue.json"
        if not candidate.exists():
            continue
        verify_bundle(folder)
        local = load_json(candidate)
        if not isinstance(local, list) or len(local) != 1:
            raise ControllerError("Sync requires a verified single-manga bundle per folder")
        item = local[0]
        old = by_id.get(item["id"])
        status = (
            "not-uploaded" if old is None
            else "catalogue-metadata-differs" if old != item
            else "matching-catalogue-structure"
        )
        rows.append({"id": item["id"], "title": item["title"], "status": status,
                     "localChapters": len(item["chapters"]),
                     "remoteChapters": len(old["chapters"]) if old else 0})
    _csv_file(report, rows, ["id", "title", "status", "localChapters", "remoteChapters"])
    return {"status": "sync-report", "revision": sha, "local": len(rows),
            "missing": sum(row["status"] == "not-uploaded" for row in rows),
            "report": str(report), "note": "Metadata structure only, not byte-level file sync"}


def delete_preview(token: str, manga_id: str, output: Path) -> dict[str, object]:
    _, sha, files, old, entries = snapshot(token)
    selected = [row for row in entries if row["id"] == manga_id]
    if len(selected) != 1:
        raise ControllerError("Delete requires exactly one existing immutable manga ID")
    item = selected[0]
    # Reversible de-list only. Original files are retained without exceptions.
    plan = {
        "operation": "delist-manga-only", "revision": sha, "id": manga_id,
        "title": item["title"], "catalogueSha256": hashlib.sha256(old).hexdigest(),
        "remainingCatalogueSha256": hashlib.sha256(_json_data(canonical_library(
            [row for row in entries if row["id"] != manga_id]
        ))).hexdigest(),
        "preservedFiles": len(files), "chaptersRetained": len(item["chapters"]),
        "remoteFileDeletionCount": 0,
    }
    _new_file(output, _json_data(plan))
    return plan


def delete_apply(token: str, manga_id: str, plan_path: Path, confirm_title: str) -> dict[str, object]:
    if not plan_path.is_file() or plan_path.is_symlink():
        raise ControllerError("Private deletion preview must be reviewed before applying")
    api, sha, files, before, entries = snapshot(token)
    selected = [row for row in entries if row["id"] == manga_id]
    if len(selected) != 1 or confirm_title != selected[0]["title"]:
        raise ControllerError("Exact immutable manga ID and display-title confirmation are required")
    expected = json.loads(plan_path.read_bytes())
    result = {
        "operation": "delist-manga-only", "revision": sha, "id": manga_id,
        "title": selected[0]["title"], "catalogueSha256": hashlib.sha256(before).hexdigest(),
        "remainingCatalogueSha256": hashlib.sha256(_json_data(canonical_library(
            [row for row in entries if row["id"] != manga_id]
        ))).hexdigest(),
        "preservedFiles": len(files), "chaptersRetained": len(selected[0]["chapters"]),
        "remoteFileDeletionCount": 0,
    }
    if expected != result:
        raise UploadConflict("Private manga catalogue or approved deletion plan changed")
    backup_path = f"control/delist-backups/{sha}/library.json"
    if backup_path in files:
        raise UploadConflict("Private catalogue backup path already occupied")
    if api.dataset_info(DATASET, token=token).sha != sha:
        raise UploadConflict("Dataset changed while attempting to de-list manga")
    from huggingface_hub import CommitOperationAdd
    api.create_commit(
        repo_id=DATASET, repo_type="dataset", revision="main", token=token,
        parent_commit=sha, commit_message=f"Reversibly de-list manga {manga_id}",
        operations=[
            CommitOperationAdd(path_in_repo=backup_path, path_or_fileobj=before),
            CommitOperationAdd(
                path_in_repo=CANONICAL_CATALOGUE,
                path_or_fileobj=_json_data(canonical_library(
                    [row for row in entries if row["id"] != manga_id]
                )),
            ),
        ],
    )
    _, _, after_files, _, after_entries = snapshot(token)
    if manga_id in {entry["id"] for entry in after_entries} or not files.issubset(after_files):
        raise UploadConflict("De-list verification failed or original files changed")
    return {"status": "delisted", "mangaId": manga_id, "filesDeleted": 0,
            "catalogueBackup": backup_path}
