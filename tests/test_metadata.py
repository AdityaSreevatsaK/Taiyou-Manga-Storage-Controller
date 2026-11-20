"""Synthetic-only regression tests for safe metadata enrichment and HF commits."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from taiyou_manga.domain import ControllerError
from taiyou_manga.hf_layout import canonical_library, validate_library
from taiyou_manga.hf_metadata import apply, preview
from taiyou_manga.metadata import completeness, load_candidates, reconcile, validate_candidates


def entry() -> dict[str, object]:
    return {
        "kind": "manga",
        "id": "mng_aaaaaaaaaaaa",
        "title": "Demo Manga",
        "aliases": [],
        "creators": [],
        "tags": [],
        "publicationStatus": "unknown",
        "direction": "vertical",
        "chapters": [{"id": "ch_bbbbbbbbbbbb", "sequence": 0, "label": "Chapter 1", "pageCount": 1}],
    }


def candidate(*, covers: bool = False) -> dict[str, object]:
    meta: dict[str, object] = {
        "creatorRoles": [
            {"name": "Artist A", "role": "artist"},
            {"name": "Writer B", "role": "author"},
        ],
        "tags": ["Comedy", "Romance"],
        "synopsis": "A safely sourced publication description.",
        "publicationStatus": "completed",
        "aliases": ["Demo alternative"],
    }
    if covers:
        meta["cover"] = {
            "file": "covers/demo.webp",
            "rightsEvidence": "Permitted artwork provided for private use",
            "attribution": "Publisher",
        }
    return {
        "schemaVersion": 1,
        "mediaKind": "manga-metadata-candidates",
        "candidates": [
            {
                "mangaId": "mng_aaaaaaaaaaaa",
                "title": "Demo Manga",
                "source": {
                    "provider": "example",
                    "sourceId": "source-123",
                    "sourceUrl": "https://example.org/title/123",
                    "retrievedAt": "2026-11-20T08:30:00Z",
                },
                "metadata": meta,
            }
        ],
    }


class FakeAdd:
    def __init__(self, *, path_in_repo: str, path_or_fileobj: bytes) -> None:
        self.path_in_repo = path_in_repo
        self.path_or_fileobj = path_or_fileobj


class FakeHF:
    def __init__(self, original: bytes, root: Path) -> None:
        self.files = {
            "data/library.json": original,
            "data/manifests/ch_bbbbbbbbbbbb.json": b"unchanged manifest",
            "data/manga/mng_aaaaaaaaaaaa/ch_bbbbbbbbbbbb/pg_cccccccccccc.webp": b"original page",
        }
        self.root = root
        self.sha = "a" * 40
        self.private = True
        self.commits: list[list[str]] = []

    def dataset_info(self, _repo: str, **kwargs: object) -> types.SimpleNamespace:
        return types.SimpleNamespace(sha=self.sha, private=self.private)

    def list_repo_files(self, _repo: str, **kwargs: object) -> list[str]:
        return sorted(self.files)

    def download(self, filename: str) -> str:
        if filename not in self.files:
            raise AssertionError("Unrecognised private test filename")
        destination = self.root / filename.replace("/", "_")
        destination.write_bytes(self.files[filename])
        return str(destination)

    def create_commit(self, **kwargs: object) -> types.SimpleNamespace:
        if kwargs["parent_commit"] != self.sha:
            raise AssertionError("Private Git revision changed")
        ops = kwargs["operations"]
        names = [op.path_in_repo for op in ops]
        self.commits.append(names)
        for op in ops:
            if op.path_in_repo != "data/library.json" and op.path_in_repo in self.files:
                raise AssertionError("Media or metadata overwritten")
            data = op.path_or_fileobj
            assert isinstance(data, bytes)
            self.files[op.path_in_repo] = data
        self.sha = "b" * 40
        return types.SimpleNamespace(oid=self.sha)


class MetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.document = self.root / "metadata.json"
        self.document.write_text(json.dumps(candidate()), encoding="utf-8")
        self.original = entry()

    def test_candidate_envelope_and_provenance_validation(self) -> None:
        parsed, digest = load_candidates(self.document)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(len(digest), 64)
        self.assertEqual(parsed[0]["metadata"]["creators"], ["Artist A", "Writer B"])
        invalid = candidate()
        invalid["candidates"][0]["source"]["sourceUrl"] = "http://example.org"
        with self.assertRaisesRegex(ControllerError, "HTTPS"):
            validate_candidates(invalid)
        invalid["candidates"][0]["source"]["sourceUrl"] = "https://example.org/?token=secret"
        with self.assertRaisesRegex(ControllerError, "HTTPS"):
            validate_candidates(invalid)

    def test_metadata_is_additive_without_touching_chapters_or_ids(self) -> None:
        checked, _ = load_candidates(self.document)
        updated, files, changes, conflicts = reconcile([self.original], checked, self.root, set())
        self.assertFalse(conflicts)
        self.assertFalse(files)
        self.assertEqual(len(changes), 6)
        self.assertEqual(updated[0]["chapters"], self.original["chapters"])
        self.assertEqual(updated[0]["id"], self.original["id"])
        self.assertEqual(updated[0]["publicationStatus"], "completed")
        self.assertEqual(updated[0]["creators"], ["Artist A", "Writer B"])
        self.assertIn("creators", updated[0]["metadataSources"])
        self.assertEqual(validate_library(canonical_library(updated)), updated)

    def test_manual_values_are_never_overwritten(self) -> None:
        original = {**self.original, "creators": ["Manually corrected"], "tags": ["My curated genre"]}
        checked, _ = load_candidates(self.document)
        updated, _, changes, conflicts = reconcile([original], checked, self.root, set())
        self.assertEqual(updated[0]["creators"], original["creators"])
        self.assertEqual(updated[0]["tags"], original["tags"])
        self.assertEqual(len(conflicts), 2)
        self.assertTrue(changes)

    def test_title_only_and_mismatched_identifiers_require_review(self) -> None:
        raw = candidate()
        del raw["candidates"][0]["mangaId"]
        checked = validate_candidates(raw)
        updated, _, changes, conflicts = reconcile([self.original], checked, self.root, set())
        self.assertEqual(updated, [self.original])
        self.assertFalse(changes)
        self.assertRegex(conflicts[0], "title-only match")
        raw = candidate()
        raw["candidates"][0]["title"] = "Wrong manga"
        _, _, _, conflicts = reconcile([self.original], validate_candidates(raw), self.root, set())
        self.assertIn("mismatched", conflicts[0])

    def test_cover_checked_without_transcoding_or_traversal(self) -> None:
        doc = candidate(covers=True)
        coverdir = self.root / "covers"
        coverdir.mkdir()
        image = Image.new("RGB", (12, 18))
        stream = io.BytesIO()
        image.save(stream, format="WEBP")
        content = stream.getvalue()
        (coverdir / "demo.webp").write_bytes(content)
        checked = validate_candidates(doc)
        updated, uploads, changes, conflicts = reconcile([self.original], checked, self.root, set())
        self.assertFalse(conflicts)
        self.assertEqual(len(uploads), 1)
        descriptor = updated[0]["cover"]
        self.assertEqual(descriptor["assetPath"], "covers/mng_aaaaaaaaaaaa.webp")
        self.assertEqual(descriptor["byteSize"], len(content))
        self.assertIn("cover", updated[0]["metadataSources"])
        self.assertIn("cover", [change["field"] for change in changes])
        self.assertEqual(uploads["data/covers/mng_aaaaaaaaaaaa.webp"].read_bytes(), content)
        self.assertEqual(validate_library(canonical_library(updated)), updated)
        doc["candidates"][0]["metadata"]["cover"]["file"] = "../secret.webp"
        with self.assertRaisesRegex(ControllerError, "Unsafe"):
            validate_candidates(doc)

    def test_completeness_report(self) -> None:
        report = completeness([self.original])
        self.assertEqual(report["series"], 1)
        self.assertEqual(report["complete"], 0)
        self.assertEqual(report["missingCount"]["cover"], 1)
        checked, _ = load_candidates(self.document)
        updated, _, _, _ = reconcile([self.original], checked, self.root, set())
        self.assertEqual(completeness(updated)["missingCount"]["creators"], 0)

    def test_private_revision_guard_and_byte_identical_catalogue_backup(self) -> None:
        original_bytes = json.dumps(canonical_library([self.original])).encode("utf-8")
        remote = FakeHF(original_bytes, self.root)
        fake = types.ModuleType("huggingface_hub")
        fake.CommitOperationAdd = FakeAdd
        fake.hf_hub_download = lambda **kw: remote.download(kw["filename"])
        with patch.dict(sys.modules, {"huggingface_hub": fake}):
            plan = preview(remote, "synthetic-token", self.document)
            self.assertEqual(plan["status"], "ready")
            self.assertEqual(plan["deleteOperations"], 0)
            self.assertEqual(plan["chapterOrPageWrites"], 0)
            approval = self.root / "approved.json"
            approval.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(ControllerError, "approval"):
                apply(remote, "synthetic-token", self.document, approval)
            result = apply(remote, "synthetic-token", self.document, approval, approve=True)
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["series"], 1)
            self.assertEqual(remote.files[result["catalogueBackup"]], original_bytes)
            self.assertEqual(len(remote.commits), 1)
            self.assertEqual(len(remote.commits[0]), 2)
            self.assertNotIn("data/manifests/ch_bbbbbbbbbbbb.json", remote.commits[0])
            self.assertNotIn(
                "data/manga/mng_aaaaaaaaaaaa/ch_bbbbbbbbbbbb/pg_cccccccccccc.webp", remote.commits[0]
            )
            with self.assertRaisesRegex(ControllerError, "stale"):
                apply(remote, "synthetic-token", self.document, approval, approve=True)

    def test_private_cover_commit_keeps_original_pages_and_rights(self) -> None:
        import io

        doc = candidate(covers=True)
        (self.root / "covers").mkdir()
        image = Image.new("RGB", (16, 24))
        stream = io.BytesIO()
        image.save(stream, format="WEBP")
        bytes_image = stream.getvalue()
        (self.root / "covers" / "demo.webp").write_bytes(bytes_image)
        self.document.write_text(json.dumps(doc), encoding="utf-8")
        original_bytes = json.dumps(canonical_library([self.original])).encode("utf-8")
        remote = FakeHF(original_bytes, self.root)
        pages_before = {
            path: body
            for path, body in remote.files.items()
            if path.startswith(("data/manga/", "data/manifests/"))
        }
        fake = types.ModuleType("huggingface_hub")
        fake.CommitOperationAdd = FakeAdd
        fake.hf_hub_download = lambda **kw: remote.download(kw["filename"])
        with patch.dict(sys.modules, {"huggingface_hub": fake}):
            plan = preview(remote, "token", self.document)
            self.assertEqual(plan["status"], "ready")
            self.assertEqual(len(plan["coverUploads"]), 1)
            self.assertEqual(len(plan["coverRights"]), 1)
            approval = self.root / "cover-preview.json"
            approval.write_text(json.dumps(plan), encoding="utf-8")
            result = apply(remote, "token", self.document, approval, approve=True)
        self.assertEqual(result["coversAdded"], 1)
        self.assertEqual(result["coverRightsStored"], 1)
        self.assertEqual(
            remote.files["data/covers/mng_aaaaaaaaaaaa.webp"], bytes_image
        )
        self.assertEqual(
            {path: remote.files[path] for path in pages_before}, pages_before
        )
        self.assertEqual(remote.files[result["catalogueBackup"]], original_bytes)
        rights_path = plan["coverRights"][0]["path"]
        rights_doc = json.loads(remote.files[rights_path])
        self.assertEqual(rights_doc["attribution"], "Publisher")
        self.assertEqual(rights_doc["mangaId"], self.original["id"])
        after = json.loads(remote.files["data/library.json"])["entries"][0]
        self.assertEqual(after["chapters"], self.original["chapters"])
        self.assertEqual(after["cover"]["mimeType"], "image/webp")

    def test_no_write_when_existing_manual_metadata_conflicts(self) -> None:
        old = {**self.original, "synopsis": "Private manual corrections"}
        remote = FakeHF(json.dumps(canonical_library([old])).encode(), self.root)
        fake = types.ModuleType("huggingface_hub")
        fake.hf_hub_download = lambda **kw: remote.download(kw["filename"])
        with patch.dict(sys.modules, {"huggingface_hub": fake}):
            plan = preview(remote, "token", self.document)
        self.assertEqual(plan["status"], "conflict")
        self.assertTrue(plan["conflicts"])
        self.assertFalse(remote.commits)


if __name__ == "__main__":
    unittest.main()
