"""Read-only manga operational exports and bounded local cache maintenance."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .domain import ControllerError
from .hf_manage import _csv_file, _json_data, _new_file, normalized_title, snapshot


def chapters_report(token: str, output: Path) -> dict[str, object]:
    _, sha, _, _, entries = snapshot(token)
    rows = []
    for item in entries:
        for chapter in item["chapters"]:
            rows.append(
                {
                    "mangaId": item["id"],
                    "title": item["title"],
                    "chapterId": chapter["id"],
                    "label": chapter["label"],
                    "volume": chapter.get("volume", ""),
                    "sequence": chapter["sequence"],
                    "pages": chapter["pageCount"],
                }
            )
    _csv_file(
        output,
        rows,
        ["mangaId", "title", "chapterId", "label", "volume", "sequence", "pages"],
    )
    return {
        "status": "chapter-inventory",
        "revision": sha,
        "manga": len(entries),
        "chapters": len(rows),
        "report": str(output),
    }


def compare_retriever(token: str, input_json: Path, output: Path) -> dict[str, object]:
    if not input_json.is_file() or input_json.is_symlink():
        raise ControllerError("Private Retriever inventory is missing or unsafe")
    if input_json.stat().st_size > 2 * 1024 * 1024:
        raise ControllerError("Retriever inventory exceeds 2 MiB")
    rows = json.loads(input_json.read_bytes())
    if isinstance(rows, dict):
        rows = rows.get("entries", rows.get("manga"))
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ControllerError("Retriever inventory must contain at most 10000 entries")
    _, sha, _, _, existing = snapshot(token)
    by_id = {item["id"]: item for item in existing}
    names: dict[str, list[str]] = {}
    for item in existing:
        for title in [item["title"], *item["aliases"]]:
            names.setdefault(normalized_title(title), []).append(item["id"])
    report = []
    for item in rows:
        if not isinstance(item, dict) or set(item) - {
            "id",
            "mangaId",
            "title",
            "chapters",
            "pages",
            "sourceUrl",
            "slug",
        }:
            raise ControllerError("Unrecognised Retriever inventory record")
        ident = item.get("mangaId", item.get("id"))
        title = item.get("title")
        if ident is None and not title:
            raise ControllerError("Retriever entries must carry an ID or title")
        if ident is not None and (
            not isinstance(ident, str) or not re.fullmatch(r"mng_[A-Za-z0-9_-]{8,64}", ident)
        ):
            raise ControllerError("Unrecognised private manga identifier in Retriever inventory")
        if title is not None and (not isinstance(title, str) or not 1 <= len(title) <= 180):
            raise ControllerError("Invalid Retriever series title")
        match = by_id.get(ident) if ident else None
        candidates = names.get(normalized_title(title), []) if title else []
        if match:
            status = "existing-by-immutable-id"
            if title and normalized_title(match["title"]) != normalized_title(title):
                status = "id-present-title-differs-review"
        elif ident:
            status = "missing-immutable-id"
        elif len(set(candidates)) == 1:
            status = "title-only-match-needs-id-review"
        elif candidates:
            status = "ambiguous-title-review"
        else:
            status = "not-in-library"
        report.append(
            {
                "id": ident or "",
                "title": title or "",
                "status": status,
                "possibleMangaIds": ", ".join(sorted(set(candidates))),
            }
        )
    _csv_file(output, report, ["id", "title", "status", "possibleMangaIds"])
    return {
        "status": "retriever-comparison",
        "revision": sha,
        "checked": len(report),
        "needsReview": sum(x["status"] != "existing-by-immutable-id" for x in report),
        "report": str(output),
    }


def local_download_cleanup(
    destination: Path, output: Path, *, apply: bool = False, confirm: str = "", older_than_days: int = 7
) -> dict[str, object]:
    """Only orphaned temporary *.part files, never original downloaded ZIP files."""
    if destination.is_symlink() or not destination.is_dir() or not 1 <= older_than_days <= 365:
        raise ControllerError("Select a real local download folder and a 1-365 day age")
    cutoff = time.time() - 86400 * older_than_days
    candidates = []
    for file in sorted(destination.iterdir()):
        if file.is_symlink():
            raise ControllerError("Symlinked files cannot be handled by local cleanup")
        if file.is_file() and file.name.endswith(".part") and file.stat().st_mtime < cutoff:
            candidates.append(file)
    files = [{"path": file.name, "size": file.stat().st_size} for file in candidates]
    summary: dict[str, object] = {
        "status": "preview" if not apply else "local-temp-cleaned",
        "temporaryFiles": len(candidates),
        "bytes": sum(file.stat().st_size for file in candidates),
        "remoteFilesDeleted": 0,
        "mangaArchivesDeleted": 0,
        "files": files,
    }
    if not apply:
        _new_file(output, _json_data(summary))
        return summary
    if confirm != "DELETE OLD LOCAL TEMP FILES":
        raise ControllerError("Exact confirmation is required to clean local temporary files")
    for file in candidates:
        file.unlink()
    return summary
