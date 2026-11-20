"""Synthetic regression tests for <chapter>_<page> flat manga import."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from taiyou_manga.builder import load_json, verify_bundle
from taiyou_manga.cli import parser, run
from taiyou_manga.domain import ControllerError
from taiyou_manga.flat_import import flat_preview, inspect_flat
from taiyou_manga.hf_bulk import load_bundles, prepare_plan


class FlatImageImportTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.source = self.root / "flat-originals"
        self.source.mkdir()
        self.identity = self.root / "private" / "ids.json"
        self.rights = self.root / "private" / "rights.json"
        self.rights.parent.mkdir()
        self.rights.write_text(
            json.dumps({
                "schemaVersion": 1,
                "sourceType": "owned",
                "title": "Sample Manga",
                "permissionEvidence": "Synthetic fixture artwork created for testing",
                "attribution": "Synthetic test artwork",
                "recordedAt": "2026-11-20T00:00:00Z",
            }), encoding="utf-8"
        )

    def add_page(self, chapter: int, page: int, colour: tuple[int, int, int]) -> Path:
        location = self.source / f"{chapter}_{page}.jpg"
        Image.new("RGB", (36, 64), colour).save(location, format="JPEG")
        return location

    def seed(self) -> None:
        self.add_page(2, 0, (180, 10, 10))
        self.add_page(1, 10, (10, 40, 250))
        for page in range(10):
            self.add_page(1, page, (page * 18, 55, 15))

    def build(self, output: Path, manga_key: str = "sample-identity") -> dict[str, object]:
        args = parser().parse_args([
            "flat-build", "--source", str(self.source), "--series-title", "Sample Manga",
            "--rights-json", str(self.rights), "--state-file", str(self.identity),
            "--output", str(output), "--manga-key", manga_key,
        ])
        return run(args)

    def test_preview_numeric_order_and_chapter_counts(self) -> None:
        self.seed()
        report = flat_preview(self.source, "Sample Manga")
        self.assertEqual(report["chapters"], 2)
        self.assertEqual(report["pages"], 12)
        self.assertEqual(report["chapterNumbers"], [1, 2])
        self.assertEqual(report["firstPageOfEachChapter"], {"1": 0, "2": 0})
        self.assertEqual(report["remoteWrites"], 0)
        scanned = inspect_flat(self.source)
        self.assertEqual(scanned.chapters[0].files[-1].name, "1_10.jpg")
        self.assertEqual(scanned.chapters[0].files[2].name, "1_2.jpg")
        self.assertFalse(self.identity.exists())

    def test_build_canonical_bundle_and_safe_cloud_preview(self) -> None:
        self.seed()
        target = self.root / "bundles" / "sample"
        result = self.build(target)
        self.assertEqual(result["series"], 1)
        self.assertEqual(result["chapters"], 2)
        self.assertEqual(result["pages"], 12)
        self.assertEqual(verify_bundle(target)["pages"], 12)
        catalogue = load_json(target / "catalogue.json")
        self.assertEqual(len(catalogue), 1)
        self.assertEqual(catalogue[0]["title"], "Sample Manga")
        self.assertEqual([ch["label"] for ch in catalogue[0]["chapters"]], [
            "Chapter 1", "Chapter 2",
        ])
        self.assertEqual([ch["sequence"] for ch in catalogue[0]["chapters"]], [0, 1])
        manifest = load_json(target / "manifests" / f"{catalogue[0]['chapters'][0]['id']}.json")
        self.assertEqual(len(manifest["pages"]), 11)
        self.assertEqual(
            manifest["pages"][2]["sha256"],
            hashlib.sha256((self.source / "1_2.jpg").read_bytes()).hexdigest(),
        )
        self.assertEqual(
            manifest["pages"][10]["sha256"],
            hashlib.sha256((self.source / "1_10.jpg").read_bytes()).hexdigest(),
        )
        self.assertTrue(all(
            page["assetPath"].startswith(
                f"manga/{catalogue[0]['id']}/{catalogue[0]['chapters'][0]['id']}/pg_"
            ) for page in manifest["pages"]
        ))
        self.assertTrue(all(p["mimeType"] == "image/jpeg" for p in manifest["pages"]))
        self.assertTrue(all(p["sha256"] for p in manifest["pages"]))
        self.assertEqual(len(load_bundles(target)), 1)
        plan, _ = prepare_plan(target, "a" * 40, {"data/library.json"}, b"{}", [])
        self.assertEqual(plan["status"], "ready")
        self.assertEqual(plan["new"], 1)
        self.assertEqual(plan["deleteOperations"], 0)

    def test_stable_opaque_ids_on_rebuild_and_source_move_with_key(self) -> None:
        self.seed()
        first_path = self.root / "bundles" / "first"
        self.build(first_path)
        original = load_json(first_path / "catalogue.json")[0]
        original_chapter = original["chapters"][0]["id"]
        original_page = load_json(first_path / "manifests" / f"{original_chapter}.json")["pages"][0]["id"]
        moved = self.root / "renamed-source-location"
        self.source.rename(moved)
        self.source = moved
        second_path = self.root / "bundles" / "second"
        self.build(second_path)
        another = load_json(second_path / "catalogue.json")[0]
        self.assertEqual(original["id"], another["id"])
        self.assertEqual(original["chapters"], another["chapters"])
        newer_page = load_json(second_path / "manifests" / f"{original_chapter}.json")["pages"][0]["id"]
        self.assertEqual(original_page, newer_page)

    def test_missing_or_duplicate_page_numbers_fail_closed(self) -> None:
        self.add_page(1, 0, (0, 50, 90))
        self.add_page(1, 2, (0, 55, 90))
        with self.assertRaisesRegex(ControllerError, "missing page"):
            inspect_flat(self.source)
        (self.source / "1_2.jpg").rename(self.source / "01_0.jpg")
        with self.assertRaisesRegex(ControllerError, "Duplicate"):
            inspect_flat(self.source)

    def test_chapter_gap_is_visible_but_not_silently_filled(self) -> None:
        self.add_page(1, 1, (0, 50, 90))
        self.add_page(3, 1, (50, 60, 70))
        plan = flat_preview(self.source, "Sample Manga")
        self.assertEqual(plan["missingChapterNumbers"], [2])
        self.assertEqual(plan["chapters"], 2)

    def test_invalid_names_and_image_bytes_are_rejected(self) -> None:
        (self.source / "README.txt").write_text("Don't silently include unknown files", encoding="utf-8")
        self.add_page(1, 0, (20, 30, 40))
        with self.assertRaisesRegex(ControllerError, "Unexpected image name"):
            inspect_flat(self.source)
        (self.source / "README.txt").unlink()
        (self.source / "1_0.jpg").write_bytes(b"not actually a JPEG")
        with self.assertRaises(ControllerError):
            self.build(self.root / "bundles" / "corrupt")
        self.assertFalse(self.identity.exists())

    def test_upload_never_overwrites_existing_same_title(self) -> None:
        self.add_page(1, 0, (5, 5, 5))
        target = self.root / "bundles" / "one"
        self.build(target)
        record = load_json(target / "catalogue.json")[0]
        plan, _ = prepare_plan(target, "b" * 40, {"data/library.json"}, b"{}", [
            {**record, "id": "mng_eeeeeeeeeeee"},
        ])
        self.assertEqual(plan["status"], "conflict")


if __name__ == "__main__":
    unittest.main()
