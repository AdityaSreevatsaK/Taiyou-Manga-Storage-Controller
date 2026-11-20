"""Offline regressions for GitHub-agent private manga staging and ingestion."""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from scripts.github_manga_ingest import _preflight, extract_private_package, parse_event, sha256_file
from scripts.stage_manga_for_github import source_paths, write_package
from taiyou_manga.builder import build, load_json, verify_bundle
from taiyou_manga.domain import ControllerError
from taiyou_manga.hf_layout import canonical_library
from taiyou_manga.metadata import load_candidates

OWNER = "AdityaSreevatsaK"
ISSUE = "Private manga import queue"
TICKET = "a" * 32
REVISION = "b" * 40
FINGERPRINT = "c" * 64


class PrivateGitHubImportTests(unittest.TestCase):
    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name)
        self.source = self.root / "source"
        self.source.mkdir()
        for page in range(3):
            Image.new("RGB", (40, 70), (30 + page * 60, 50, 70)).save(
                self.source / f"1_{page}.jpg", format="JPEG"
            )
        self.rights = self.root / "rights.json"
        self.rights.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "sourceType": "original",
                    "title": "Synthetic Test Manga",
                    "permissionEvidence": "All synthetic page images were created by this automated test",
                    "attribution": "Synthetic fixture",
                    "recordedAt": "2026-11-20T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )
        self.bundle = self.root / "bundle"
        build(
            self.source,
            self.bundle,
            self.root / "ids.json",
            "Synthetic Test Manga",
            "vertical",
            self.rights,
            allow_duplicate_pages=False,
            flat_numbered=True,
            manga_key="synthetic-remote-fixture",
        )
        self.entry = load_json(self.bundle / "catalogue.json")[0]
        self.meta = self.root / "meta"
        (self.meta / "covers").mkdir(parents=True)
        Image.new("RGB", (50, 80), (10, 120, 50)).save(self.meta / "covers" / "synthetic.jpg", format="JPEG")
        candidates = {
            "schemaVersion": 1,
            "mediaKind": "manga-metadata-candidates",
            "candidates": [
                {
                    "mangaId": self.entry["id"],
                    "title": self.entry["title"],
                    "source": {
                        "provider": "synthetic",
                        "sourceId": "synthetic-test",
                        "sourceUrl": "https://example.org/synthetic-test",
                        "retrievedAt": "2026-11-20T00:00:00Z",
                    },
                    "metadata": {
                        "creators": ["Fixture artist"],
                        "tags": ["Synthetic"],
                        "synopsis": "A synthetic test.",
                        "publicationStatus": "completed",
                        "cover": {
                            "file": "covers/synthetic.jpg",
                            "rightsEvidence": "Image was created by this test",
                            "attribution": "Synthetic test fixtures",
                        },
                    },
                }
            ],
        }
        self.candidates = self.meta / "candidates.json"
        self.candidates.write_text(json.dumps(candidates), encoding="utf-8")

    @staticmethod
    def event(body: str) -> dict[str, object]:
        return {
            "issue": {"title": ISSUE},
            "comment": {"body": body, "user": {"login": OWNER}},
        }

    def test_only_owner_exact_issue_command_can_trigger_private_ingest(self) -> None:
        preview = parse_event(
            self.event(f"/manga-import {TICKET} preview"),
            "issue_comment",
            OWNER,
            "refs/heads/master",
        )
        self.assertEqual(preview["ticket"], TICKET)
        self.assertEqual(preview["phase"], "preview")
        apply = parse_event(
            self.event(f"/manga-import {TICKET} apply {REVISION} {FINGERPRINT}"),
            "issue_comment",
            OWNER,
            "refs/heads/master",
        )
        self.assertEqual(apply["fingerprint"], FINGERPRINT)

        with self.assertRaises(ControllerError):
            parse_event(
                self.event(f"/manga-import {TICKET} preview"),
                "issue_comment",
                "outsider",
                "refs/heads/master",
            )
        with self.assertRaises(ControllerError):
            parse_event(
                self.event(f"/manga-import {TICKET} apply"),
                "issue_comment",
                OWNER,
                "refs/heads/master",
            )
        with self.assertRaises(ControllerError):
            parse_event(
                self.event(f"/manga-import {TICKET} preview"), "issue_comment", OWNER, "refs/heads/feature"
            )
        wrong_issue = self.event(f"/manga-import {TICKET} preview")
        wrong_issue["issue"] = {"title": "Some other issue"}
        with self.assertRaises(ControllerError):
            parse_event(wrong_issue, "issue_comment", OWNER, "refs/heads/master")
        wrong_user = self.event(f"/manga-import {TICKET} preview")
        wrong_user["comment"] = {"body": f"/manga-import {TICKET} preview", "user": {"login": "outsider"}}
        with self.assertRaises(ControllerError):
            parse_event(wrong_user, "issue_comment", OWNER, "refs/heads/master")
        with self.assertRaises(ControllerError):
            parse_event(
                {"inputs": {"ticket": TICKET, "phase": "apply"}},
                "workflow_dispatch",
                OWNER,
                "refs/heads/master",
            )

    def test_verified_private_package_extracts_with_no_schema_change(self) -> None:
        include = source_paths(self.bundle, self.candidates)
        self.assertTrue(any(name.endswith("/rights.json") for _, name in include))
        self.assertTrue(any(name == "metadata/covers/synthetic.jpg" for _, name in include))
        package = self.root / "package.zip"
        write_package(package, include)
        self.assertTrue(sha256_file(package))
        bundle, candidates = extract_private_package(package, self.root / "extracted")
        self.assertEqual(verify_bundle(bundle)["pages"], 3)
        records, _ = load_candidates(candidates)
        self.assertEqual(records[0]["mangaId"], self.entry["id"])
        self.assertEqual(records[0]["metadata"]["cover"]["file"], "covers/synthetic.jpg")

    def test_preview_pin_changes_when_staged_media_or_dataset_changes(self) -> None:
        include = source_paths(self.bundle, self.candidates)
        package = self.root / "package.zip"
        write_package(package, include)
        bundle, candidates = extract_private_package(package, self.root / "extracted")
        receipt = {
            "mangaId": self.entry["id"],
            "chapters": 1,
            "pages": 3,
            "metadataSha256": sha256_file(candidates),
            "packageSha256": sha256_file(package),
        }
        raw_catalogue = json.dumps(canonical_library([])).encode("utf-8")
        plan, fingerprint, extra = _preflight(
            bundle, candidates, receipt, REVISION, {"data/library.json"}, raw_catalogue, []
        )
        self.assertEqual(plan["status"], "ready")
        self.assertEqual(plan["new"], 1)
        self.assertEqual(extra["coverCount"], 1)
        self.assertEqual(extra["metadataChanges"], 5)
        _, different_revision, _ = _preflight(
            bundle, candidates, receipt, "d" * 40, {"data/library.json"}, raw_catalogue, []
        )
        self.assertNotEqual(fingerprint, different_revision)
        receipt["packageSha256"] = "0" * 64
        _, different_package, _ = _preflight(
            bundle, candidates, receipt, REVISION, {"data/library.json"}, raw_catalogue, []
        )
        self.assertNotEqual(fingerprint, different_package)

    def test_public_source_archive_path_traversal_is_rejected(self) -> None:
        package = self.root / "evil.zip"
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("bundle/../anything.txt", b"bad")
        with self.assertRaisesRegex(ControllerError, "Unsafe private manga staging ZIP path"):
            extract_private_package(package, self.root / "extracted")

    def test_zip_member_symlinks_are_rejected(self) -> None:
        package = self.root / "symlinks.zip"
        with zipfile.ZipFile(package, "w") as archive:
            member = zipfile.ZipInfo("bundle/unsafe.jpg")
            member.create_system = 3
            member.external_attr = 0o120777 << 16
            archive.writestr(member, b"spoof")
        with self.assertRaisesRegex(ControllerError, "symlink"):
            extract_private_package(package, self.root / "extracted")

    def test_tampered_immutable_manga_identity_is_rejected(self) -> None:
        include = source_paths(self.bundle, self.candidates)
        package = self.root / "package.zip"
        write_package(package, include)
        bundle, candidates = extract_private_package(package, self.root / "extracted")
        receipt = {
            "mangaId": "mng_ffffffffffffffff",
            "chapters": 1,
            "pages": 3,
            "metadataSha256": sha256_file(candidates),
            "packageSha256": sha256_file(package),
        }
        with self.assertRaisesRegex(ControllerError, "identity"):
            _preflight(
                bundle,
                candidates,
                receipt,
                REVISION,
                {"data/library.json"},
                json.dumps(canonical_library([])).encode(),
                [],
            )


if __name__ == "__main__":
    unittest.main()
