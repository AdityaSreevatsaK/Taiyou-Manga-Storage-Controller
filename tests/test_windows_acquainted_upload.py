"""Synthetic regression tests for the owner-initiated Windows Acquainted upload helper."""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from scripts.upload_acquainted_windows import (
    NAME,
    discover,
    extract_pages,
    find_cover,
    metadata_candidate,
    read_metadata,
    source_rights,
)
from taiyou_manga.builder import build, load_json, verify_bundle
from taiyou_manga.metadata import load_candidates


class WindowsUploadScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        scope = tempfile.TemporaryDirectory()
        self.addCleanup(scope.cleanup)
        self.root = Path(scope.name)
        self.chapter_zip = self.root / "all-chapters.zip"
        self.meta_zip = self.root / "metadata.zip"
        self.cover = self.root / "separate-cover.jpg"
        Image.new("RGB", (50, 75), (123, 12, 90)).save(self.cover, format="JPEG")
        image = self.root / "source.jpg"
        Image.new("RGB", (30, 45), (20, 50, 100)).save(image, format="JPEG")
        with zipfile.ZipFile(self.chapter_zip, "w") as archive:
            archive.write(image, "nested/1_10.jpg")
            for page in range(10):
                archive.write(image, f"nested/1_{page}.jpg")
            archive.write(image, "nested/2_0.jpg")
        metadata = {
            "title": NAME,
            "aliases": ["Alternative title"],
            "creators": ["Perilla", "PAMBA"],
            "creatorRoles": [
                {"name": "Perilla", "role": "author"},
                {"name": "PAMBA", "role": "artist"},
            ],
            "genreTags": ["Romance"],
            "descriptiveTags": ["Webtoon"],
            "publicationStatus": "completed",
            "synopsis": "Synthetic test only.",
            "references": {
                "officialEnglishPublisher": "https://tapas.io/series/acquainted-encounter-spin-off/info"
            },
            "publicationCredits": "Perilla and PAMBA",
        }
        candidates = {
            "candidates": [
                {
                    "title": NAME,
                    "source": {
                        "provider": "tapas",
                        "sourceId": "acquainted-encounter-spin-off",
                        "sourceUrl": metadata["references"]["officialEnglishPublisher"],
                        "retrievedAt": "2026-11-20T17:00:00Z",
                    },
                    "metadata": {
                        "synopsis": metadata["synopsis"],
                        "publicationStatus": "completed",
                        "tags": ["Romance", "Webtoon"],
                    },
                }
            ],
        }
        with zipfile.ZipFile(self.meta_zip, "w") as archive:
            archive.writestr("metadata/metaddata.json", json.dumps(metadata))
            archive.writestr("metadata/candidates.json", json.dumps(candidates))
        self.rights = self.root / "original-rights.json"
        self.rights.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "sourceType": "original",
                    "title": NAME,
                    "permissionEvidence": "Test authors created and own these synthetic image fixtures",
                    "attribution": "Synthetic fixture creator",
                    "recordedAt": "2026-11-20T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )

    def test_identifies_exact_archives_cover_and_canonical_metadata(self) -> None:
        images, meta = discover(self.root, None, None)
        self.assertEqual((images, meta), (self.chapter_zip, self.meta_zip))
        original, source = read_metadata(meta)
        self.assertEqual(original["title"], NAME)
        self.assertEqual(find_cover(self.root, None, images, meta), self.cover)
        work = self.root / ".acquainted-private-import"
        work.mkdir()
        extracted = work / "pages"
        self.assertEqual(extract_pages(images, extracted), 12)
        self.assertEqual(extract_pages(images, extracted), 12)
        rights = source_rights(work, NAME, str(self.rights))
        bundle = work / "bundle"
        summary = build(
            extracted,
            bundle,
            work / "ids.json",
            NAME,
            "vertical",
            rights,
            allow_duplicate_pages=True,
            flat_numbered=True,
            manga_key="acquainted-encounter-spin-off",
        )
        self.assertEqual(summary["chapters"], 2)
        self.assertEqual(summary["pages"], 12)
        self.assertEqual(verify_bundle(bundle)["pages"], 12)
        item = load_json(bundle / "catalogue.json")[0]
        candidate_file = metadata_candidate(original, source, item["id"], self.cover, work)
        parsed, _ = load_candidates(candidate_file)
        self.assertEqual(parsed[0]["mangaId"], item["id"])
        self.assertEqual(parsed[0]["metadata"]["creators"], ["Perilla", "PAMBA"])
        self.assertEqual(parsed[0]["metadata"]["publicationStatus"], "completed")
        self.assertEqual(parsed[0]["metadata"]["tags"], ["Romance", "Webtoon"])
        self.assertIn("cover", parsed[0]["metadata"])
        self.assertEqual(item["direction"], "vertical")

    def test_does_not_extract_unsafe_zip_member(self) -> None:
        with zipfile.ZipFile(self.chapter_zip, "w") as archive:
            archive.writestr("../1_0.jpg", b"bad")
        with self.assertRaisesRegex(RuntimeError, "Unsafe ZIP member"):
            discover(self.root, None, None)

    def test_rejects_same_page_number_even_if_numeric_spelling_differs(self) -> None:
        with zipfile.ZipFile(self.chapter_zip, "w") as archive:
            archive.writestr("1_0.jpg", b"page")
            archive.writestr("01_0.jpg", b"other")
        with self.assertRaisesRegex(RuntimeError, "Repeated chapter and page"):
            extract_pages(self.chapter_zip, self.root / "pages")


if __name__ == "__main__":
    unittest.main()
