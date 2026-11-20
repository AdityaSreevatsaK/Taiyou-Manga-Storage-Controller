"""Synthetic tests for the canonical HF layout and strictly non-destructive migration plan."""

from __future__ import annotations

import unittest

from taiyou_manga.domain import ControllerError
from taiyou_manga.hf_layout import (
    CANONICAL_CATALOGUE,
    canonical_library,
    legacy_migration_preview,
    validate_library,
)


class CanonicalMangaLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sid = "mng_aaaaaaaaaaaa"
        self.cid = "ch_bbbbbbbbbbbb"
        self.pid = "pg_cccccccccccc"
        self.entry = {
            "kind": "manga",
            "id": self.sid,
            "title": "ReLIFE",
            "aliases": [],
            "creators": [],
            "tags": [],
            "publicationStatus": "unknown",
            "direction": "vertical",
            "chapters": [{"id": self.cid, "label": "Chapter 1", "sequence": 0, "pageCount": 1}],
        }
        self.image = f"manga/{self.sid}/{self.cid}/{self.pid}.png"
        self.manifest = {
            "schemaVersion": 1,
            "mediaKind": "manga",
            "chapterId": self.cid,
            "pages": [
                {
                    "id": self.pid,
                    "assetPath": self.image,
                    "mimeType": "image/png",
                    "width": 600,
                    "height": 800,
                    "byteSize": 1234,
                    "sha256": "a" * 64,
                }
            ],
        }
        self.paths = {
            "catalogue.json",
            f"manifests/{self.cid}.json",
            f"assets/{self.image}",
            "control/relife-identities.json",
            "ingest/relife-v1/complete.json",
        }
        self.manifests = {f"manifests/{self.cid}.json": self.manifest}

    def test_canonical_envelope_is_exact_reader_schema(self) -> None:
        document = canonical_library([self.entry])
        self.assertEqual(set(document), {"schemaVersion", "mediaKind", "entries"})
        self.assertEqual(document["schemaVersion"], 1)
        self.assertEqual(document["mediaKind"], "manga")
        self.assertEqual(validate_library(document), [self.entry])
        with self.assertRaisesRegex(ControllerError, "envelope"):
            validate_library([self.entry])

    def test_preview_preserves_all_ids_and_original_media_bytes(self) -> None:
        expected = legacy_migration_preview([self.entry], self.paths, self.manifests, "a" * 40)
        self.assertEqual(expected["canonicalPath"], CANONICAL_CATALOGUE)
        self.assertEqual((expected["series"], expected["chapters"], expected["pages"]), (1, 1, 1))
        self.assertEqual(expected["filesToCopyWithoutDeletingLegacy"], 2)
        self.assertFalse(expected["remoteWritesEnabled"])
        self.assertTrue(expected["requiresFullBackup"])
        self.assertEqual(
            expected,
            legacy_migration_preview([self.entry], self.paths, self.manifests, "a" * 40),
        )

    def test_missing_image_or_manifest_refused(self) -> None:
        with self.assertRaisesRegex(ControllerError, "Missing or invalid legacy image"):
            legacy_migration_preview(
                [self.entry],
                self.paths - {f"assets/{self.image}"},
                self.manifests,
                "a" * 40,
            )
        with self.assertRaisesRegex(ControllerError, "Missing legacy chapter manifest"):
            legacy_migration_preview(
                [self.entry],
                self.paths - {f"manifests/{self.cid}.json"},
                self.manifests,
                "a" * 40,
            )

    def test_reject_unknown_existing_canonical_data(self) -> None:
        with self.assertRaisesRegex(ControllerError, "Existing canonical"):
            legacy_migration_preview(
                [self.entry],
                self.paths | {"data/manga/mng_other/file"},
                self.manifests,
                "a" * 40,
            )

    def test_reject_any_id_or_manifest_relabelling(self) -> None:
        other = {**self.entry, "id": "mng_dddddddddddd"}
        with self.assertRaisesRegex(ControllerError, "Legacy page does not belong"):
            legacy_migration_preview([other], self.paths, self.manifests, "a" * 40)
        broken = {
            **self.manifest,
            "pages": [{**self.manifest["pages"][0], "sha256": "bad"}],
        }
        with self.assertRaises(ControllerError):
            legacy_migration_preview(
                [self.entry],
                self.paths,
                {f"manifests/{self.cid}.json": broken},
                "a" * 40,
            )

    def test_refuses_unreferenced_legacy_images_and_unsupported_version(self) -> None:
        with self.assertRaisesRegex(ControllerError, "Unreferenced legacy media"):
            legacy_migration_preview(
                [self.entry],
                self.paths | {f"assets/manga/{self.sid}/{self.cid}/pg_dddddddddddd.webp"},
                self.manifests,
                "a" * 40,
            )
        with self.assertRaisesRegex(ControllerError, "Unsupported"):
            validate_library({"schemaVersion": 2, "mediaKind": "manga", "entries": [self.entry]})


if __name__ == "__main__":
    unittest.main()
