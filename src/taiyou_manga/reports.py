"""Verified, private and spreadsheet-safe manga inventory reports."""

from __future__ import annotations

import csv
from pathlib import Path

from .builder import load_json, verify_bundle
from .domain import ControllerError

FIELDS = (
    "series_id",
    "series_title",
    "chapter_id",
    "chapter_label",
    "volume",
    "chapter_sequence",
    "page_count",
    "total_bytes",
    "rights_declared",
)


def _spreadsheet_safe(value: str) -> str:
    """Prevent formula execution when exported titles or labels are opened in Excel."""
    if value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_inventory_csv(bundle: Path, output: Path) -> dict[str, object]:
    """Write only verified chapter aggregates to a new, private CSV file."""
    if output.suffix.casefold() != ".csv":
        raise ControllerError("CSV report destination must end with .csv")
    if output.is_symlink() or output.exists():
        raise ControllerError("CSV report destination already exists; refusing overwrite")
    if output.resolve().is_relative_to(bundle.resolve()):
        raise ControllerError("CSV report must not be created inside a verified bundle")

    totals = verify_bundle(bundle)
    rows: list[dict[str, object]] = []
    for series in load_json(bundle / "catalogue.json"):
        for chapter in series["chapters"]:
            manifest = load_json(bundle / "manifests" / f"{chapter['id']}.json")
            rows.append(
                {
                    "series_id": series["id"],
                    "series_title": _spreadsheet_safe(series["title"]),
                    "chapter_id": chapter["id"],
                    "chapter_label": _spreadsheet_safe(chapter["label"]),
                    "volume": _spreadsheet_safe(chapter.get("volume", "")),
                    "chapter_sequence": chapter["sequence"],
                    "page_count": len(manifest["pages"]),
                    "total_bytes": sum(page["byteSize"] for page in manifest["pages"]),
                    "rights_declared": "yes" if totals["rightsDeclared"] else "no",
                }
            )
    rows.sort(
        key=lambda item: (
            str(item["series_title"]).casefold(),
            int(str(item["chapter_sequence"])),
            str(item["chapter_id"]),
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with output.open("x", encoding="utf-8-sig", newline="") as handle:
            created = True
            writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    except BaseException:
        if created:
            output.unlink(missing_ok=True)
        raise

    return {
        "output": str(output),
        "chapters": len(rows),
        "series": totals["series"],
        "pages": totals["pages"],
        "report": "private-csv-inventory",
    }
