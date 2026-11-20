"""Offline regression tests for the gated, append-only private HF uploader."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from taiyou_manga.domain import ControllerError
from taiyou_manga.hf_upload import (
    BATCH_SIZE,
    DATASET,
    UploadConflict,
    UploadFile,
    _checkpoint,
    _digest_records,
    _inspect,
    _partition,
    _remote,
    apply_relife_upload,
    preview_relife_upload,
)
from taiyou_manga.relife_stage import _stable_registry


class FakeApi:
    def __init__(self, *, private: bool = True, files: set[str] | None = None) -> None:
        self.sha = "a" * 40
        self.private = private
        self.files = set(files or [])
        self.commits: list[list[str]] = []

    def dataset_info(self, repo_id: str, **kwargs: object) -> types.SimpleNamespace:
        assert repo_id == DATASET
        return types.SimpleNamespace(sha=self.sha, private=self.private)

    def list_repo_files(self, repo_id: str, **kwargs: object) -> list[str]:
        assert repo_id == DATASET
        return sorted(self.files)

    def create_commit(self, **kwargs: object) -> types.SimpleNamespace:
        assert kwargs["repo_id"] == DATASET
        assert kwargs["repo_type"] == "dataset"
        assert kwargs["parent_commit"] == self.sha
        ops = kwargs["operations"]
        paths = [operation.path_in_repo for operation in ops]
        if self.files.intersection(paths):
            raise AssertionError("Uploader attempted to overwrite existing paths")
        self.files.update(paths)
        self.commits.append(paths)
        self.sha = f"{len(self.commits) + 1:040x}"
        return types.SimpleNamespace(oid=self.sha)


class AddOperation:
    def __init__(self, *, path_in_repo: str, path_or_fileobj: object) -> None:
        self.path_in_repo = path_in_repo
        self.path_or_fileobj = path_or_fileobj


class HFUploadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.page = self.root / "page.png"
        self.page.write_bytes(b"synthetic-media")
        self.meta = self.root / "catalogue.json"
        self.meta.write_text("[]", encoding="utf-8")
        self.pages = [
            UploadFile(f"assets/manga/mng_test/ch_test/pg_{i:08}.png", self.page, hashlib.sha256(b"synthetic-media").hexdigest(), 15)
            for i in range(3)
        ]
        self.metadata = [
            UploadFile("catalogue.json", self.meta, hashlib.sha256(b"[]").hexdigest(), 2)
        ]

    def test_stable_opaque_ids_independent_of_import_machine(self) -> None:
        first = _stable_registry({"1", "19.5"})
        second = _stable_registry({"19.5", "1"})
        self.assertEqual(first, second)
        self.assertEqual(len(first), 3)
        self.assertEqual(first["series:ReLIFE"][:4], "mng_")
        self.assertTrue(first["chapter:ReLIFE/Chapter 19.5.cbz"].startswith("ch_"))
        self.assertNotEqual(first["chapter:ReLIFE/Chapter 19.5.cbz"], first["chapter:ReLIFE/Chapter 1.cbz"])

    def test_digest_and_chunk_marker_deterministic(self) -> None:
        self.assertEqual(len(_partition(self.pages)), 1)
        self.assertEqual(BATCH_SIZE, 200)
        self.assertEqual(_digest_records(self.pages), _digest_records(list(self.pages)))
        name, first = _checkpoint(1, self.pages)
        self.assertEqual(name, "ingest/relife-v1/part-001.json")
        self.assertEqual(first, _checkpoint(1, self.pages)[1])

    def test_reject_non_private_dataset(self) -> None:
        with self.assertRaisesRegex(ControllerError, "private"):
            _remote(FakeApi(private=False), "synthetic-token")

    def test_reject_existing_catalogue_and_orphan_media(self) -> None:
        with self.assertRaisesRegex(UploadConflict, "catalogue already exists"):
            _inspect(FakeApi(files={"catalogue.json"}), "test", self.pages, self.metadata)
        with self.assertRaisesRegex(UploadConflict, "without the expected atomic"):
            _inspect(FakeApi(files={self.pages[0].path}), "test", self.pages, self.metadata)

    def test_preview_never_allows_empty_hf_token(self) -> None:
        with self.assertRaisesRegex(ControllerError, "HF_TOKEN"):
            preview_relife_upload(self.root / "none", self.root / "ids", "")

    def test_apply_requires_explicit_approval_even_with_token(self) -> None:
        with self.assertRaisesRegex(ControllerError, "Explicit owner"):
            apply_relife_upload(
                self.root, self.root / "ids", "test", self.root / "plan.json", approve=False
            )

    def test_preview_and_apply_adds_media_first_and_catalogue_last(self) -> None:
        api = FakeApi()
        plan, _, _, _, _ = _inspect(api, "test", self.pages, self.metadata)
        plan_file = self.root / "plan.json"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")
        fake = types.ModuleType("huggingface_hub")
        fake.CommitOperationAdd = AddOperation  # type: ignore[attr-defined]
        with (
            patch("taiyou_manga.hf_upload._candidate", return_value=(self.pages, self.metadata)),
            patch("taiyou_manga.hf_upload._hf_api", return_value=api),
            patch.dict(sys.modules, {"huggingface_hub": fake}),
        ):
            result = apply_relife_upload(self.root, self.root / "ids", "test", plan_file, approve=True)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["partsWritten"], 1)
        self.assertEqual(len(api.commits), 2)
        self.assertNotIn("catalogue.json", api.commits[0])
        self.assertIn("catalogue.json", api.commits[1])
        self.assertIn("ingest/relife-v1/complete.json", api.commits[1])
        self.assertEqual(len(set(api.commits[0] + api.commits[1])), len(api.commits[0] + api.commits[1]))

    def test_revision_change_after_preview_aborts_without_commit(self) -> None:
        api = FakeApi()
        plan, _, _, _, _ = _inspect(api, "test", self.pages, self.metadata)
        plan_file = self.root / "plan.json"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")
        api.sha = "f" * 40
        fake = types.ModuleType("huggingface_hub")
        fake.CommitOperationAdd = AddOperation  # type: ignore[attr-defined]
        with (
            patch("taiyou_manga.hf_upload._candidate", return_value=(self.pages, self.metadata)),
            patch("taiyou_manga.hf_upload._hf_api", return_value=api),
            patch.dict(sys.modules, {"huggingface_hub": fake}),
        ):
            with self.assertRaisesRegex(UploadConflict, "changed since approved preview"):
                apply_relife_upload(self.root, self.root / "ids", "test", plan_file, approve=True)
        self.assertFalse(api.commits)


if __name__ == "__main__":
    unittest.main()
