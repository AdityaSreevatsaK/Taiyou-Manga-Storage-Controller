"""Synthetic offline tests for ReLIFE candidate staging and provisional IDs."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from taiyou_manga.builder import load_json, verify_bundle
from taiyou_manga.domain import ControllerError
from taiyou_manga.images import check_bytes
from taiyou_manga.relife_stage import stage_relife_candidate


class ReLIFEStagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        self.bundle = self.root / "bundle"
        self.registry = self.root / "private-ids.json"

    def source(self, chapters: tuple[str, ...] = ("1", "19.5")) -> None:
        buffer = io.BytesIO()
        with Image.new("RGB", (32, 40), (20, 60, 90)) as image:
            image.save(buffer, format="PNG")
        png = buffer.getvalue()
        meta = check_bytes(png, "001.png")
        page = {
            "name": "001.png",
            "sha256": meta.checksum,
            "width": meta.width,
            "height": meta.height,
            "mimeType": meta.mime,
            "byteSize": meta.byte_size,
        }
        reports = []
        cbzs = {}
        for ch in chapters:
            name = f"ReLIFE - Vol. 1 Ch. {ch}.cbz"
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w") as cbz:
                cbz.writestr("001.png", png)
                cbz.writestr("ComicInfo.xml", "<ComicInfo/>")
            content = archive.getvalue()
            cbzs["ReLIFE/" + name] = content
            reports.append(
                {
                    "name": name,
                    "relativePath": name,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "archiveByteSize": len(content),
                    "verifiedPageCount": 1,
                    "pages": [page],
                }
            )
        audit = {
            "schemaVersion": 1,
            "title": "ReLIFE",
            "requestedQuality": "source-original-not-data-saver",
            "completeSeriesVerified": False,
            "requestedRange": {"start": 1, "end": 20},
            "verifiedArchives": len(reports),
            "verifiedPages": len(reports),
            "archives": reports,
        }
        with zipfile.ZipFile(self.artifacts / "ReLIFE-Original-Quality-Ch1-20.zip", "w") as outer:
            outer.writestr("relife_quality_audit.json", json.dumps(audit))
            outer.writestr("SOURCE_AND_RIGHTS.txt", "Not an upload permission statement")
            for name, content in cbzs.items():
                outer.writestr(name, content)

    def test_stages_one_sorted_series_with_provisional_ids(self) -> None:
        self.source()
        result = stage_relife_candidate(self.artifacts, self.bundle, self.registry, require_complete=False)
        self.assertEqual(result["status"], "verified-provisional-candidate")
        self.assertEqual((result["series"], result["chapters"], result["pages"]), (1, 2, 2))
        self.assertIs(result["readyForUpload"], False)
        self.assertFalse(result["persistentIdsAssigned"])
        self.assertEqual(verify_bundle(self.bundle)["pages"], 2)
        catalogue = load_json(self.bundle / "catalogue.json")
        self.assertEqual([entry["title"] for entry in catalogue], ["ReLIFE"])
        self.assertEqual(
            [chapter["label"] for chapter in catalogue[0]["chapters"]],
            ["Chapter 1", "Chapter 19.5"],
        )
        self.assertEqual(catalogue[0]["direction"], "vertical")
        self.assertEqual(len(load_json(self.registry)), 3)

    def test_stable_identity_staging_uses_reproducible_ids(self) -> None:
        self.source()
        result = stage_relife_candidate(
            self.artifacts, self.bundle, self.registry, require_complete=False, stable_ids=True
        )
        self.assertTrue(result["persistentIdsAssigned"])
        first = load_json(self.registry)
        catalogue = load_json(self.bundle / "catalogue.json")
        self.assertEqual(first["series:ReLIFE"], catalogue[0]["id"])
        self.assertEqual(
            first["chapter:ReLIFE/Chapter 19.5.cbz"], catalogue[0]["chapters"][1]["id"]
        )

    def test_preexisting_bundle_or_registry_refused_without_changes(self) -> None:
        self.source()
        self.bundle.mkdir()
        with self.assertRaisesRegex(ControllerError, "output already exists"):
            stage_relife_candidate(self.artifacts, self.bundle, self.registry, require_complete=False)
        self.bundle.rmdir()
        self.registry.write_text("existing", encoding="utf-8")
        with self.assertRaisesRegex(ControllerError, "registry destination already exists"):
            stage_relife_candidate(self.artifacts, self.bundle, self.registry, require_complete=False)
        self.assertFalse(self.bundle.exists())

    def test_incomplete_source_fails_closed_in_default_production_mode(self) -> None:
        self.source()
        with self.assertRaisesRegex(ControllerError, "ReLIFE run incomplete"):
            stage_relife_candidate(self.artifacts, self.bundle, self.registry)
        self.assertFalse(self.bundle.exists())
        self.assertFalse(self.registry.exists())


if __name__ == "__main__":
    unittest.main()
