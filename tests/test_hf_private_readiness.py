"""Synthetic read-only Hugging Face gate tests, with no remote or token access."""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

from taiyou_manga.domain import ControllerError
from taiyou_manga.storage import HuggingFaceReadOnly, RemoteWritesDisabled


class HFPrivateReadinessTests(unittest.TestCase):
    @staticmethod
    def fake_hub(*, private: bool = True, missing: bool = False) -> dict[str, types.ModuleType]:
        hub = types.ModuleType("huggingface_hub")
        errors = types.ModuleType("huggingface_hub.errors")

        class RepositoryNotFoundError(Exception):
            pass

        class GatedRepoError(Exception):
            pass

        class RevisionNotFoundError(Exception):
            pass

        errors.RepositoryNotFoundError = RepositoryNotFoundError  # type: ignore[attr-defined]
        errors.GatedRepoError = GatedRepoError  # type: ignore[attr-defined]
        errors.RevisionNotFoundError = RevisionNotFoundError  # type: ignore[attr-defined]

        class FakeHfApi:
            def dataset_info(self, repo_id: str) -> types.SimpleNamespace:
                if repo_id != "AdityaSreevatsaK/Taiyous-Manga" or missing:
                    raise RepositoryNotFoundError("test dataset unavailable")
                return types.SimpleNamespace(private=private, sha="a" * 40)

        hub.HfApi = FakeHfApi  # type: ignore[attr-defined]
        return {"huggingface_hub": hub, "huggingface_hub.errors": errors}

    def test_private_health_read_only_without_token_details(self) -> None:
        with patch.dict(sys.modules, self.fake_hub()):
            result = HuggingFaceReadOnly("AdityaSreevatsaK/Taiyous-Manga").health()
        self.assertEqual(result["revision"], "a" * 40)
        self.assertIs(result["private"], True)
        self.assertIs(result["remoteWrites"], False)
        self.assertNotIn("token", result)

    def test_public_dataset_refused(self) -> None:
        with patch.dict(sys.modules, self.fake_hub(private=False)):
            with self.assertRaisesRegex(ControllerError, "Dataset is not private"):
                HuggingFaceReadOnly("AdityaSreevatsaK/Taiyous-Manga").health()

    def test_missing_private_access_refused(self) -> None:
        with patch.dict(sys.modules, self.fake_hub(missing=True)):
            with self.assertRaisesRegex(ControllerError, "Dataset missing, private without permission"):
                HuggingFaceReadOnly("AdityaSreevatsaK/Taiyous-Manga").health()

    def test_huggingface_write_remains_disabled(self) -> None:
        with self.assertRaises(RemoteWritesDisabled):
            HuggingFaceReadOnly("AdityaSreevatsaK/Taiyous-Manga").write("unsafe")


if __name__ == "__main__":
    unittest.main()
