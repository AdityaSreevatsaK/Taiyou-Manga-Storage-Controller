"""Fail closed on untrusted ID registry contents before publishing any bundle."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from taiyou_manga.builder import build, write_json
from taiyou_manga.demo import create_demo
from taiyou_manga.domain import ControllerError


class RegistryValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.bundle = self.root / "bundle"
        self.registry = self.root / "identity.json"
        create_demo(self.source)

    def test_duplicate_opaque_registry_values_rejected(self) -> None:
        write_json(
            self.registry,
            {
                "chapter:Series/Chapter 1": "ch_abcdefghijkl",
                "chapter:Series/Chapter 2": "ch_abcdefghijkl",
            },
        )
        before = self.registry.read_bytes()
        with self.assertRaisesRegex(ControllerError, "Duplicate opaque ID"):
            build(self.source, self.bundle, self.registry)
        self.assertEqual(self.registry.read_bytes(), before)
        self.assertFalse(self.bundle.exists())

    def test_unknown_registry_keys_fail_closed(self) -> None:
        write_json(self.registry, {"other:some-source": "mng_abcdefghijkl"})
        with self.assertRaisesRegex(ControllerError, "Unknown identity registry key type"):
            build(self.source, self.bundle, self.registry)
        self.assertFalse(self.bundle.exists())

    def test_colliding_case_insensitive_keys_rejected(self) -> None:
        write_json(
            self.registry,
            {
                "series:Signal Garden": "mng_abcdefghijkl",
                "series:signal garden": "mng_mnopqrstuvwx",
            },
        )
        with self.assertRaisesRegex(ControllerError, "Case-insensitive duplicate"):
            build(self.source, self.bundle, self.registry)
        self.assertFalse(self.bundle.exists())

    def test_invalid_empty_registry_source_key_rejected(self) -> None:
        write_json(self.registry, {"chapter:": "ch_abcdefghijkl"})
        with self.assertRaisesRegex(ControllerError, "Invalid identity registry source key"):
            build(self.source, self.bundle, self.registry)
        self.assertFalse(self.bundle.exists())

    def test_staged_verification_failure_keeps_registry_unmodified(self) -> None:
        with patch(
            "taiyou_manga.builder.verify_bundle",
            side_effect=ControllerError("Invalid staged bundle"),
        ):
            with self.assertRaisesRegex(ControllerError, "Invalid staged bundle"):
                build(self.source, self.bundle, self.registry)
        self.assertFalse(self.bundle.exists())
        self.assertFalse(self.registry.exists())
        self.assertFalse(self.registry.with_name("identity.json.lock").exists())


if __name__ == "__main__":
    unittest.main()
