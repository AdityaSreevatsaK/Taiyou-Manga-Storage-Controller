"""Synthetic tests for a complete, pinned, private HF pre-migration recovery branch."""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

from taiyou_manga.domain import ControllerError
from taiyou_manga.hf_recovery import BACKUP_BRANCH, create_recovery_ref


class FakeApi:
    def __init__(self) -> None:
        self.sha = "a" * 40
        self.branch: str | None = None
        self.branch_sha: str | None = None
        self.calls = 0
        self.files = ["catalogue.json", "manifests/ch_test000000.json", "assets/manga/test.png"]

    def list_repo_refs(self, repo_id: str, **kw: object) -> types.SimpleNamespace:
        refs = (
            [types.SimpleNamespace(name=BACKUP_BRANCH, target_commit=self.branch_sha)]
            if self.branch
            else []
        )
        return types.SimpleNamespace(branches=refs)

    def create_branch(self, **kw: object) -> None:
        self.calls += 1
        assert kw["branch"] == BACKUP_BRANCH
        assert kw["revision"] == self.sha
        assert kw["repo_type"] == "dataset"
        self.branch = BACKUP_BRANCH
        self.branch_sha = self.sha

    def dataset_info(self, repo_id: str, **kw: object) -> types.SimpleNamespace:
        return types.SimpleNamespace(private=True, sha=self.branch_sha if kw.get("revision") else self.sha)

    def list_repo_files(self, repo_id: str, **kw: object) -> list[str]:
        return self.files


class RecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api = FakeApi()
        self.hub = types.ModuleType("huggingface_hub")
        self.hub.HfApi = lambda token: self.api  # type: ignore[attr-defined]
        self.plan = {
            "series": 1, "chapters": 237, "pages": 5606,
            "expectedRevision": self.api.sha, "filesToCopyWithoutDeletingLegacy": 5843,
        }

    def test_preview_does_not_create_branch(self) -> None:
        with (
            patch.dict(sys.modules, {"huggingface_hub": self.hub}),
            patch("taiyou_manga.hf_recovery.read_legacy_preview", return_value=self.plan),
        ):
            result = create_recovery_ref("synthetic-token", apply=False)
        self.assertEqual(result["status"], "recovery-branch-proposed")
        self.assertEqual(self.api.calls, 0)
        self.assertIs(result["mainModified"], False)
        self.assertIs(result["independentOffPlatformBackup"], False)

    def test_pins_and_verifies_full_snapshot_without_modifying_main(self) -> None:
        with (
            patch.dict(sys.modules, {"huggingface_hub": self.hub}),
            patch("taiyou_manga.hf_recovery.read_legacy_preview", return_value=self.plan),
        ):
            created = create_recovery_ref("synthetic-token", apply=True)
            repeated = create_recovery_ref("synthetic-token", apply=True)
        self.assertEqual(created["status"], "recovery-branch-created")
        self.assertEqual(repeated["status"], "already-protected")
        self.assertEqual(self.api.calls, 1)
        self.assertEqual(created["protectedRevision"], self.api.sha)

    def test_changed_existing_branch_refuses_to_move_it(self) -> None:
        self.api.branch = BACKUP_BRANCH
        self.api.branch_sha = "b" * 40
        with (
            patch.dict(sys.modules, {"huggingface_hub": self.hub}),
            patch("taiyou_manga.hf_recovery.read_legacy_preview", return_value=self.plan),
        ):
            with self.assertRaisesRegex(ControllerError, "different original revision"):
                create_recovery_ref("test", apply=True)
        self.assertEqual(self.api.calls, 0)

    def test_requires_verified_full_baseline_before_creating_backup(self) -> None:
        wrong = {**self.plan, "pages": 5605}
        with (
            patch.dict(sys.modules, {"huggingface_hub": self.hub}),
            patch("taiyou_manga.hf_recovery.read_legacy_preview", return_value=wrong),
        ):
            with self.assertRaisesRegex(ControllerError, "verified baseline"):
                create_recovery_ref("test", apply=True)
        self.assertEqual(self.api.calls, 0)


if __name__ == "__main__":
    unittest.main()
