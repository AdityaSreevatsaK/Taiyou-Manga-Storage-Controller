"""Synthetic regression: preserve ReLIFE when appending another private manga."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from taiyou_manga.hf_upload import UploadConflict, UploadFile
from taiyou_manga.selected_hf_upload import inspect_selected, selected_apply
from taiyou_manga.selected_titles import TITLES, SelectedTitle


class FakeAdd:
    def __init__(self, *, path_in_repo: str, path_or_fileobj: object) -> None:
        self.path_in_repo = path_in_repo
        self.path_or_fileobj = path_or_fileobj


class FakeHf:
    def __init__(self, catalogue_file: Path) -> None:
        self.sha = "a" * 40
        self.files = {"catalogue.json", "ingest/relife-v1/complete.json"}
        self.commits: list[list[str]] = []
        self.catalogue_file = catalogue_file

    def dataset_info(self, repo_id: str, **kwargs: object) -> types.SimpleNamespace:
        return types.SimpleNamespace(sha=self.sha, private=True)

    def list_repo_files(self, repo_id: str, **kwargs: object) -> list[str]:
        return sorted(self.files)

    def create_commit(self, **kwargs: object) -> types.SimpleNamespace:
        assert kwargs["parent_commit"] == self.sha
        assert kwargs["repo_type"] == "dataset"
        operations = kwargs["operations"]
        names = [op.path_in_repo for op in operations]
        assert len(set(names)) == len(names)
        for op in operations:
            if op.path_in_repo in self.files and op.path_in_repo != "catalogue.json":
                raise AssertionError("Attempted overwrite of immutable media")
            if op.path_in_repo == "catalogue.json":
                body = op.path_or_fileobj
                assert isinstance(body, bytes)
                self.catalogue_file.write_bytes(body)
        self.commits.append(names)
        self.files.update(names)
        self.sha = f"{len(self.commits) + 5:040x}"
        return types.SimpleNamespace(oid=self.sha)


class SelectedUploadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.catalogue = self.root / "remote-catalogue.json"
        self.relife = {"kind": "manga", "id": "mng_existing_12345678", "title": "ReLIFE", "chapters": []}
        self.catalogue.write_text(json.dumps([self.relife]), encoding="utf-8")
        self.api = FakeHf(self.catalogue)
        self.title = SelectedTitle("test-other", "Test Other", 123, 1, 1, "Test-Original-Ch", "test-uuid")
        self.page = self.root / "page.png"
        self.page.write_bytes(b"synthetic-image")
        self.meta = self.root / "manifest.json"
        self.meta.write_text("{}", encoding="utf-8")
        self.media = [
            UploadFile(
                "assets/manga/mng_example/ch_example/pg_example.png",
                self.page,
                hashlib.sha256(self.page.read_bytes()).hexdigest(),
                self.page.stat().st_size,
            )
        ]
        self.metadata = [
            UploadFile(
                "manifests/ch_example.json",
                self.meta,
                hashlib.sha256(self.meta.read_bytes()).hexdigest(),
                self.meta.stat().st_size,
            )
        ]
        self.entry = {
            "kind": "manga",
            "id": "mng_other_12345678",
            "title": "Test Other",
            "chapters": [{"id": "ch_example_12345678", "label": "Chapter 1", "sequence": 0}],
        }
        self.fake = types.ModuleType("huggingface_hub")
        self.fake.CommitOperationAdd = FakeAdd  # type: ignore[attr-defined]
        self.fake.hf_hub_download = lambda **kw: str(self.catalogue)  # type: ignore[attr-defined]

    def test_appends_without_changing_existing_relife_entry(self) -> None:
        with (
            patch.dict(TITLES, {self.title.slug: self.title}),
            patch.dict(sys.modules, {"huggingface_hub": self.fake}),
        ):
            plan, _, _, _, _, _ = inspect_selected(
                self.api, "synthetic-token", self.title, self.media, self.metadata, self.entry
            )
            preview = self.root / "approved.json"
            preview.write_text(json.dumps(plan), encoding="utf-8")
            with (
                patch(
                    "taiyou_manga.selected_hf_upload.candidate_files",
                    return_value=(self.media, self.metadata, self.entry),
                ),
                patch("taiyou_manga.selected_hf_upload._hf_api", return_value=self.api),
            ):
                result = selected_apply(
                    self.title.slug, self.root, self.root, preview, "synthetic-token", approve=True
                )
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["catalogueTitles"], 2)
        self.assertEqual(result["partsWritten"], 1)
        self.assertNotIn("catalogue.json", self.api.commits[0])
        self.assertIn("catalogue.json", self.api.commits[1])
        final = json.loads(self.catalogue.read_text(encoding="utf-8"))
        self.assertIn(self.relife, final)
        self.assertIn(self.entry, final)

    def test_stale_revision_rejected_without_changes(self) -> None:
        with (
            patch.dict(TITLES, {self.title.slug: self.title}),
            patch.dict(sys.modules, {"huggingface_hub": self.fake}),
        ):
            plan, _, _, _, _, _ = inspect_selected(
                self.api, "test", self.title, self.media, self.metadata, self.entry
            )
            file = self.root / "plan.json"
            file.write_text(json.dumps(plan), encoding="utf-8")
            self.api.sha = "f" * 40
            with (
                patch(
                    "taiyou_manga.selected_hf_upload.candidate_files",
                    return_value=(self.media, self.metadata, self.entry),
                ),
                patch("taiyou_manga.selected_hf_upload._hf_api", return_value=self.api),
            ):
                with self.assertRaisesRegex(UploadConflict, "changed since preview"):
                    selected_apply(self.title.slug, self.root, self.root, file, "test", approve=True)
        self.assertEqual(self.api.commits, [])

    def test_existing_title_cannot_be_overwritten(self) -> None:
        self.catalogue.write_text(json.dumps([self.relife, self.entry]), encoding="utf-8")
        with patch.dict(sys.modules, {"huggingface_hub": self.fake}):
            with self.assertRaisesRegex(UploadConflict, "already exists"):
                inspect_selected(self.api, "test", self.title, self.media, self.metadata, self.entry)

    def test_private_upload_requires_attested_approval(self) -> None:
        with self.assertRaisesRegex(Exception, "approved"):
            selected_apply("maid-sama", self.root, self.root, self.root, "", approve=False)


if __name__ == "__main__":
    unittest.main()
