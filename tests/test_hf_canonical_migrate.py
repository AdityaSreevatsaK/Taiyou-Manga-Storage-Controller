"""Synthetic safety regressions for private ReLIFE canonical migration."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from taiyou_manga.domain import ControllerError
from taiyou_manga.hf_canonical_migrate import (
    BATCH_SIZE,
    CANONICAL_CATALOGUE,
    EXPECTED_FILES,
    SOURCE_SHA,
    _batches,
    _identity,
    _marker,
    _verify_namespace,
)


class CanonicalMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = "assets/manga/mng_aaaaaaaa/ch_bbbbbbbb/pg_cccccccc.png"
        self.target = "data/manga/mng_aaaaaaaa/ch_bbbbbbbb/pg_cccccccc.png"
        self.manifest_source = "manifests/ch_bbbbbbbb.json"
        self.manifest_target = "data/manifests/ch_bbbbbbbb.json"
        self.mapping = {
            self.source: self.target,
            self.manifest_source: self.manifest_target,
        }

    def test_expected_real_inventory(self) -> None:
        self.assertEqual(EXPECTED_FILES, 5843)
        self.assertEqual(BATCH_SIZE, 125)
        self.assertEqual(len(SOURCE_SHA), 40)

    def test_stable_batches_and_checkpoint(self) -> None:
        batches = _batches(self.mapping)
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches, _batches(dict(reversed(list(self.mapping.items())))))
        name, marker = _marker("staging", 1, batches[0])
        self.assertIn("staging/batch-001.json", name)
        self.assertEqual(marker, _marker("staging", 1, batches[0])[1])
        with self.assertRaises(ControllerError):
            _marker("unknown", 1, batches[0])

    def test_batches_are_bounded_without_losing_files(self) -> None:
        paths = {f"assets/manga/a/file_{index:05d}.png": f"data/manga/a/file_{index:05d}.png"
                 for index in range(EXPECTED_FILES)}
        batches = _batches(paths)
        self.assertEqual(sum(len(batch) for batch in batches), EXPECTED_FILES)
        self.assertTrue(all(0 < len(batch) <= BATCH_SIZE for batch in batches))

    def test_preserves_originals_and_rejects_unknown_canonical_paths(self) -> None:
        existing = {self.source, self.manifest_source, ".gitattributes"}
        _verify_namespace(existing, self.mapping)
        _verify_namespace(existing | {self.target, CANONICAL_CATALOGUE}, self.mapping)
        with self.assertRaisesRegex(ControllerError, "Unrecognised"):
            _verify_namespace(existing | {"data/secrets/unrelated.json"}, self.mapping)
        with self.assertRaisesRegex(ControllerError, "original"):
            _verify_namespace(existing - {self.source}, self.mapping)

    def test_content_identity_is_strictly_immutable(self) -> None:
        original = SimpleNamespace(size=12345, blob_id="f" * 40, lfs={"sha256": "a" * 64})
        copied = SimpleNamespace(size=12345, blob_id="f" * 40, lfs={"sha256": "a" * 64})
        self.assertEqual(_identity(original), _identity(copied))
        changed = SimpleNamespace(size=12345, blob_id="e" * 40, lfs={"sha256": "a" * 64})
        self.assertNotEqual(_identity(original), _identity(changed))
        with self.assertRaises(ControllerError):
            _identity(SimpleNamespace(size=12345, blob_id=None, lfs=None))


if __name__ == "__main__":
    unittest.main()
