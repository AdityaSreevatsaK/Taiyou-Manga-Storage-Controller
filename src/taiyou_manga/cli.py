"""Cross-platform CLI and Windows-friendly interactive menu."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .backup import create_backup, restore_backup, verify_backup
from .builder import build, load_json, verify_bundle
from .demo import create_demo
from .domain import ControllerError
from .images import Limits
from .sources import discover
from .storage import HuggingFaceReadOnly, MockStorage


def _path(value: str) -> Path:
    return Path(value).expanduser()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="taiyou-manga", description="Offline-first manga storage controller")
    sub = p.add_subparsers(dest="command", required=True)
    fixtures = sub.add_parser("fixtures", help="Generate original synthetic manga")
    fixtures.add_argument("--output", required=True, type=_path)
    scan = sub.add_parser("scan", help="Read-only chapter discovery and page counts")
    scan.add_argument("--source", required=True, type=_path)
    generate = sub.add_parser("manifest", help="Create a candidate private-media bundle")
    generate.add_argument("--source", required=True, type=_path)
    generate.add_argument("--output", required=True, type=_path)
    generate.add_argument("--state-file", type=_path, default=Path(".manga-controller/ids.json"))
    generate.add_argument("--series-title")
    generate.add_argument("--direction", choices=["rtl", "ltr", "vertical"], default="rtl")
    generate.add_argument("--rights-json", type=_path)
    for name in ("inventory", "verify"):
        sub.add_parser(name, help="Inspect verified bundle").add_argument(
            "--bundle", required=True, type=_path
        )
    plan = sub.add_parser("plan-upload", help="Dry-run only against a local mock remote")
    plan.add_argument("--bundle", required=True, type=_path)
    plan.add_argument("--mock-dir", required=True, type=_path)
    mock = sub.add_parser("mock-upload", help="Approve local-only mock revision update")
    mock.add_argument("--bundle", required=True, type=_path)
    mock.add_argument("--mock-dir", required=True, type=_path)
    mock.add_argument(
        "--expected-revision", default="", help="Revision printed by plan-upload (empty for first commit)"
    )
    mock.add_argument("--approve", action="store_true")
    backup = sub.add_parser("backup", help="Create and verify immutable full-media backup")
    backup.add_argument("--bundle", required=True, type=_path)
    backup.add_argument("--output", required=True, type=_path)
    check = sub.add_parser("check-backup", help="Verify original bytes and index digests")
    check.add_argument("--backup", required=True, type=_path)
    restore = sub.add_parser("restore", help="Preview or approve non-destructive local restore")
    restore.add_argument("--backup", required=True, type=_path)
    restore.add_argument("--destination", required=True, type=_path)
    restore.add_argument("--approve", action="store_true")
    health = sub.add_parser(
        "hf-health", help="Optional read-only check of explicitly named private HF dataset"
    )
    health.add_argument("--repo-id", required=True)
    sub.add_parser("menu", help="Interactive Windows-friendly menu")
    return p


def run(args: argparse.Namespace) -> dict[str, Any]:
    cmd = args.command
    if cmd == "fixtures":
        return create_demo(args.output)
    if cmd == "scan":
        chapters = list(discover(args.source, Limits()))
        return {
            "status": "read-only",
            "chapters": len(chapters),
            "pages": sum(len(chapter.pages) for chapter in chapters),
            "sources": [{"chapter": chapter.key, "pages": len(chapter.pages)} for chapter in chapters],
        }
    if cmd == "manifest":
        return build(
            args.source, args.output, args.state_file, args.series_title, args.direction, args.rights_json
        )
    if cmd in ("inventory", "verify"):
        result = verify_bundle(args.bundle)
        if cmd == "inventory":
            result["catalogue"] = [
                {"id": e["id"], "chapters": len(e["chapters"])}
                for e in load_json(args.bundle / "catalogue.json")
            ]
        return result
    if cmd == "plan-upload":
        result = MockStorage(args.mock_dir).preview(args.bundle).as_json()
        result["remoteKind"] = "local-mock-only"
        return result
    if cmd == "mock-upload":
        revision = MockStorage(args.mock_dir).apply(args.bundle, args.expected_revision or None, args.approve)
        return {"revision": revision, "remoteKind": "local-mock-only"}
    if cmd == "backup":
        return create_backup(args.bundle, args.output)
    if cmd == "check-backup":
        return verify_backup(args.backup)
    if cmd == "restore":
        return restore_backup(args.backup, args.destination, args.approve)
    if cmd == "hf-health":
        return HuggingFaceReadOnly(args.repo_id).health()
    if cmd == "menu":
        interactive_menu()
        return {"status": "menu closed"}
    raise ControllerError(f"Unknown command: {cmd}")


def interactive_menu() -> None:
    actions = {
        "1": ("Generate synthetic manga", lambda: ["fixtures", "--output", input("New fixture folder: ")]),
        "2": ("Scan an input folder/archive", lambda: ["scan", "--source", input("Manga source: ")]),
        "3": (
            "Build candidate manifest and local media bundle",
            lambda: [
                "manifest",
                "--source",
                input("Manga source: "),
                "--output",
                input("New bundle folder: "),
            ],
        ),
        "4": ("Verify local bundle", lambda: ["verify", "--bundle", input("Bundle folder: ")]),
        "5": (
            "Preview mock upload",
            lambda: [
                "plan-upload",
                "--bundle",
                input("Bundle folder: "),
                "--mock-dir",
                input("Local mock directory: "),
            ],
        ),
        "6": (
            "Create verified full-media backup",
            lambda: [
                "backup",
                "--bundle",
                input("Bundle folder: "),
                "--output",
                input("New .zip destination: "),
            ],
        ),
        "7": (
            "Preview backup restoration",
            lambda: [
                "restore",
                "--backup",
                input("Backup .zip: "),
                "--destination",
                input("New restore folder: "),
            ],
        ),
        "8": ("Inspect bundle inventory", lambda: ["inventory", "--bundle", input("Bundle folder: ")]),
        "0": ("Exit", lambda: []),
    }
    while True:
        print("\nTaiyou Manga Storage Controller (offline mode)")
        for key, (title, _) in actions.items():
            print(f" {key}. {title}")
        choice = input("Choice: ").strip()
        if choice == "0":
            return
        action = actions.get(choice)
        if action is None:
            print("Invalid selection")
            continue
        try:
            argv = action[1]()
            print(json.dumps(run(parser().parse_args(argv)), indent=2, sort_keys=True))
        except (ControllerError, OSError, EOFError) as exc:
            print(f"ERROR: {exc}")


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        result = run(args)
        if args.command != "menu":
            print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (ControllerError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
