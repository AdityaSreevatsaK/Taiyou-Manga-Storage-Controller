"""Synthetic image-corruption and non-destructive repair acceptance tests."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from scripts.acquainted_image_repair import inspect_and_prepare
from taiyou_manga.domain import ControllerError
from taiyou_manga.images import check_bytes


def jpeg(colour: tuple[int, int, int]) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (80, 110), colour).save(output, format="JPEG")
    return output.getvalue()


class DamagedMangaImageTests(unittest.TestCase):
    def setUp(self) -> None:
        scoped = tempfile.TemporaryDirectory()
        self.addCleanup(scoped.cleanup)
        self.work = Path(scoped.name)
        self.pages = self.work / "pages"
        self.pages.mkdir()
        self.original = jpeg((100, 90, 80))
        self.good = self.pages / "7_8.jpg"
        self.good.write_bytes(self.original)

    def test_clean_images_need_no_repair_or_content_change(self) -> None:
        self.assertEqual(inspect_and_prepare(self.pages, self.work), self.pages)
        self.assertEqual(self.good.read_bytes(), self.original)
        report = json.loads((self.work / "image-diagnostics.json").read_text())
        self.assertEqual(report["invalidImageCount"], 0)
        self.assertFalse(report["requiresVisualReview"])

    def test_missing_jpeg_eoi_is_staged_for_visual_review_only(self) -> None:
        damaged = self.original[:-2]
        file = self.pages / "7_9.jpg"
        file.write_bytes(damaged)
        with self.assertRaisesRegex(ControllerError, "--use-reviewed-repairs"):
            inspect_and_prepare(self.pages, self.work)
        report = json.loads((self.work / "image-diagnostics.json").read_text())
        self.assertEqual(report["invalidImageCount"], 1)
        self.assertEqual(report["recoveredCandidateCount"], 1)
        self.assertEqual(report["issues"][0]["file"], "7_9.jpg")
        preview = self.work / "repaired-candidates" / "7_9.jpg"
        self.assertTrue(preview.is_file())
        self.assertEqual(file.read_bytes(), damaged)
        check_bytes(preview.read_bytes(), preview.name)

        selected = inspect_and_prepare(self.pages, self.work, use_reviewed_repairs=True)
        self.assertNotEqual(selected, self.pages)
        self.assertEqual({f.name for f in selected.iterdir()}, {"7_8.jpg", "7_9.jpg"})
        self.assertEqual((selected / "7_8.jpg").read_bytes(), self.original)
        check_bytes((selected / "7_9.jpg").read_bytes(), "7_9.jpg")
        self.assertEqual(file.read_bytes(), damaged)
        self.assertEqual(inspect_and_prepare(self.pages, self.work, use_reviewed_repairs=True), selected)

    def test_arbitrary_corruption_is_not_mistaken_for_recoverable_jpeg(self) -> None:
        file = self.pages / "7_9.jpg"
        file.write_bytes(b"not an image and not recoverable")
        with self.assertRaisesRegex(ControllerError, "not recoverable"):
            inspect_and_prepare(self.pages, self.work, use_reviewed_repairs=True)
        report = json.loads((self.work / "image-diagnostics.json").read_text())
        self.assertEqual(report["recoveredCandidateCount"], 0)
        self.assertIn("7_9.jpg", report["issues"][0]["file"])
        self.assertFalse((self.work / "validated-pages").exists())

    def test_repaired_copy_is_never_silently_replaced(self) -> None:
        file = self.pages / "7_9.jpg"
        file.write_bytes(self.original[:-2])
        with self.assertRaises(ControllerError):
            inspect_and_prepare(self.pages, self.work)
        target = self.work / "repaired-candidates" / "7_9.jpg"
        target.write_bytes(b"tampered")
        with self.assertRaisesRegex(ControllerError, "Existing repaired JPEG changed"):
            inspect_and_prepare(self.pages, self.work, use_reviewed_repairs=True)

    def test_report_mentions_real_decoder_error(self) -> None:
        file = self.pages / "7_9.jpg"
        file.write_bytes(b"\xff\xd8garbled JPEG data")
        with self.assertRaises(ControllerError):
            inspect_and_prepare(self.pages, self.work)
        report = json.loads((self.work / "image-diagnostics.json").read_text())
        self.assertIn("Invalid or corrupt image", report["issues"][0]["validationError"])


if __name__ == "__main__":
    unittest.main()
