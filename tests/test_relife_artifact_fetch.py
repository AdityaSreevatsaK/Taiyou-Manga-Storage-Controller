"""No-network unit tests for secure cross-repository source artefact retrieval."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.fetch_relife_actions_artifacts import (
    EXPECTED_NAMES,
    SourceAccessError,
    _list_artifacts,
    _signed_download_url,
    _stream_download,
    _valid_blob_url,
)


class DownloadSecurityTests(unittest.TestCase):
    def test_accept_signed_github_owned_origin_only(self) -> None:
        good = "https://productionresultssa1.blob.core.windows.net/actions-results/abc?sig=secret"
        self.assertTrue(_valid_blob_url(good))
        self.assertTrue(_valid_blob_url("https://pipelines.actions.githubusercontent.com/archive"))
        self.assertFalse(_valid_blob_url("http://productionresultssa1.blob.core.windows.net/x"))
        self.assertFalse(_valid_blob_url("https://pipelines.actions.githubusercontent.com.evil.test/x"))
        self.assertFalse(_valid_blob_url("https://evil.test/x"))

    def test_source_artifact_listing_requires_exact_batches(self) -> None:
        artifacts = [
            {"name": name, "id": index + 1, "expired": False, "size_in_bytes": 100}
            for index, name in enumerate(sorted(EXPECTED_NAMES))
        ]
        data = io.BytesIO(json.dumps({"artifacts": artifacts}).encode("utf-8"))
        with patch("urllib.request.urlopen", return_value=data):
            self.assertEqual(len(_list_artifacts("test-token")), 12)

        artifacts[0]["expired"] = True
        denied = io.BytesIO(json.dumps({"artifacts": artifacts}).encode("utf-8"))
        with patch("urllib.request.urlopen", return_value=denied):
            with self.assertRaisesRegex(SourceAccessError, "expired"):
                _list_artifacts("test-token")

    def test_redirect_does_not_trust_attacker_download_location(self) -> None:
        error = urllib.error.HTTPError(
            "https://api.github.com/placeholder",
            303,
            "See Other",
            {"Location": "https://attacker.test/files?key=invalid"},
            None,
        )
        fake = Mock()
        fake.open.side_effect = error
        with patch("urllib.request.build_opener", return_value=fake):
            with self.assertRaisesRegex(SourceAccessError, "untrusted"):
                _signed_download_url("test-token", 123)

    def test_stream_download_checks_size_and_removes_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "source.zip"
            with patch("urllib.request.urlopen", return_value=io.BytesIO(b"zipdata")):
                self.assertEqual(_stream_download("https://example.test/file", target, 7), 7)
            self.assertEqual(target.read_bytes(), b"zipdata")

            mismatch = Path(folder) / "mismatch.zip"
            with patch("urllib.request.urlopen", return_value=io.BytesIO(b"broken")):
                with self.assertRaisesRegex(SourceAccessError, "size does not match"):
                    _stream_download("https://example.test/file", mismatch, 50)
            self.assertFalse(mismatch.exists())


if __name__ == "__main__":
    unittest.main()
