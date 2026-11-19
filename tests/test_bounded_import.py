"""Bounded manga imports must be safe on large or malformed collections."""

from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from taiyou_manga.builder import build, load_json, verify_bundle
from taiyou_manga.cli import main
from taiyou_manga.demo import create_demo
from taiyou_manga.domain import ControllerError
from taiyou_manga.images import Limits
from taiyou_manga.sources import discover, read_archive, read_folder


def original_png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (32, 40), (20, 30, 40)).save(output, format="PNG")
    return output.getvalue()


class BoundedImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.bundle = self.root / "bundle"
        self.registry = self.root / "ids.json"
        create_demo(self.source)

    def test_all_chapters_still_build_with_stable_counts(self) -> None:
        result = build(self.source, self.bundle, self.registry)
        self.assertEqual((result["series"], result["chapters"], result["pages"]), (2, 4, 12))
        self.assertEqual(verify_bundle(self.bundle)["pages"], 12)
        catalogue = load_json(self.bundle / "catalogue.json")
        self.assertEqual(sum(len(entry["chapters"]) for entry in catalogue), 4)

    def test_aggregate_page_quota_applies_to_scan_and_import(self) -> None:
        tiny = Limits(max_total_import_bytes=100)
        with self.assertRaisesRegex(ControllerError, "Total image bytes"):
            list(discover(self.source, tiny))
        with self.assertRaisesRegex(ControllerError, "Total image bytes"):
            build(self.source, self.bundle, self.registry, limits=tiny)
        self.assertFalse(self.bundle.exists())
        self.assertFalse(self.registry.exists())

    def test_total_chapter_quota_blocks_partial_publication(self) -> None:
        with self.assertRaisesRegex(ControllerError, "Total chapter count"):
            build(self.source, self.bundle, self.registry, limits=Limits(max_chapters=2))
        self.assertFalse(self.bundle.exists())
        self.assertFalse(self.registry.exists())

    def test_folder_aggregate_quota_matches_archive_safety(self) -> None:
        folder = next(path for path in self.source.rglob("Chapter 1") if path.is_dir())
        with self.assertRaisesRegex(ControllerError, "Chapter folder total size"):
            read_folder(folder, self.source, Limits(max_archive_bytes=100))

    def test_nested_directory_depth_quota_blocks_publication(self) -> None:
        with self.assertRaisesRegex(ControllerError, "directory nesting exceeds depth quota"):
            build(self.source, self.bundle, self.registry, limits=Limits(max_source_depth=2))
        self.assertFalse(self.bundle.exists())
        self.assertFalse(self.registry.exists())

    def test_source_tree_entry_quota_prevents_large_scans(self) -> None:
        with self.assertRaisesRegex(ControllerError, "source tree exceeds entry quota"):
            list(discover(self.source, Limits(max_source_entries=3)))
        with self.assertRaisesRegex(ControllerError, "source tree exceeds entry quota"):
            build(self.source, self.bundle, self.registry, limits=Limits(max_source_entries=3))
        self.assertFalse(self.bundle.exists())
        self.assertFalse(self.registry.exists())

    def test_minimum_directory_depth_can_be_allowed(self) -> None:
        result = build(self.source, self.bundle, self.registry, limits=Limits(max_source_depth=3))
        self.assertEqual(result["chapters"], 4)
        self.assertEqual(verify_bundle(self.bundle)["pages"], 12)

    def test_cli_rejects_unbounded_traversal_options(self) -> None:
        self.assertEqual(
            main(["scan", "--source", str(self.source), "--max-source-depth", "13"]), 2
        )
        self.assertEqual(
            main(["scan", "--source", str(self.source), "--max-source-entries", "0"]), 2
        )

    def test_standard_cbz_directory_entries_are_accepted(self) -> None:
        archive = self.root / "nested.cbz"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("Chapter/", b"")
            zf.writestr("Chapter/001.png", original_png())
        pages = read_archive(archive)
        self.assertEqual([page.name for page in pages], ["Chapter/001.png"])

    def test_nested_zip_traversal_directories_still_rejected(self) -> None:
        archive = self.root / "bad.cbz"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../outside/", b"")
            zf.writestr("001.png", original_png())
        with self.assertRaises(ControllerError):
            read_archive(archive)

    def test_archive_compressed_size_quota(self) -> None:
        archive = self.root / "big.cbz"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("001.png", original_png())
        with self.assertRaisesRegex(ControllerError, "compressed size"):
            read_archive(archive, Limits(max_archive_bytes=50))

    def test_invalid_cli_limits_fail_with_actionable_errors(self) -> None:
        self.assertEqual(main(["scan", "--source", str(self.source), "--max-total-mb", "0"]), 2)
        self.assertEqual(
            main(
                [
                    "manifest",
                    "--source",
                    str(self.source),
                    "--output",
                    str(self.bundle),
                    "--max-chapters",
                    "10001",
                ]
            ),
            2,
        )
        self.assertFalse(self.bundle.exists())

    def test_build_writes_first_manifest_before_requesting_second_chapter(self) -> None:
        first, second = list(discover(self.source))[:2]

        def observed_discovery(*_args: object) -> object:
            yield first
            staged = list(self.root.glob(".manga-stage-*"))
            self.assertEqual(len(staged), 1)
            self.assertEqual(len(list((staged[0] / "manifests").glob("*.json"))), 1)
            yield second

        with patch("taiyou_manga.builder.discover", side_effect=observed_discovery):
            result = build(self.source, self.bundle, self.registry)
        self.assertEqual(result["chapters"], 2)
        self.assertEqual(verify_bundle(self.bundle)["chapters"], 2)


if __name__ == "__main__":
    unittest.main()
