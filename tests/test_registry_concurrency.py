"""Identity assignment must be protected against concurrent imports and partial writes."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from taiyou_manga.builder import _registry_lock, build, load_json
from taiyou_manga.demo import create_demo
from taiyou_manga.domain import ControllerError


class IdentityRegistrySafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "fixtures"
        self.bundle = self.root / "bundle"
        self.registry = self.root / "state" / "ids.json"
        create_demo(self.source)

    def test_concurrent_import_is_rejected_and_lock_released(self) -> None:
        with _registry_lock(self.registry):
            with self.assertRaisesRegex(ControllerError, "registry is locked"):
                build(self.source, self.bundle, self.registry)
            self.assertFalse(self.bundle.exists())
        self.assertFalse(self.registry.with_name("ids.json.lock").exists())
        build(self.source, self.bundle, self.registry)
        self.assertTrue(self.registry.exists())

    def test_failed_registry_commit_never_publishes_bundle(self) -> None:
        with patch("taiyou_manga.builder.Path.replace", side_effect=OSError("write blocked")):
            with self.assertRaises(OSError):
                build(self.source, self.bundle, self.registry)
        self.assertFalse(self.bundle.exists())
        self.assertFalse(self.registry.exists())
        self.assertFalse(self.registry.with_name("ids.json.lock").exists())
        self.assertEqual(list(self.registry.parent.glob(".manga-ids-*.tmp")), [])

    def test_failed_bundle_publish_leaves_recoverable_registry(self) -> None:
        with patch("taiyou_manga.builder.Path.rename", side_effect=OSError("rename blocked")):
            with self.assertRaises(OSError):
                build(self.source, self.bundle, self.registry)
        self.assertFalse(self.bundle.exists())
        self.assertTrue(self.registry.exists())
        original = load_json(self.registry)
        build(self.source, self.bundle, self.registry)
        self.assertEqual(load_json(self.registry), original)

    def test_symlink_registry_cannot_be_followed(self) -> None:
        real = self.root / "real.json"
        real.write_text("{}", encoding="utf-8")
        self.registry.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.registry.symlink_to(real)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks unavailable")
        with self.assertRaisesRegex(ControllerError, "cannot be a symlink"):
            build(self.source, self.bundle, self.registry)
        self.assertFalse(self.bundle.exists())


if __name__ == "__main__":
    unittest.main()
