"""Synthetic original-image, extra-chapter dedup and permanent ID integration."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from taiyou_manga.builder import load_json, verify_bundle
from taiyou_manga.domain import ControllerError
from taiyou_manga.images import check_bytes
from taiyou_manga.selected_stage import stage_selected_manga, stable_registry
from taiyou_manga.selected_titles import TITLES, SelectedTitle


class SelectedMangaStageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        self.bundle = self.root / "bundle"
        self.registry = self.root / "ids.json"
        self.title = SelectedTitle(
            "test-selected", "Example Manga", 999, 21, 23,
            "Manga-example-Original-Ch", "00000000-0000-0000-0000-000000000000",
        )

    def files(self, *, omit_final: bool = False, damaged: bool = False) -> None:
        image_io = io.BytesIO()
        with Image.new("RGB", (32, 40), (20, 30, 80)) as image:
            image.save(image_io, "PNG")
        page_data = image_io.getvalue()
        page_meta = check_bytes(page_data, "001.png")
        for start, end in self.title.ranges:
            records = []
            members = {}
            for number in [0, *range(start, end + 1)]:
                if number == end and omit_final and end == 21:
                    continue
                chapter = f"Ch. {number} Oneshot" if number == 0 else f"Vol. 1 Ch. {number}"
                name = chapter + ".cbz"
                chapter_io = io.BytesIO()
                with zipfile.ZipFile(chapter_io, "w") as cbz:
                    cbz.writestr("001.png", page_data)
                payload = chapter_io.getvalue()
                members[f"test-selected-{start}-{end}/chapters/{name}"] = payload
                records.append(
                    {
                        "name": name,
                        "relativePath": name,
                        "mainChapterLabel": number if number else None,
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "archiveByteSize": len(payload),
                        "verifiedPageCount": 1,
                        "pages": [
                            {
                                "name": "001.png", "sha256": page_meta.checksum,
                                "mimeType": page_meta.mime, "width": page_meta.width,
                                "height": page_meta.height, "byteSize": page_meta.byte_size,
                            }
                        ],
                    }
                )
            batch = {
                "schemaVersion": 1, "slug": self.title.slug, "title": self.title.name,
                "sourceTitleUrl": f"https://mangadex.org/title/{self.title.source_id}",
                "requestedRange": {"start": start, "end": end},
                "qualityRequested": "original-upload-not-data-saver",
                "completeSeriesVerified": False,
                "archives": records,
                "verifiedArchives": len(records), "verifiedPages": len(records),
                "verifiedMainChapters": end - start + 1,
                "verifiedMainChapterNumbers": list(range(start, end + 1)),
            }
            outer = self.artifacts / f"{self.title.prefix}{start}-{end}.zip"
            with zipfile.ZipFile(outer, "w") as zf:
                root = f"test-selected-{start}-{end}"
                zf.writestr(f"{root}/quality_audit.json", json.dumps(batch))
                zf.writestr(f"{root}/SOURCE_AND_RIGHTS.txt", "No independent legal assurance")
                for path, payload in members.items():
                    zf.writestr(path, payload)
            if damaged and start == 21:
                with zipfile.ZipFile(outer, "a") as zf:
                    zf.writestr("unexpected.exe", b"unsafe")

    def test_two_batches_with_repeated_zero_bonus_keep_one_stable_chapter(self) -> None:
        self.files()
        with patch.dict(TITLES, {self.title.slug: self.title}):
            result = stage_selected_manga(
                self.title.slug, self.artifacts, self.bundle, self.registry
            )
        self.assertEqual(result["status"], "verified-selected-candidate")
        self.assertEqual(result["duplicateBonusArchivesSkipped"], 1)
        self.assertEqual(result["mainChapters"], 21)
        self.assertEqual(result["uniqueChapters"], 22)
        self.assertEqual(result["verifiedPages"], 22)
        self.assertEqual(result["auditedSourcePages"], 23)
        self.assertEqual(verify_bundle(self.bundle)["chapters"], 22)
        entry = load_json(self.bundle / "catalogue.json")[0]
        self.assertEqual(entry["title"], "Example Manga")
        self.assertEqual(entry["chapters"][0]["label"], "Chapter 0")
        self.assertEqual(entry["chapters"][-1]["label"], "Chapter 21")
        self.assertEqual(load_json(self.registry), stable_registry(self.title, {"0"} | {str(n) for n in range(1, 22)}))

    def test_missing_numbered_main_chapter_refused(self) -> None:
        self.files(omit_final=True)
        with patch.dict(TITLES, {self.title.slug: self.title}):
            with self.assertRaises(ControllerError):
                stage_selected_manga(self.title.slug, self.artifacts, self.bundle, self.registry)
        self.assertFalse(self.bundle.exists())

    def test_unexpected_outer_source_file_refused(self) -> None:
        self.files(damaged=True)
        with patch.dict(TITLES, {self.title.slug: self.title}):
            with self.assertRaisesRegex(ControllerError, "Unexpected non-chapter"):
                stage_selected_manga(self.title.slug, self.artifacts, self.bundle, self.registry)
        self.assertFalse(self.bundle.exists())

    def test_source_run_mapping_is_fixed(self) -> None:
        self.assertEqual(len(TITLES), 4)
        self.assertEqual(TITLES["maid-sama"].main_chapters, 85)
        self.assertEqual(TITLES["last-game"].main_chapters, 56)
        self.assertEqual(TITLES["love-so-life"].main_chapters, 106)
        self.assertEqual(TITLES["onizuka-sawarida"].main_chapters, 49)


if __name__ == "__main__":
    unittest.main()
