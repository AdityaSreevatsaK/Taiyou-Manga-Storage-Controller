"""Bounded, fully decoded image verification using Pillow."""

from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageFile

from .domain import IMAGE_EXTENSIONS, ControllerError

Image.MAX_IMAGE_PIXELS = 70_000_000
ImageFile.LOAD_TRUNCATED_IMAGES = False
FORMAT_MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "AVIF": "image/avif"}


@dataclass(frozen=True)
class Limits:
    max_image_bytes: int = 25_000_000
    max_pixels: int = 70_000_000
    max_dimension: int = 16_000
    max_pages: int = 1_000
    max_archive_bytes: int = 500_000_000
    max_ratio: int = 100


DEFAULT_LIMITS = Limits()


@dataclass(frozen=True)
class CheckedImage:
    checksum: str
    byte_size: int
    width: int
    height: int
    mime: str
    extension: str


def check_bytes(data: bytes, filename: str, limits: Limits = DEFAULT_LIMITS) -> CheckedImage:
    suffix = Path(filename).suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        raise ControllerError(f"Unsupported image extension: {suffix or '(none)'}")
    if not 0 < len(data) <= limits.max_image_bytes:
        raise ControllerError("Image exceeds byte-size limit or is empty")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as probe:
                actual = FORMAT_MIME.get(probe.format or "")
                if actual != IMAGE_EXTENSIONS[suffix]:
                    raise ControllerError("Image signature and extension disagree")
                width, height = probe.size
                if (
                    not 1 <= width <= limits.max_dimension
                    or not 1 <= height <= limits.max_dimension
                    or width * height > limits.max_pixels
                ):
                    raise ControllerError("Image dimension/pixel budget exceeded")
                probe.verify()
            with Image.open(io.BytesIO(data)) as decoded:
                decoded.load()  # full decode catches truncated streams
    except (
        OSError,
        SyntaxError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        if isinstance(exc, ControllerError):
            raise
        raise ControllerError(f"Invalid or corrupt image: {filename}") from exc
    return CheckedImage(hashlib.sha256(data).hexdigest(), len(data), width, height, actual, suffix)


def read_limited(path: Path, maximum: int) -> bytes:
    with path.open("rb") as handle:
        data = handle.read(maximum + 1)
    if len(data) > maximum:
        raise ControllerError(f"File too large: {path.name}")
    return data
