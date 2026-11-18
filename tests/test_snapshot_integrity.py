"""Regression tests for complete mock snapshots and strict bundle allowlists."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from taiyou_manga.builder import build, load_json, verify_bundle, write_json
from taiyou_manga.demo import create_demo
from taiyou_manga.domain import ControllerError
from taiyou_manga.storage import MockStorage


class SnapshotIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "fixtures"
        self.bundle = self.root / "bundle"
        create_demo(self.source)
        build(
            self.source,
            self.bundle,
            self.root / "ids.json",
            rights_path=self.root / "fixtures-rights-example.json",
        )
        self.mock = MockStorage(self.root / "mock")

    def commit(self) -> str:
        revision = self.mock.apply(self.bundle, None, approve=True)
        self.assertEqual(self.mock.preview(self.bundle).status, "no-op")
        return revision

    def test_catalogue_changes_are_never_silently_noop(self) -> None:
        revision = self.commit()
        catalogue = self.bundle / "catalogue.json"
        entries = load_json(catalogue)
        entries[0]["title"] = "Renamed, same pages"
        write_json(catalogue, entries)
        self.assertEqual(verify_bundle(self.bundle)["pages"], 12)
        plan = self.mock.preview(self.bundle)
        self.assertEqual(plan.revision, revision)
        self.assertEqual(plan.status, "conflict")
        self.assertEqual(plan.new_pages, 0)
        self.assertGreaterEqual(plan.metadata_conflicts, 1)
        self.assertGreaterEqual(plan.as_json()["metadataConflicts"], 1)
        with self.assertRaises(ControllerError):
            self.mock.apply(self.bundle, revision, approve=True)

    def test_reordered_manifest_is_conflict_even_with_identical_pages(self) -> None:
        revision = self.commit()
        manifest_path = next((self.bundle / "manifests").glob("*.json"))
        manifest = load_json(manifest_path)
        manifest["pages"].reverse()
        write_json(manifest_path, manifest)
        # Individual assets remain valid, but pageIndex/pageId progress depends on the order.
        self.assertEqual(verify_bundle(self.bundle)["pages"], 12)
        self.assertEqual(self.mock.preview(self.bundle).status, "conflict")
        self.assertEqual(self.mock._head(), revision)

    def test_rights_evidence_changes_are_conflicts(self) -> None:
        self.commit()
        path = self.bundle / "rights.json"
        evidence = load_json(path)
        evidence["attribution"] = "Updated private attribution"
        write_json(path, evidence)
        self.assertEqual(verify_bundle(self.bundle)["rightsDeclared"], True)
        self.assertGreaterEqual(self.mock.preview(self.bundle).metadata_conflicts, 1)

    def test_corrupt_or_missing_committed_snapshot_rejected(self) -> None:
        revision = self.commit()
        snapshot_catalogue = self.mock.root / "snapshots" / revision / "catalogue.json"
        entries = load_json(snapshot_catalogue)
        entries[0]["title"] = "Tampered snapshot"
        write_json(snapshot_catalogue, entries)
        with self.assertRaisesRegex(ControllerError, "snapshot bytes changed"):
            self.mock.preview(self.bundle)

    def test_missing_snapshot_and_malformed_head_rejected(self) -> None:
        write_json(self.mock.root / "head.json", {"revision": "a" * 64})
        with self.assertRaises(ControllerError):
            self.mock.preview(self.bundle)
        write_json(self.mock.root / "head.json", {"revision": "../escape"})
        with self.assertRaisesRegex(ControllerError, "head corrupt"):
            self.mock.preview(self.bundle)

    def test_orphan_manifest_and_untracked_file_rejected(self) -> None:
        orphan = self.bundle / "manifests" / "untracked.json"
        write_json(orphan, {"untracked": True})
        with self.assertRaisesRegex(ControllerError, "Unexpected, missing or orphaned"):
            verify_bundle(self.bundle)
        orphan.unlink()
        (self.bundle / "private-notes.txt").write_text("not for backups", encoding="utf-8")
        with self.assertRaisesRegex(ControllerError, "Unexpected, missing or orphaned"):
            verify_bundle(self.bundle)

    def test_malformed_catalogue_returns_controlled_error(self) -> None:
        catalogue = self.bundle / "catalogue.json"
        entries = load_json(catalogue)
        entries[0].pop("chapters")
        write_json(catalogue, entries)
        with self.assertRaisesRegex(ControllerError, "Malformed bundle metadata"):
            verify_bundle(self.bundle)


if __name__ == "__main__":
    unittest.main()
