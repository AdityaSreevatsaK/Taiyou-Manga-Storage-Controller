"""Synthetic contract tests for ReLIFE GitHub artefact acceptance."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from taiyou_manga.domain import ControllerError
from taiyou_manga.images import check_bytes
from taiyou_manga.relife_intake import audit_relife_artifacts


def _image() -> bytes:
    buffer = io.BytesIO()
    with Image.new("RGB", (40, 50), (20, 50, 90)) as picture:
        picture.save(buffer, format="PNG")
    return buffer.getvalue()


class ReLIFEIntakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.zip_path = self.directory / "ReLIFE-Original-Quality-Ch1-20.zip"

    def fixture(
        self,
        *,
        numbers: tuple[str, ...] = ("1", "19.5"),
        corrupted_cbz_checksum: bool = False,
        omit_rights: bool = False,
        with_companions: bool = False,
        bad_tracker: bool = False,
    ) -> bytes:
        image = _image()
        checked = check_bytes(image, "001.png")
        page = {
            "name": "001.png",
            "sha256": checked.checksum,
            "width": checked.width,
            "height": checked.height,
            "mimeType": checked.mime,
            "byteSize": checked.byte_size,
        }
        records = []
        embedded: dict[str, bytes] = {}
        for number in numbers:
            filename = f"ReLIFE - Vol. 1 Ch. {number}.cbz"
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as cbz:
                cbz.writestr("001.png", image)
                cbz.writestr("ComicInfo.xml", b"<ComicInfo><Number>1</Number></ComicInfo>")
            payload = output.getvalue()
            embedded["ReLIFE/" + filename] = payload
            checksum = hashlib.sha256(payload).hexdigest()
            if corrupted_cbz_checksum:
                checksum = "0" * 64
            records.append(
                {
                    "name": filename,
                    "relativePath": filename,
                    "sha256": checksum,
                    "archiveByteSize": len(payload),
                    "verifiedPageCount": 1,
                    "pages": [page],
                }
            )
        audit = {
            "schemaVersion": 1,
            "title": "ReLIFE",
            "sourceTitleUrl": "https://mangadex.org/title/6e3553b9-ddb5-4d37-b7a3-99998044774e/relife",
            "sourceEdition": "MangaDex English uploader-provided images; not publisher masters",
            "requestedQuality": "source-original-not-data-saver",
            "completeSeriesVerified": False,
            "requestedRange": {"start": 1, "end": 20},
            "verifiedArchives": len(records),
            "verifiedPages": len(records),
            "archives": records,
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as outer:
            outer.writestr("relife_quality_audit.json", json.dumps(audit))
            if not omit_rights:
                outer.writestr("SOURCE_AND_RIGHTS.txt", "No permission asserted")
            if with_companions:
                cover = io.BytesIO()
                with Image.new("RGB", (32, 40), (30, 70, 120)) as picture:
                    picture.save(cover, format="JPEG")
                outer.writestr("ReLIFE/cover.jpg", cover.getvalue())
                header = b"malformed tracker" if bad_tracker else b"SQLite format 3\\x00"
                outer.writestr("ReLIFE/download.db", header + bytes(120))
            for name, payload in embedded.items():
                outer.writestr(name, payload)
        self.zip_path.write_bytes(buffer.getvalue())
        return buffer.getvalue()

    def test_metadata_and_content_preflight_are_read_only(self) -> None:
        original = self.fixture()
        plan = audit_relife_artifacts(self.directory, require_complete=False)
        self.assertEqual(plan["status"], "metadata-only")
        self.assertEqual(plan["cbzArchives"], 2)
        self.assertEqual(plan["numberedChapters"], 1)
        self.assertEqual(plan["extras"], ["19.5"])
        self.assertIs(plan["readyForUpload"], False)
        verified = audit_relife_artifacts(self.directory, deep_verify=True, require_complete=False)
        self.assertEqual(verified["status"], "verified-content")
        self.assertEqual(verified["pages"], 2)
        self.assertEqual(self.zip_path.read_bytes(), original)
        self.assertEqual(list(self.directory.iterdir()), [self.zip_path])

    def test_mangadex_cover_and_tracker_are_checked_and_ignored(self) -> None:
        original = self.fixture(with_companions=True)
        report = audit_relife_artifacts(self.directory, deep_verify=True, require_complete=False)
        self.assertEqual(report["cbzArchives"], 2)
        self.assertEqual(report["pages"], 2)
        self.assertEqual(self.zip_path.read_bytes(), original)

    def test_fake_tracker_is_rejected(self) -> None:
        self.fixture(with_companions=True, bad_tracker=True)
        with self.assertRaisesRegex(ControllerError, "tracker signature"):
            audit_relife_artifacts(self.directory, require_complete=False)

    def test_file_checksum_tampering_detected_only_in_deep_verification(self) -> None:
        self.fixture(corrupted_cbz_checksum=True)
        audit_relife_artifacts(self.directory, require_complete=False)
        with self.assertRaisesRegex(ControllerError, "CBZ SHA-256"):
            audit_relife_artifacts(self.directory, deep_verify=True, require_complete=False)

    def test_missing_rights_provenance_file_is_rejected(self) -> None:
        self.fixture(omit_rights=True)
        with self.assertRaisesRegex(ControllerError, "Unexpected or missing files"):
            audit_relife_artifacts(self.directory, require_complete=False)

    def test_duplicate_chapter_in_one_batch_is_rejected(self) -> None:
        self.fixture(numbers=("1", "01"))
        with self.assertRaisesRegex(ControllerError, "Duplicate chapter identity"):
            audit_relife_artifacts(self.directory, require_complete=False)

    def test_missing_numbered_chapters_cannot_be_considered_complete(self) -> None:
        self.fixture()
        with self.assertRaisesRegex(ControllerError, "incomplete"):
            audit_relife_artifacts(self.directory, require_complete=True)

    def test_unknown_extra_chapter_fails_closed(self) -> None:
        self.fixture(numbers=("1", "20.5"))
        with self.assertRaisesRegex(ControllerError, "Unexpected ReLIFE decimal"):
            audit_relife_artifacts(self.directory, require_complete=False)

    def test_unsafe_archive_path_is_rejected(self) -> None:
        self.fixture()
        source = self.zip_path.read_bytes()
        with zipfile.ZipFile(io.BytesIO(source)) as old:
            audit = old.read("relife_quality_audit.json")
            rights = old.read("SOURCE_AND_RIGHTS.txt")
            cbz_name = "ReLIFE - Vol. 1 Ch. 1.cbz"
            cbz = old.read("ReLIFE/" + cbz_name)
        with zipfile.ZipFile(self.zip_path, "w") as damaged:
            damaged.writestr("relife_quality_audit.json", audit)
            damaged.writestr("SOURCE_AND_RIGHTS.txt", rights)
            damaged.writestr("../" + cbz_name, cbz)
        with self.assertRaisesRegex(ControllerError, "ZIP traversal"):
            audit_relife_artifacts(self.directory, require_complete=False)


if __name__ == "__main__":
    unittest.main()
