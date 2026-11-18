"""Generate original synthetic images, never copyrighted manga."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from .builder import write_json
from .domain import ControllerError


def create_demo(root: Path) -> dict[str, object]:
    if root.exists():
        raise ControllerError("Demo destination exists; refusing overwrite")
    groups = [("Signal Garden", "Volume 1", "Chapter 1", 3),
              ("Signal Garden", "Volume 1", "Chapter 2", 4),
              ("Moonlit Courier", "Volume 1", "Chapter 1", 2),
              ("Moonlit Courier", "Volume 2", "Chapter 2", 3)]
    pages = 0
    for group_index, (series, volume, chapter, count) in enumerate(groups):
        folder = root / series / volume / chapter
        folder.mkdir(parents=True, exist_ok=True)
        for i in range(count):
            with Image.new("RGB", (288, 400), (236, 225, 203)) as image:
                draw = ImageDraw.Draw(image)
                shade = 60 + group_index * 20
                draw.rounded_rectangle((28, 28, 258, 365), radius=18, outline=(shade, 60, 90), width=4)
                draw.ellipse((50 + i * 10, 70, 140 + i * 10, 160), fill=(shade, 130, 160))
                draw.text((50, 200), f"ORIGINAL SYNTHETIC PAGE {i + 1}", fill=(30, 30, 30))
                draw.text((50, 240), series[:20], fill=(30, 30, 30))
                with BytesIO() as buffer:
                    image.save(buffer, format="PNG")
                    (folder / f"page-{i + 1:03}.png").write_bytes(buffer.getvalue())
                pages += 1
    write_json(root.parent / (root.name + "-rights-example.json"), {
        "schemaVersion": 1, "sourceType": "original", "title": "Synthetic controller examples",
        "permissionEvidence": "Original synthetic images created for controller testing",
        "attribution": "Taiyou Manga Controller fixtures", "recordedAt": "2026-11-18T00:00:00Z"})
    return {"series": 2, "chapters": 4, "pages": pages, "source": str(root)}
