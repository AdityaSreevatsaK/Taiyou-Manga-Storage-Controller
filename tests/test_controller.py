"""Offline-only synthetic fixture tests with no Hugging Face credentials."""

from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from taiyou_manga.backup import create_backup, restore_backup, verify_backup
from taiyou_manga.builder import build, load_json, verify_bundle, write_json
from taiyou_manga.cli import main
from taiyou_manga.demo import create_demo
from taiyou_manga.domain import ControllerError, validate_manifest_json
from taiyou_manga.images import Limits, check_bytes
from taiyou_manga.sources import natural_key, read_archive
from taiyou_manga.storage import HuggingFaceReadOnly, MockStorage, RemoteWritesDisabled, RevisionConflict


def png(colour: tuple[int, int, int] = (10, 20, 30), size: tuple[int, int] = (32, 40)) -> bytes:
    data = io.BytesIO()
    Image.new("RGB", size, colour).save(data, format="PNG")
    return data.getvalue()


class ImageAndArchiveTests(unittest.TestCase):
    def test_valid_and_mismatched_mime(self) -> None:
        image = check_bytes(png(), "1.png")
        self.assertEqual(image.mime, "image/png")
        with self.assertRaises(ControllerError):
            check_bytes(png(), "1.jpg")

    def test_invalid_corrupt_and_size_limits(self) -> None:
        for content in (b"not an image", png()[:50]):
            with self.subTest(content=content[:10]), self.assertRaises(ControllerError):
                check_bytes(content, "image.png")
        with self.assertRaises(ControllerError):
            check_bytes(png(), "1.png", Limits(max_image_bytes=30))
        with self.assertRaises(ControllerError):
            check_bytes(png(), "1.png", Limits(max_dimension=20))

    def test_natural_sort(self) -> None:
        self.assertEqual(sorted(["10.png", "2.png", "1.png"], key=natural_key), ["1.png", "2.png", "10.png"])

    def test_archive_accepts_cbz(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            archive = Path(root) / "chapter.cbz"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("10.png", png((5, 6, 7)))
                zf.writestr("2.png", png((1, 2, 3)))
            self.assertEqual([p.name for p in read_archive(archive)], ["2.png", "10.png"])

    def test_archive_traversal_absolute_backslashes_and_duplicate_members(self) -> None:
        for names in (
            ["../evil.png"],
            ["/evil.png"],
            ["C:/evil.png"],
            ["dir\\evil.png"],
            ["1.png", "1.png"],
            ["1.png", "1.PNG"],
            ["%2e%2e.png"],
        ):
            with self.subTest(names=names), tempfile.TemporaryDirectory() as root:
                archive = Path(root) / "bad.cbz"
                with zipfile.ZipFile(archive, "w") as zf:
                    for name in names:
                        zf.writestr(name, png())
                with self.assertRaises(ControllerError):
                    read_archive(archive)

    def test_archive_excess_ratio_symlink_and_nonimage(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            archive = Path(root) / "bad.cbz"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("huge.png", b"0" * 200_000)
            with self.assertRaises(ControllerError):
                read_archive(archive)
            with zipfile.ZipFile(archive, "w") as zf:
                link = zipfile.ZipInfo("link.png")
                link.create_system = 3
                link.external_attr = 0o120777 << 16
                zf.writestr(link, png())
            with self.assertRaises(ControllerError):
                read_archive(archive)
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("notes.txt", b"secret")
            with self.assertRaises(ControllerError):
                read_archive(archive)

    def test_folder_symlink_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            chapter = base / "ch"
            chapter.mkdir()
            (base / "target.png").write_bytes(png())
            try:
                (chapter / "1.png").symlink_to(base / "target.png")
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks unavailable")
            from taiyou_manga.sources import read_folder

            with self.assertRaises(ControllerError):
                read_folder(chapter, base)


class BundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.demo = self.root / "fixtures"
        self.bundle = self.root / "bundle"
        self.registry = self.root / "state" / "identities.json"
        create_demo(self.demo)

    def make_bundle(self) -> dict[str, object]:
        return build(
            self.demo, self.bundle, self.registry, rights_path=self.root / "fixtures-rights-example.json"
        )

    def test_demo_count_manifest_compatibility_and_integrity(self) -> None:
        stats = self.make_bundle()
        self.assertEqual((stats["series"], stats["chapters"], stats["pages"]), (2, 4, 12))
        self.assertEqual(verify_bundle(self.bundle)["pages"], 12)
        for path in (self.bundle / "manifests").glob("*.json"):
            self.assertEqual(validate_manifest_json(load_json(path)).as_json(), load_json(path))

    def test_title_change_preserves_opaque_ids_and_progress_identity(self) -> None:
        self.make_bundle()
        before = load_json(self.bundle / "catalogue.json")
        before_pages = {
            p["sha256"]: p["id"]
            for m in (self.bundle / "manifests").glob("*.json")
            for p in load_json(m)["pages"]
        }
        before[0]["title"] = "New title (no identity change)"
        write_json(self.bundle / "catalogue.json", before)
        self.assertEqual(verify_bundle(self.bundle)["pages"], 12)
        self.assertEqual(before[0]["id"], load_json(self.bundle / "catalogue.json")[0]["id"])
        after_pages = {
            p["sha256"]: p["id"]
            for m in (self.bundle / "manifests").glob("*.json")
            for p in load_json(m)["pages"]
        }
        self.assertEqual(before_pages, after_pages)

    def test_rerun_identities_preserved(self) -> None:
        self.make_bundle()
        first = load_json(self.bundle / "catalogue.json")
        second = self.root / "second"
        build(self.demo, second, self.registry)
        latter = load_json(second / "catalogue.json")
        self.assertEqual(
            [[c["id"] for c in entry["chapters"]] for entry in first],
            [[c["id"] for c in entry["chapters"]] for entry in latter],
        )
        with self.assertRaises(ControllerError):
            build(self.demo, second, self.registry)

    def test_corrupted_file_cannot_verify(self) -> None:
        self.make_bundle()
        path = next((self.bundle / "assets").rglob("*.png"))
        path.write_bytes(path.read_bytes()[:80])
        with self.assertRaises(ControllerError):
            verify_bundle(self.bundle)

    def test_extra_assets_rejected(self) -> None:
        self.make_bundle()
        (self.bundle / "assets" / "manga" / "bad.png").write_bytes(png())
        with self.assertRaises(ControllerError):
            verify_bundle(self.bundle)

    def test_missing_reordered_page_fails_closed(self) -> None:
        self.make_bundle()
        manifest = next((self.bundle / "manifests").glob("*.json"))
        original = load_json(manifest)
        original["pages"] = list(reversed(original["pages"]))
        write_json(manifest, original)
        # Bundle checksum verification alone is order-independent; page IDs stay paired
        # with pages so the reader's progress pair (pageIndex, pageId) detects this.
        first = original["pages"][0]["id"]
        self.assertNotEqual(first, original["pages"][-1]["id"])
        self.assertEqual(verify_bundle(self.bundle)["pages"], 12)
        original["pages"].pop()
        write_json(manifest, original)
        with self.assertRaises(ControllerError):
            verify_bundle(self.bundle)

    def test_duplicate_page_image_fails(self) -> None:
        chapter = next(self.demo.rglob("Chapter 1"))
        (chapter / "new.png").write_bytes((chapter / "page-001.png").read_bytes())
        with self.assertRaises(ControllerError):
            self.make_bundle()

    def test_schema_invalid_and_missing_remote_identity(self) -> None:
        with self.assertRaises(ControllerError):
            validate_manifest_json({"schemaVersion": 2, "mediaKind": "manga", "chapterId": "x", "pages": []})
        with self.assertRaises(ControllerError):
            HuggingFaceReadOnly("not-a-dataset-id")

    def test_hf_write_disabled(self) -> None:
        with self.assertRaises(RemoteWritesDisabled):
            HuggingFaceReadOnly("owner/private-manga").write("anything")

    def test_mock_preview_idempotence_and_stale_revision(self) -> None:
        self.make_bundle()
        mock = MockStorage(self.root / "local-mock")
        preview = mock.preview(self.bundle)
        self.assertEqual((preview.status, preview.new_pages), ("new", 12))
        with self.assertRaises(ControllerError):
            mock.apply(self.bundle, None, approve=False)
        revision = mock.apply(self.bundle, None, approve=True)
        self.assertEqual(mock.preview(self.bundle).status, "no-op")
        self.assertEqual(mock.apply(self.bundle, revision, approve=True), revision)
        with self.assertRaises(RevisionConflict):
            mock.apply(self.bundle, None, approve=True)

    def test_mock_conflicting_byte_changes(self) -> None:
        self.make_bundle()
        mock = MockStorage(self.root / "local-mock")
        revision = mock.apply(self.bundle, None, approve=True)
        one = next((self.bundle / "manifests").glob("*.json"))
        manifest = load_json(one)
        original = manifest["pages"][0]
        # Supply a different valid image and update checksum and size, keeping asset path.
        other = png((10, 200, 80), (288, 400))
        target = self.bundle / "assets" / original["assetPath"]
        target.write_bytes(other)
        from hashlib import sha256

        original["sha256"] = sha256(other).hexdigest()
        original["byteSize"] = len(other)
        write_json(one, manifest)
        self.assertEqual(mock.preview(self.bundle).status, "conflict")
        with self.assertRaises(ControllerError):
            mock.apply(self.bundle, revision, approve=True)

    def test_full_backup_restore_and_tamper(self) -> None:
        self.make_bundle()
        archive = self.root / "backup.zip"
        result = create_backup(self.bundle, archive)
        self.assertEqual(result["kind"], "full-media")
        self.assertGreater(verify_backup(archive)["verifiedBytes"], 0)
        restore = self.root / "restored"
        self.assertEqual(restore_backup(archive, restore)["operation"], "preview")
        self.assertFalse(restore.exists())
        self.assertEqual(restore_backup(archive, restore, True)["operation"], "restored")
        self.assertEqual(verify_bundle(restore)["pages"], 12)
        with self.assertRaises(ControllerError):
            restore_backup(archive, restore, True)
        with zipfile.ZipFile(archive, "a") as zf:
            zf.writestr("unexpected.txt", b"evil")
        with self.assertRaises(ControllerError):
            verify_backup(archive)

    def test_backup_zip_traversal(self) -> None:
        archive = self.root / "unsafe.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../evil", b"x")
            zf.writestr("BACKUP_INDEX.json", b"{}")
        with self.assertRaises(ControllerError):
            verify_backup(archive)

    def test_cli_no_live_access(self) -> None:
        self.assertEqual(main(["scan", "--source", str(self.demo)]), 0)
        self.assertEqual(main(["hf-health", "--repo-id", "invalid"]), 2)


if __name__ == "__main__":
    unittest.main()


class MockFaultTests(unittest.TestCase):
    def test_lock_refuses_concurrent_writers(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            storage = MockStorage(Path(root) / "mock")
            with storage._write_lock(), self.assertRaises(RevisionConflict):
                storage.apply(Path(root) / "non-existent-bundle", None, approve=True)

    def test_interrupted_mock_copy_does_not_move_head(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            fixture = base / "fixtures"
            create_demo(fixture)
            bundle = base / "bundle"
            build(fixture, bundle, base / "ids.json")
            storage = MockStorage(base / "mock")
            with patch("taiyou_manga.storage.shutil.copytree", side_effect=OSError("interrupted")):
                with self.assertRaises(OSError):
                    storage.apply(bundle, None, approve=True)
            self.assertIsNone(storage._head())
            self.assertFalse((base / "mock" / "write.lock").exists())
            self.assertEqual(storage.preview(bundle).status, "new")
