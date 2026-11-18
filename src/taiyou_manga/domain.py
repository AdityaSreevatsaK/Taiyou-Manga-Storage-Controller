"""Candidate bundle models constrained to the Manga Library's draft v1 types.

The *chapter manifest* and *catalogue entry* JSON mirror the current React
validators. The local inventory envelope is controller-only, not an HF schema.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

IMAGE_EXTENSIONS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".avif": "image/avif"}
ID_RE = re.compile(r"^(?:mng|ch|pg)_[A-Za-z0-9_-]{8,64}$")
ASSET_RE = re.compile(r"^manga/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+\.(?:png|jpg|jpeg|webp|avif)$")
CHECKSUM_RE = re.compile(r"^[0-9a-f]{64}$")


class ControllerError(ValueError):
    """An actionable user-facing validation or operation error."""


def valid_id(value: str, prefix: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value) or not value.startswith(prefix + "_"):
        raise ControllerError(f"Invalid opaque {prefix} ID")
    return value


def safe_text(value: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ControllerError("Invalid text length or empty value")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ControllerError("Control character in metadata")
    return value.strip()


@dataclass(frozen=True)
class Page:
    id: str
    assetPath: str
    mimeType: str
    width: int
    height: int
    byteSize: int
    sha256: str

    def validate(self) -> None:
        valid_id(self.id, "pg")
        if not ASSET_RE.fullmatch(self.assetPath):
            raise ControllerError("Unsafe page asset path")
        extension = "." + self.assetPath.rsplit(".", 1)[-1]
        if IMAGE_EXTENSIONS[extension] != self.mimeType:
            raise ControllerError("Page MIME mismatch")
        if not (1 <= self.width <= 16000 and 1 <= self.height <= 16000):
            raise ControllerError("Page dimensions exceeded")
        if self.width * self.height > 70_000_000:
            raise ControllerError("Page pixel budget exceeded")
        if not (1 <= self.byteSize <= 25_000_000) or not CHECKSUM_RE.fullmatch(self.sha256):
            raise ControllerError("Invalid page size or SHA-256")


@dataclass(frozen=True)
class Chapter:
    id: str
    label: str
    sequence: int
    volume: str | None = None
    pageCount: int | None = None

    def as_json(self) -> dict[str, Any]:
        result: dict[str, Any] = {"id": self.id, "label": self.label, "sequence": self.sequence}
        if self.volume is not None:
            result["volume"] = self.volume
        if self.pageCount is not None:
            result["pageCount"] = self.pageCount
        return result


@dataclass(frozen=True)
class ChapterManifest:
    chapterId: str
    pages: tuple[Page, ...]

    def as_json(self) -> dict[str, Any]:
        return {"schemaVersion": 1, "mediaKind": "manga", "chapterId": self.chapterId,
                "pages": [asdict(p) for p in self.pages]}

    def validate(self) -> None:
        valid_id(self.chapterId, "ch")
        if not 1 <= len(self.pages) <= 1000:
            raise ControllerError("Chapter must contain 1 to 1000 pages")
        ids, paths = set(), set()
        for page in self.pages:
            page.validate()
            if page.id in ids or page.assetPath in paths:
                raise ControllerError("Duplicate page identity or path")
            ids.add(page.id)
            paths.add(page.assetPath)


def validate_manifest_json(data: object) -> ChapterManifest:
    if not isinstance(data, dict) or data.get("schemaVersion") != 1 or data.get("mediaKind") != "manga":
        raise ControllerError("Unsupported manifest schema")
    raw_pages = data.get("pages")
    if not isinstance(raw_pages, list):
        raise ControllerError("Manifest pages must be an array")
    try:
        pages = tuple(Page(**p) for p in raw_pages)
        result = ChapterManifest(chapterId=data["chapterId"], pages=pages)
        result.validate()
    except (TypeError, KeyError) as exc:
        raise ControllerError("Malformed manifest fields") from exc
    return result
