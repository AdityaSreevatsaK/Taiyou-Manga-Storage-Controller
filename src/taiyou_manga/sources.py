"""Safe image folder and ZIP/CBZ import; no extraction to untrusted paths."""

from __future__ import annotations

import re
import stat
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .domain import IMAGE_EXTENSIONS, ControllerError
from .images import DEFAULT_LIMITS, Limits, read_limited


@dataclass(frozen=True)
class RawPage:
    name: str
    data: bytes


@dataclass(frozen=True)
class ChapterSource:
    key: str
    series_key: str
    series_title: str
    chapter_label: str
    volume: str | None
    pages: tuple[RawPage, ...]


def natural_key(name: str) -> list[tuple[int, object]]:
    return [(1, int(s)) if s.isdigit() else (0, s.casefold()) for s in re.split(r"(\d+)", name)]


def _safe_member(name: str) -> None:
    if not name or len(name) > 240 or "\\" in name or "\x00" in name or "%" in name:
        raise ControllerError("Unsafe ZIP member name")
    parsed = PurePosixPath(name)
    if (
        parsed.is_absolute()
        or any(part in ("..", ".") for part in name.split("/"))
        or ":" in name
        or len(parsed.parts) > 10
        or any(not part for part in name.split("/"))
    ):
        raise ControllerError("ZIP traversal or invalid member path")


def read_archive(path: Path, limits: Limits = DEFAULT_LIMITS) -> tuple[RawPage, ...]:
    try:
        if path.stat().st_size > limits.max_archive_bytes:
            raise ControllerError("Archive compressed size exceeds quota")
        with zipfile.ZipFile(path) as zf:
            entries = zf.infolist()
            if not 1 <= len(entries) <= limits.max_pages:
                raise ControllerError("Archive entry count exceeds limit")
            names: set[str] = set()
            total = 0
            images: list[tuple[str, zipfile.ZipInfo]] = []
            for member in entries:
                # Standard CBZ files may contain explicit directory entries.
                # Validate the underlying path before ignoring those entries.
                _safe_member(member.filename[:-1] if member.is_dir() else member.filename)
                if member.is_dir():
                    continue
                mode = member.external_attr >> 16
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                    raise ControllerError("Archive contains a symlink or special file")
                folded = member.filename.casefold()
                if folded in names:
                    raise ControllerError("Duplicate archive member path")
                names.add(folded)
                if member.flag_bits & 1:
                    raise ControllerError("Encrypted archives are unsupported")
                if not 0 < member.file_size <= limits.max_image_bytes:
                    raise ControllerError("Archive member file-size limit exceeded")
                if member.file_size > max(member.compress_size, 1) * limits.max_ratio:
                    raise ControllerError("Suspicious archive compression ratio")
                total += member.file_size
                if total > limits.max_archive_bytes:
                    raise ControllerError("Archive uncompressed quota exceeded")
                if Path(member.filename).suffix.lower() not in IMAGE_EXTENSIONS:
                    raise ControllerError("Non-image file inside archive")
                images.append((member.filename, member))
            if not 1 <= len(images) <= limits.max_pages:
                raise ControllerError("No valid image pages in archive")
            result = []
            for filename, info in sorted(images, key=lambda item: natural_key(item[0])):
                with zf.open(info) as handle:
                    data = handle.read(limits.max_image_bytes + 1)
                if len(data) != info.file_size or len(data) > limits.max_image_bytes:
                    raise ControllerError("Unexpected archive member size")
                result.append(RawPage(filename, data))
            return tuple(result)
    except (zipfile.BadZipFile, EOFError, RuntimeError, OSError) as exc:
        raise ControllerError("Invalid, damaged or unreadable ZIP/CBZ archive") from exc


def _check_path(path: Path, root: Path) -> None:
    if path.is_symlink():
        raise ControllerError("Symlink input is forbidden")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ControllerError("Input escapes selected root")


def read_folder(path: Path, root: Path, limits: Limits = DEFAULT_LIMITS) -> tuple[RawPage, ...]:
    files = sorted((p for p in path.iterdir() if p.is_file()), key=lambda p: natural_key(p.name))
    if not 1 <= len(files) <= limits.max_pages:
        raise ControllerError("Chapter folder contains no pages or too many entries")
    total = 0
    for image_path in files:
        _check_path(image_path, root)
        if image_path.suffix.lower() not in IMAGE_EXTENSIONS:
            raise ControllerError(f"Unsupported chapter file: {image_path.name}")
        size = image_path.stat().st_size
        if size < 1 or size > limits.max_image_bytes:
            raise ControllerError(f"Image file size exceeds quota: {image_path.name}")
        total += size
        if total > limits.max_archive_bytes:
            raise ControllerError("Chapter folder total size exceeds quota")
    result = []
    actual_total = 0
    for image_path in files:
        _check_path(image_path, root)
        data = read_limited(image_path, limits.max_image_bytes)
        actual_total += len(data)
        if actual_total > limits.max_archive_bytes:
            raise ControllerError("Chapter folder total size changed beyond quota")
        result.append(RawPage(image_path.name, data))
    return tuple(result)


def _infer(root: Path, chapter: Path, *, single: bool = False) -> tuple[str, str, str, str | None]:
    if single:
        return ".", root.stem if root.is_file() else root.name, "Chapter 1", None
    parts = chapter.relative_to(root).parts
    series = parts[0]
    label = Path(parts[-1]).stem if chapter.is_file() else parts[-1]
    volume = parts[-2] if len(parts) >= 3 else None
    return series, series, label, volume


def _directories(root: Path, limits: Limits) -> Iterator[Path]:
    """Bounded directory walk, rejecting suspiciously deep or enormous trees."""
    stack = [(root, 0)]
    visited = 0
    while stack:
        folder, depth = stack.pop()
        children = []
        for child in folder.iterdir():
            visited += 1
            if visited > limits.max_source_entries:
                raise ControllerError("Input source tree exceeds entry quota")
            children.append(child)
        children.sort(key=lambda path: natural_key(path.name))
        directories = []
        for child in children:
            _check_path(child, root)
            if child.is_dir():
                if depth + 1 > limits.max_source_depth:
                    raise ControllerError("Input source directory nesting exceeds depth quota")
                directories.append((child, depth + 1))
        stack.extend(reversed(directories))
        yield folder


def _discover(source: Path, limits: Limits) -> Iterator[ChapterSource]:
    if source.is_symlink() or not source.exists():
        raise ControllerError("Input does not exist or is a symlink")
    if source.is_file():
        if source.suffix.lower() not in (".zip", ".cbz"):
            raise ControllerError("Only ZIP/CBZ files are accepted as archives")
        key, title, label, volume = _infer(source, source, single=True)
        yield ChapterSource(".", key, title, label, volume, read_archive(source, limits))
        return
    root = source.resolve()
    found = 0
    for folder in _directories(root, limits):
        image_files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
        if image_files:
            if folder == root:
                key, title, label, volume = _infer(root, folder, single=True)
            else:
                key, title, label, volume = _infer(root, folder)
            found += 1
            yield ChapterSource(
                folder.relative_to(root).as_posix(),
                key,
                title,
                label,
                volume,
                read_folder(folder, root, limits),
            )
        for arc in sorted(folder.glob("*"), key=lambda p: natural_key(p.name)):
            if arc.is_file() and arc.suffix.lower() in (".zip", ".cbz"):
                _check_path(arc, root)
                key, title, label, volume = _infer(root, arc)
                found += 1
                yield ChapterSource(
                    arc.relative_to(root).as_posix(), key, title, label, volume, read_archive(arc, limits)
                )
    if not found:
        raise ControllerError("No supported chapter folders or archives found")


def discover(source: Path, limits: Limits = DEFAULT_LIMITS) -> Iterator[ChapterSource]:
    """Validate aggregate quotas while yielding only one decoded chapter at a time."""
    if (
        limits.max_chapters < 1
        or limits.max_total_import_bytes < 1
        or limits.max_source_depth < 1
        or limits.max_source_entries < 1
    ):
        raise ControllerError("Invalid import quotas")
    chapters = 0
    total = 0
    for item in _discover(source, limits):
        chapters += 1
        if chapters > limits.max_chapters:
            raise ControllerError("Total chapter count exceeds import quota")
        total += sum(len(page.data) for page in item.pages)
        if total > limits.max_total_import_bytes:
            raise ControllerError("Total image bytes exceed import quota")
        yield item
