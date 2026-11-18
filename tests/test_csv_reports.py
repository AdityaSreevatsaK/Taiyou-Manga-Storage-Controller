"""Private CSV reports are verified, non-destructive and spreadsheet-safe."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from taiyou_manga.builder import build, load_json, write_json
from taiyou_manga.cli import main
from taiyou_manga.demo import create_demo
from taiyou_manga.domain import ControllerError
from taiyou_manga.reports import export_inventory_csv


class CSVReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = self.root / "source"
        self.bundle = self.root / "bundle"
        create_demo(source)
        build(
            source, self.bundle, self.root / "ids.json", rights_path=self.root / "source-rights-example.json"
        )
        self.report = self.root / "reports" / "inventory.csv"

    def read_rows(self) -> list[dict[str, str]]:
        with self.report.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def test_export_chapters_pages_and_private_fields(self) -> None:
        self.assertEqual(
            main(["export-csv", "--bundle", str(self.bundle), "--output", str(self.report)]),
            0,
        )
        rows = self.read_rows()
        self.assertEqual(len(rows), 4)
        self.assertEqual(sum(int(row["page_count"]) for row in rows), 12)
        self.assertEqual({row["rights_declared"] for row in rows}, {"yes"})
        self.assertNotIn("permissionEvidence", self.report.read_text(encoding="utf-8-sig"))
        self.assertNotIn("personalProgress", self.report.read_text(encoding="utf-8-sig"))

    def test_spreadsheet_formula_injection_is_escaped(self) -> None:
        path = self.bundle / "catalogue.json"
        entries = load_json(path)
        entries[0]["title"] = '=HYPERLINK("https://example.com","click")'
        entries[0]["chapters"][0]["label"] = "+SUM(A1:A5)"
        entries[0]["chapters"][0]["volume"] = "-1+2"
        write_json(path, entries)
        export_inventory_csv(self.bundle, self.report)
        rows = self.read_rows()
        changed = [row for row in rows if row["series_title"].startswith("'=HYPERLINK")]
        self.assertTrue(changed)
        self.assertIn("'+SUM(A1:A5)", [row["chapter_label"] for row in changed])
        self.assertIn("'-1+2", [row["volume"] for row in changed])

    def test_existing_report_and_report_inside_bundle_refused(self) -> None:
        export_inventory_csv(self.bundle, self.report)
        original = self.report.read_bytes()
        with self.assertRaises(ControllerError):
            export_inventory_csv(self.bundle, self.report)
        self.assertEqual(self.report.read_bytes(), original)
        with self.assertRaises(ControllerError):
            export_inventory_csv(self.bundle, self.bundle / "inventory.csv")

    def test_corrupt_bundle_cannot_generate_report(self) -> None:
        target = next((self.bundle / "assets").rglob("*.png"))
        target.write_bytes(b"damaged image")
        with self.assertRaises(ControllerError):
            export_inventory_csv(self.bundle, self.report)
        self.assertFalse(self.report.exists())


if __name__ == "__main__":
    unittest.main()
