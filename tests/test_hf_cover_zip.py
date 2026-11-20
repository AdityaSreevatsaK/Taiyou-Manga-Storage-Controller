"""Synthetic ZIP adapter tests; no MangaDex image or Hugging Face connection."""

from __future__ import annotations

import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from taiyou_manga.domain import ControllerError
from taiyou_manga.hf_cli import parser
from taiyou_manga.hf_cover_zip import unpack_verified


class CoverZipTests(unittest.TestCase):
    def setUp(self) -> None:
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.root = Path(root.name)
        self.input_zip = self.root / "original-covers.zip"
        self.destination = self.root / "private-extraction"
        self.destination.mkdir()

    def test_valid_private_source_cover_archive(self) -> None:
        with zipfile.ZipFile(self.input_zip, "w") as archive:
            archive.writestr("metadata.json", "{}")
            archive.writestr("covers/source.jpg", b"synthetic-not-a-real-image")
        candidate = unpack_verified(self.input_zip, self.destination)
        self.assertEqual(candidate.name, "metadata.json")
        self.assertEqual(
            (self.destination / "covers" / "source.jpg").read_bytes(),
            b"synthetic-not-a-real-image",
        )
        # Actual image bytes are subsequently validated by hf_metadata.
        args = parser().parse_args([
            "upload-covers", "--zip", str(self.input_zip),
            "--plan-file", str(self.root / "preview.json"),
        ])
        self.assertFalse(args.apply)
        self.assertFalse(args.approve)

    def test_path_traversal_is_rejected(self) -> None:
        with zipfile.ZipFile(self.input_zip, "w") as archive:
            archive.writestr("metadata.json", "{}")
            archive.writestr("covers/../../secret.jpg", b"dangerous")
        with self.assertRaisesRegex(ControllerError, "Unsafe"):
            unpack_verified(self.input_zip, self.destination)
        self.assertFalse((self.root / "secret.jpg").exists())

    def test_duplicate_or_missing_cover_is_blocked(self) -> None:
        with zipfile.ZipFile(self.input_zip, "w") as archive:
            archive.writestr("metadata.json", "{}")
        with self.assertRaisesRegex(ControllerError, "at least one"):
            unpack_verified(self.input_zip, self.destination)

    def test_symlinked_cover_member_rejected(self) -> None:
        with zipfile.ZipFile(self.input_zip, "w") as archive:
            archive.writestr("metadata.json", "{}")
            member = zipfile.ZipInfo("covers/suspicious.jpg")
            member.create_system = 3
            member.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(member, b"../../outside.jpg")
        with self.assertRaisesRegex(ControllerError, "Unsafe"):
            unpack_verified(self.input_zip, self.destination)


if __name__ == "__main__":
    unittest.main()
