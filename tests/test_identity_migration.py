"""Synthetic, offline tests for safe chapter and series identity migration."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from taiyou_manga.builder import _registry_lock, build, load_json, write_json
from taiyou_manga.demo import create_demo
from taiyou_manga.domain import ControllerError
from taiyou_manga.identity_migration import migrate_identities


class IdentityMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.bundle = self.root / "bundle-before"
        self.registry = self.root / "private" / "ids.json"
        self.mapping = self.root / "private" / "mapping.json"
        self.backup = self.root / "private" / "ids-backup.json"
        create_demo(self.source)
        build(self.source, self.bundle, self.registry)
        self.original = self.registry.read_bytes()

    def make_moves(self, moves: list[dict[str, str]]) -> None:
        write_json(self.mapping, {"schemaVersion": 1, "moves": moves})

    def series_rename(self) -> list[dict[str, str]]:
        return [
            {"kind": "series", "from": "Signal Garden", "to": "Signal Archive"},
            {
                "kind": "chapter",
                "from": "Signal Garden/Volume 1/Chapter 1",
                "to": "Signal Archive/Volume 1/Chapter 1",
            },
            {
                "kind": "chapter",
                "from": "Signal Garden/Volume 1/Chapter 2",
                "to": "Signal Archive/Volume 1/Chapter 2",
            },
        ]

    def test_preview_does_not_mutate_registry_or_create_backup(self) -> None:
        self.make_moves(self.series_rename())
        plan = migrate_identities(self.registry, self.mapping)
        self.assertEqual(plan["status"], "preview-only")
        self.assertEqual(plan["currentRevision"], hashlib.sha256(self.original).hexdigest())
        self.assertEqual(len(plan["moves"]), 3)
        self.assertEqual(self.registry.read_bytes(), self.original)
        self.assertFalse(self.backup.exists())
        self.assertFalse(self.registry.with_name("ids.json.lock").exists())

    def test_rename_preserves_series_chapter_and_page_ids(self) -> None:
        original_catalogue = load_json(self.bundle / "catalogue.json")
        original_entries = {entry["id"]: entry for entry in original_catalogue}
        original_manifests = {
            chapter["id"]: load_json(self.bundle / "manifests" / (chapter["id"] + ".json"))
            for entry in original_catalogue
            for chapter in entry["chapters"]
        }
        (self.source / "Signal Garden").rename(self.source / "Signal Archive")
        self.make_moves(self.series_rename())
        revision = migrate_identities(self.registry, self.mapping)["currentRevision"]
        result = migrate_identities(
            self.registry,
            self.mapping,
            approve=True,
            expected_revision=revision,
            backup_file=self.backup,
        )
        self.assertEqual(result["status"], "applied")
        self.assertEqual(self.backup.read_bytes(), self.original)
        self.assertFalse(self.registry.with_name("ids.json.lock").exists())

        new_bundle = self.root / "bundle-after"
        build(self.source, new_bundle, self.registry)
        new_catalogue = load_json(new_bundle / "catalogue.json")
        self.assertEqual(
            {entry["id"] for entry in original_catalogue},
            {entry["id"] for entry in new_catalogue},
        )
        for entry in new_catalogue:
            old = original_entries[entry["id"]]
            self.assertEqual(
                [ch["id"] for ch in entry["chapters"]],
                [ch["id"] for ch in old["chapters"]],
            )
            for chapter in entry["chapters"]:
                new = load_json(new_bundle / "manifests" / (chapter["id"] + ".json"))
                previous = original_manifests[chapter["id"]]
                self.assertEqual(new["pages"], previous["pages"])

    def test_stale_revision_blocks_apply_without_backup(self) -> None:
        self.make_moves(self.series_rename())
        with self.assertRaisesRegex(ControllerError, "Stale identity"):
            migrate_identities(
                self.registry,
                self.mapping,
                approve=True,
                expected_revision="0" * 64,
                backup_file=self.backup,
            )
        self.assertEqual(self.registry.read_bytes(), self.original)
        self.assertFalse(self.backup.exists())

    def test_apply_requires_backup_and_exact_revision(self) -> None:
        self.make_moves(self.series_rename())
        revision = migrate_identities(self.registry, self.mapping)["currentRevision"]
        with self.assertRaisesRegex(ControllerError, "exact previewed"):
            migrate_identities(self.registry, self.mapping, approve=True, backup_file=self.backup)
        with self.assertRaisesRegex(ControllerError, "unused local backup"):
            migrate_identities(self.registry, self.mapping, approve=True, expected_revision=revision)
        self.assertEqual(self.registry.read_bytes(), self.original)

    def test_series_rename_must_include_every_chapter(self) -> None:
        self.make_moves(self.series_rename()[:2])
        with self.assertRaisesRegex(ControllerError, "every chapter"):
            migrate_identities(self.registry, self.mapping)
        self.assertEqual(self.registry.read_bytes(), self.original)

    def test_existing_destination_refuses_overwrite(self) -> None:
        self.make_moves([{"kind": "series", "from": "Signal Garden", "to": "Moonlit Courier"}])
        with self.assertRaisesRegex(ControllerError, "destination already exists"):
            migrate_identities(self.registry, self.mapping)

    def test_case_only_source_collisions_fail(self) -> None:
        self.make_moves(
            [
                {
                    "kind": "chapter",
                    "from": "Signal Garden/Volume 1/Chapter 1",
                    "to": "Moonlit Courier/Volume 1/CHAPTER 1",
                }
            ]
        )
        with self.assertRaisesRegex(ControllerError, "case-insensitive source collisions"):
            migrate_identities(self.registry, self.mapping)

    def test_duplicate_source_and_invalid_paths_fail(self) -> None:
        entries = self.series_rename()
        self.make_moves([entries[0], entries[0]])
        with self.assertRaisesRegex(ControllerError, "Duplicate migration source"):
            migrate_identities(self.registry, self.mapping)
        self.make_moves([{"kind": "chapter", "from": "../escape", "to": "Somewhere"}])
        with self.assertRaisesRegex(ControllerError, "Invalid source path"):
            migrate_identities(self.registry, self.mapping)
        self.make_moves([{"kind": "unknown", "from": "A", "to": "B"}])
        with self.assertRaisesRegex(ControllerError, "kind must"):
            migrate_identities(self.registry, self.mapping)

    def test_existing_backup_is_not_overwritten(self) -> None:
        self.make_moves(self.series_rename())
        self.backup.write_bytes(b"important-existing-backup")
        revision = migrate_identities(self.registry, self.mapping)["currentRevision"]
        with self.assertRaisesRegex(ControllerError, "already exists"):
            migrate_identities(
                self.registry,
                self.mapping,
                approve=True,
                expected_revision=revision,
                backup_file=self.backup,
            )
        self.assertEqual(self.backup.read_bytes(), b"important-existing-backup")
        self.assertEqual(self.registry.read_bytes(), self.original)

    def test_failed_registry_swap_preserves_old_registry_and_backup(self) -> None:
        self.make_moves(self.series_rename())
        revision = migrate_identities(self.registry, self.mapping)["currentRevision"]
        with patch("taiyou_manga.identity_migration.Path.replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                migrate_identities(
                    self.registry,
                    self.mapping,
                    approve=True,
                    expected_revision=revision,
                    backup_file=self.backup,
                )
        self.assertEqual(self.registry.read_bytes(), self.original)
        self.assertEqual(self.backup.read_bytes(), self.original)
        self.assertEqual(list(self.registry.parent.glob(".manga-remap-*.tmp")), [])

    def test_concurrent_import_blocks_migration(self) -> None:
        self.make_moves(self.series_rename())
        with _registry_lock(self.registry):
            with self.assertRaisesRegex(ControllerError, "registry is locked"):
                migrate_identities(self.registry, self.mapping)
        self.assertEqual(self.registry.read_bytes(), self.original)

    def test_inverse_mapping_can_restore_original_id_registry(self) -> None:
        changes = self.series_rename()
        self.make_moves(changes)
        revision = migrate_identities(self.registry, self.mapping)["currentRevision"]
        migrated = migrate_identities(
            self.registry,
            self.mapping,
            approve=True,
            expected_revision=revision,
            backup_file=self.backup,
        )
        inverse = [{"kind": c["kind"], "from": c["to"], "to": c["from"]} for c in changes]
        self.make_moves(inverse)
        rollback = self.root / "private" / "before-rollback.json"
        migrate_identities(
            self.registry,
            self.mapping,
            approve=True,
            expected_revision=migrated["currentRevision"],
            backup_file=rollback,
        )
        self.assertEqual(self.registry.read_bytes(), self.original)
        self.assertEqual(rollback.exists(), True)


if __name__ == "__main__":
    unittest.main()
