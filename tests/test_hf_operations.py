"""Offline regression tests for Novel-style manga management workflows."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from taiyou_manga.domain import ControllerError
from taiyou_manga.hf_bulk import _conflicts, load_bundles, prepare_plan
from taiyou_manga.hf_cli import parser
from taiyou_manga.hf_extra import local_download_cleanup
from taiyou_manga.hf_manage import (
    delete_apply,
    list_entries,
    normalized_title,
    quick_integrity,
    title_conflicts,
)


def record(manga_id: str = "mng_aaaaaaaaaaaa", title: str = "Demo Manga") -> dict:
    chapter = "ch_bbbbbbbbbbbb"
    return {
        "kind": "manga",
        "id": manga_id,
        "title": title,
        "aliases": [],
        "creators": [],
        "tags": [],
        "publicationStatus": "unknown",
        "direction": "vertical",
        "chapters": [{"id": chapter, "label": "Chapter 1", "sequence": 0, "pageCount": 1}],
    }


class ManagementPureTests(unittest.TestCase):
    def test_listing_and_title_alias_conflict(self) -> None:
        first = record()
        second = record("mng_cccccccccccc", "DÉMO-MANGA")
        first["aliases"] = ["Demo Manga Deluxe"]
        self.assertEqual(normalized_title("Demo-Manga"), normalized_title("Demo_Manga"))
        rows = list_entries([second, first])
        self.assertEqual(len(rows), 2)
        conflicts = title_conflicts([first, second])
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["count"], 2)

    def test_integrity_reports_missing_covers_and_pages(self) -> None:
        item = record()
        item["cover"] = {
            "assetPath": f"covers/{item['id']}.jpg",
            "mimeType": "image/jpeg",
            "width": 450,
            "height": 650,
            "byteSize": 1024,
            "sha256": "a" * 64,
        }
        report = quick_integrity([item], {"data/library.json"})
        self.assertFalse(report["complete"])
        self.assertEqual(report["missingManifests"], ["ch_bbbbbbbbbbbb"])
        self.assertEqual(report["missingCovers"], [item["id"]])
        self.assertEqual(report["missingPageSeries"], [item["id"]])
        self.assertEqual(report["chapters"], 1)
        self.assertEqual(report["pages"], 1)
        full = {
            "data/library.json",
            "data/manifests/ch_bbbbbbbbbbbb.json",
            f"data/manga/{item['id']}/ch_bbbbbbbbbbbb/pg_cccccccccccc.jpg",
            f"data/covers/{item['id']}.jpg",
        }
        self.assertTrue(quick_integrity([item], full)["complete"])
        other = "mng_eeeeeeeeeeee"
        full.add(f"data/manga/{other}/ch_bbbbbbbbbbbb/pg_cccccccccccc.jpg")
        self.assertIn(other, quick_integrity([item], full)["orphanMediaSeries"])

    def test_cli_has_expected_novel_parity_commands_and_safe_deletion(self) -> None:
        commands = parser()._subparsers._group_actions[0].choices
        for name in [
            "bulk-upload",
            "download",
            "list",
            "conflicts",
            "verify",
            "sync",
            "backup-catalogue",
            "restore",
            "delete",
            "covers",
            "chapters",
            "compare-retriever",
            "health",
            "metadata-report",
            "metadata",
            "cleanup",
            "menu",
        ]:
            self.assertIn(name, commands)
        self.assertNotIn("clear-all", commands)
        args = parser().parse_args(
            [
                "delete",
                "--manga-id",
                "mng_aaaaaaaaaaaa",
                "--plan-file",
                "reports/delist.json",
            ]
        )
        self.assertFalse(args.apply)
        self.assertFalse(args.approve)
        self.assertEqual(args.confirm_title, "")


class BulkCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.item = record()
        chapter_id = "ch_bbbbbbbbbbbb"
        page_id = "pg_cccccccccccc"
        self.blob = b"valid-synthetic-media-only"
        image_path = self.root / "assets" / "manga" / self.item["id"] / chapter_id
        image_path.mkdir(parents=True)
        (image_path / f"{page_id}.png").write_bytes(self.blob)
        self.manifest = {
            "schemaVersion": 1,
            "mediaKind": "manga",
            "chapterId": chapter_id,
            "pages": [
                {
                    "id": page_id,
                    "assetPath": f"manga/{self.item['id']}/{chapter_id}/{page_id}.png",
                    "mimeType": "image/png",
                    "width": 10,
                    "height": 10,
                    "byteSize": len(self.blob),
                    "sha256": hashlib.sha256(self.blob).hexdigest(),
                }
            ],
        }
        (self.root / "manifests").mkdir()
        (self.root / "manifests" / f"{chapter_id}.json").write_text(
            json.dumps(self.manifest), encoding="utf-8"
        )
        (self.root / "catalogue.json").write_text(json.dumps([self.item]), encoding="utf-8")
        (self.root / "rights.json").write_text(
            json.dumps({"title": "Demo Manga", "evidence": "Synthetic permission"}),
            encoding="utf-8",
        )
        self.verified = {"series": 1, "pages": 1, "chapters": 1, "rightsDeclared": True}

    def test_candidates_are_stable_and_source_paths_are_safe(self) -> None:
        with patch("taiyou_manga.hf_bulk.verify_bundle", return_value=self.verified):
            bundles = load_bundles(self.root)
        self.assertEqual(len(bundles), 1)
        self.assertEqual(bundles[0].entry["id"], self.item["id"])
        self.assertEqual(len(bundles[0].files), 2)
        self.assertEqual(sum(f.size for f in bundles[0].files if f.remote.endswith(".png")), len(self.blob))
        entries = [self.item]
        remote_paths = {file.remote for file in bundles[0].files}
        self.assertEqual(_conflicts(bundles[0], entries, remote_paths)[0], "already-listed")
        self.assertEqual(_conflicts(bundles[0], entries, set())[0], "conflict")

    def test_bulk_preview_rejects_collision_without_mutation(self) -> None:
        with patch("taiyou_manga.hf_bulk.verify_bundle", return_value=self.verified):
            doc, records = prepare_plan(self.root, "a" * 40, set(), b"{}", [])
            self.assertEqual(doc["status"], "ready")
            self.assertEqual(doc["new"], 1)
            self.assertEqual(doc["deleteOperations"], 0)
            self.assertEqual(doc["items"][0]["pages"], 1)
            self.assertEqual(len(records), 1)
            rival = record("mng_ffffffffffff", "Demo_Manga")
            conflict, _ = prepare_plan(self.root, "a" * 40, set(), b"{}", [rival])
            self.assertEqual(conflict["status"], "conflict")
            rival["title"] = "Different manga"
            rival["aliases"] = ["Demo Manga"]
            alias_conflict, _ = prepare_plan(self.root, "a" * 40, set(), b"{}", [rival])
            self.assertEqual(alias_conflict["status"], "conflict")

    def test_bulk_rejects_missing_source_permission_or_changed_page(self) -> None:
        (self.root / "rights.json").unlink()
        with patch(
            "taiyou_manga.hf_bulk.verify_bundle",
            return_value={
                **self.verified,
                "rightsDeclared": False,
            },
        ):
            with self.assertRaisesRegex(ControllerError, "rights.json"):
                load_bundles(self.root)
        self.root.joinpath("rights.json").write_text(json.dumps({"title": "Demo Manga"}), encoding="utf-8")
        (
            self.root / "assets" / "manga" / self.item["id"] / "ch_bbbbbbbbbbbb" / "pg_cccccccccccc.png"
        ).write_bytes(b"tampered")
        with patch("taiyou_manga.hf_bulk.verify_bundle", return_value=self.verified):
            with self.assertRaisesRegex(ControllerError, "bytes disagree"):
                load_bundles(self.root)


class DestructiveGuardsTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.item = record()
        self.plan = self.root / "delist.json"

    def test_delete_does_not_commit_without_matching_preapproved_plan(self) -> None:
        fake = SimpleNamespace(dataset_info=lambda *args, **kw: SimpleNamespace(sha="a" * 40))
        contents = json.dumps({"schemaVersion": 1, "mediaKind": "manga", "entries": [self.item]}).encode()
        snap = (fake, "a" * 40, {"data/library.json"}, contents, [self.item])
        with patch("taiyou_manga.hf_manage.snapshot", return_value=snap):
            with self.assertRaisesRegex(ControllerError, "preview"):
                delete_apply("token", self.item["id"], self.plan, self.item["title"])
            self.plan.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ControllerError, "confirmation"):
                delete_apply("token", self.item["id"], self.plan, "Wrong title")
            with self.assertRaisesRegex(ControllerError, "changed"):
                delete_apply("token", self.item["id"], self.plan, self.item["title"])

    def test_cleanup_only_removes_aged_local_part_files(self) -> None:
        old = self.root / "old.part"
        old.write_bytes(b"incomplete")
        archive = self.root / "mng_aaaaaaaaaaaa.zip"
        archive.write_bytes(b"protected")
        recently = self.root / "recent.part"
        recently.write_bytes(b"recent")
        stamp = time.time() - 10 * 86400
        os.utime(old, (stamp, stamp))
        report = local_download_cleanup(self.root, self.plan, older_than_days=7)
        self.assertEqual(report["temporaryFiles"], 1)
        self.assertTrue(old.exists())
        with self.assertRaisesRegex(ControllerError, "Exact confirmation"):
            local_download_cleanup(self.root, self.plan, older_than_days=7, apply=True)
        local_download_cleanup(
            self.root,
            self.plan,
            older_than_days=7,
            apply=True,
            confirm="DELETE OLD LOCAL TEMP FILES",
        )
        self.assertFalse(old.exists())
        self.assertTrue(archive.exists())
        self.assertTrue(recently.exists())


if __name__ == "__main__":
    unittest.main()
