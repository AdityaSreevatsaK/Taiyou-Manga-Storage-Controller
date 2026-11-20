"""Import a single manga from a flat folder of <chapter>_<page> image files.

Examples: 1_0.jpg, 1_1.jpg, 1_10.jpg, 2_0.png. This is a local
preparation adapter only, not a second Hugging Face storage format.
The regular bundle builder and revision-guarded hf_bulk uploader handle
canonical mng/ch/pg IDs, manifests, paths, backups and remote publication.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .domain import IMAGE_EXTENSIONS, ControllerError, safe_text
from .images import DEFAULT_LIMITS, Limits, read_limited
from .sources import ChapterSource, RawPage

FLAT_NAME = re.compile(r"^(?P<chapter>[0-9]+)_(?P<page>[0-9]+)\.(?P<ext>png|jpg|jpeg|webp|avif)$", re.I)
MAX_INDEX = 1_000_000


@dataclass(frozen=True)
class FlatChapter:
    number: int
    files: tuple[Path, ...]
    first_page: int
    last_page: int
    size_bytes: int


@dataclass(frozen=True)
class FlatInventory:
    chapters: tuple[FlatChapter, ...]
    bytes_total: int
    pages: int
    missing_chapters: tuple[int, ...]


def inspect_flat(source: Path, limits: Limits = DEFAULT_LIMITS) -> FlatInventory:
    """Fast filename/size validation; does not modify the input or decode images.

    Complete decoding and SHA-256 verification occur when building the bundle.
    """
    if not source.is_dir() or source.is_symlink():
        raise ControllerError("Flat manga source must be a real, non-symlinked image directory")
    children = list(source.iterdir())
    if not children:
        raise ControllerError("No images in flat numbered manga source folder")
    if len(children) > limits.max_source_entries:
        raise ControllerError("Flat manga folder exceeds filesystem-entry safety limit")

    grouped: dict[int, list[tuple[int, Path, int]]] = defaultdict(list)
    seen: set[tuple[int, int]] = set()
    total = 0
    for path in children:
        if path.is_symlink() or not path.is_file():
            raise ControllerError("Flat folder must contain only regular images, not symlinks or subfolders")
        if not path.resolve().is_relative_to(source.resolve()):
            raise ControllerError("Flat manga image escapes the selected source directory")
        match = FLAT_NAME.fullmatch(path.name)
        if match is None or path.suffix.lower() not in IMAGE_EXTENSIONS:
            raise ControllerError(
                f"Unexpected image name: {path.name!r}; expected <chapter>_<page>.jpg, e.g. 1_0.jpg"
            )
        chapter, page = int(match["chapter"]), int(match["page"])
        if chapter > MAX_INDEX or page > MAX_INDEX:
            raise ControllerError("Flat chapter/page number exceeds supported index limit")
        key = (chapter, page)
        if key in seen:
            raise ControllerError(f"Duplicate chapter/page number: {chapter}_{page}")
        seen.add(key)
        size = path.stat().st_size
        if not 0 < size <= limits.max_image_bytes:
            raise ControllerError(f"Missing or oversized manga image: {path.name}")
        total += size
        if total > limits.max_total_import_bytes:
            raise ControllerError("Flat manga exceeds the total import size limit")
        grouped[chapter].append((page, path, size))
        if len(grouped) > limits.max_chapters:
            raise ControllerError("Flat manga chapter count exceeds limit")

    chapters: list[FlatChapter] = []
    for number, records in sorted(grouped.items()):
        records.sort(key=lambda item: item[0])
        positions = [x[0] for x in records]
        if len(positions) > limits.max_pages:
            raise ControllerError(f"Too many pages in chapter {number}")
        if positions[0] not in (0, 1):
            raise ControllerError(f"Chapter {number} must start at page 0 or 1, found {positions[0]}")
        expected = list(range(positions[0], positions[0] + len(positions)))
        if positions != expected:
            raise ControllerError(
                f"Chapter {number} has missing page numbers; refusing to silently reorder or omit pages"
            )
        chapter_size = sum(size for _, _, size in records)
        if chapter_size > limits.max_archive_bytes:
            raise ControllerError(f"Chapter {number} exceeds the per-chapter byte limit")
        chapters.append(
            FlatChapter(
                number, tuple(path for _, path, _ in records), positions[0], positions[-1], chapter_size
            )
        )

    # Chapter gaps are warned, not assumed to be missing data (e.g., extra chapters).
    missing: list[int] = []
    labels = sorted(grouped)
    if labels and labels[-1] - labels[0] <= 10_000:
        missing = [value for value in range(labels[0], labels[-1] + 1) if value not in grouped]
    return FlatInventory(tuple(chapters), total, len(children), tuple(missing))


def flat_preview(
    source: Path,
    series_title: str,
    limits: Limits = DEFAULT_LIMITS,
) -> dict[str, object]:
    """Read-only preview; no catalogue/registry or remote write."""
    safe_text(series_title, 180)
    inventory = inspect_flat(source, limits)
    return {
        "status": "flat-image-import-preview",
        "mode": "read-only",
        "seriesTitle": series_title,
        "source": str(source),
        "sourceNaming": "<chapter>_<page>.<png|jpg|jpeg|webp|avif>",
        "chapters": len(inventory.chapters),
        "pages": inventory.pages,
        "bytes": inventory.bytes_total,
        "chapterNumbers": [chapter.number for chapter in inventory.chapters],
        "missingChapterNumbers": list(inventory.missing_chapters),
        "firstPageOfEachChapter": {str(chapter.number): chapter.first_page for chapter in inventory.chapters},
        "remoteWrites": 0,
        "requiresBuild": True,
        "requiresApprovedHfUpload": True,
    }


def discover_flat(
    source: Path,
    series_title: str,
    limits: Limits = DEFAULT_LIMITS,
    *,
    manga_key: str | None = None,
) -> Iterator[ChapterSource]:
    """Yield a single chapter's raw pages at a time, sorted by numeric index."""
    safe_text(series_title, 180)
    inventory = inspect_flat(source, limits)
    # The registry key deliberately does not depend on the manga display title.
    # A moved source folder requires reviewed identity-migrate, as for normal imports.
    if manga_key is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", manga_key):
        raise ControllerError(
            "Stable manga key must contain 1-100 letters, digits, dots, hyphens or underscores"
        )
    source_key = "flat:" + (manga_key if manga_key is not None else source.resolve().as_posix())
    if len(source_key) > 850:
        raise ControllerError("Flat manga source path exceeds stable identity registry limit")
    for chapter in inventory.chapters:
        pages = []
        for path in chapter.files:
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(source.resolve()):
                raise ControllerError("Flat manga source file changed or became unsafe during import")
            data = read_limited(path, limits.max_image_bytes)
            pages.append(RawPage(path.name, data))
        yield ChapterSource(
            key=source_key + ":chapter:" + str(chapter.number),
            series_key=source_key,
            series_title=series_title,
            chapter_label=f"Chapter {chapter.number}",
            volume=None,
            pages=tuple(pages),
        )
