"""Windows-friendly private Hugging Face manga storage operations.

Mirrors Novel Controller's useful user workflows, without reusing EPUB
concepts or exposing dangerous whole-dataset deletion from the menu.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, cast

from .domain import ControllerError
from .hf_bulk import plan_upload, upload
from .hf_extra import chapters_report, compare_retriever, local_download_cleanup
from .hf_manage import (
    _csv_file,
    catalogue_backup,
    delete_apply,
    delete_preview,
    download_all,
    export_list,
    export_report,
    local_sync,
    restore_delisted,
    snapshot,
    title_conflicts,
)
from .hf_metadata import apply as apply_metadata
from .hf_metadata import preview as preview_metadata
from .metadata import completeness


def _path(value: str) -> Path:
    return Path(value).expanduser()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="taiyou-manga-manage",
        description="Safe, private manga storage controller tools",
    )
    subs = p.add_subparsers(dest="command", required=True)
    bulk = subs.add_parser("bulk-upload", help="Preview or apply verified manga bundles")
    bulk.add_argument("--source", required=True, type=_path)
    bulk.add_argument("--plan-file", required=True, type=_path)
    bulk.add_argument("--apply", action="store_true")
    bulk.add_argument("--approve", action="store_true")
    download = subs.add_parser("download", help="Back up all original manga pages as ZIP archives")
    download.add_argument("--destination", required=True, type=_path)
    download.add_argument("--manga-id")
    listing = subs.add_parser("list", help="Export all private manga catalogue records")
    listing.add_argument("--output", required=True, type=_path)
    conflict = subs.add_parser("conflicts", help="Detect duplicate titles or aliases")
    conflict.add_argument("--output", required=True, type=_path)
    verify = subs.add_parser("verify", help="Verify manga manifests, pages and covers")
    verify.add_argument("--mode", choices=["quick", "manifest", "deep"], default="quick")
    verify.add_argument("--output", required=True, type=_path)
    sync = subs.add_parser("sync", help="Compare verified local bundles with private catalogue")
    sync.add_argument("--bundles", required=True, type=_path)
    sync.add_argument("--output", required=True, type=_path)
    backup = subs.add_parser("backup-catalogue", help="Back up canonical private catalogue bytes")
    backup.add_argument("--output", required=True, type=_path)
    restore = subs.add_parser("restore", help="Re-list a previously de-listed manga without page writes")
    restore.add_argument("--manga-id", required=True)
    restore.add_argument("--source-revision", required=True)
    restore.add_argument("--plan-file", required=True, type=_path)
    restore.add_argument("--apply", action="store_true")
    restore.add_argument("--approve", action="store_true")
    delete = subs.add_parser("delete", help="De-list one manga reversibly, preserve all original media")
    delete.add_argument("--manga-id", required=True)
    delete.add_argument("--plan-file", required=True, type=_path)
    delete.add_argument("--apply", action="store_true")
    delete.add_argument("--approve", action="store_true")
    delete.add_argument("--confirm-title", default="")
    cover_upload = subs.add_parser("upload-covers", help="Preview or apply private manga cover ZIP")
    cover_upload.add_argument("--zip", required=True, type=_path)
    cover_upload.add_argument("--plan-file", required=True, type=_path)
    cover_upload.add_argument("--apply", action="store_true")
    cover_upload.add_argument("--approve", action="store_true")
    covers = subs.add_parser("covers", help="Report missing or present verified private covers")
    covers.add_argument("--output", required=True, type=_path)
    chapters = subs.add_parser("chapters", help="Export all manga chapters as CSV")
    chapters.add_argument("--output", required=True, type=_path)
    retriever = subs.add_parser("compare-retriever", help="Compare a local manga inventory")
    retriever.add_argument("--inventory", required=True, type=_path)
    retriever.add_argument("--output", required=True, type=_path)
    health = subs.add_parser("health", help="Create local HTML/JSON/CSV manga health report")
    health.add_argument("--mode", choices=["quick", "manifest", "deep"], default="quick")
    health.add_argument("--output", required=True, type=_path)
    missing = subs.add_parser("metadata-report", help="Read-only report of missing publication metadata")
    missing.add_argument("--output", required=True, type=_path)
    metadata = subs.add_parser("metadata", help="Preview or apply approved publication metadata")
    metadata.add_argument("--candidates", required=True, type=_path)
    metadata.add_argument("--plan-file", required=True, type=_path)
    metadata.add_argument("--apply", action="store_true")
    metadata.add_argument("--approve", action="store_true")
    cleanup = subs.add_parser("cleanup", help="Preview/remove only old local .part download files")
    cleanup.add_argument("--destination", required=True, type=_path)
    cleanup.add_argument("--output", required=True, type=_path)
    cleanup.add_argument("--older-than-days", type=int, default=7)
    cleanup.add_argument("--apply", action="store_true")
    cleanup.add_argument("--confirm", default="")
    subs.add_parser("menu", help="Novel-style Windows command menu")
    return p


def run(args: argparse.Namespace) -> dict[str, Any]:
    cmd = args.command
    if cmd == "menu":
        interactive_menu()
        return {"status": "menu-closed"}
    token = os.getenv("HF_TOKEN", "")
    if cmd != "cleanup" and not token:
        raise ControllerError(
            "Set HF_TOKEN in your private environment; never place tokens in repository files"
        )
    if cmd == "bulk-upload":
        if args.apply:
            return upload(token, args.source, args.plan_file, approve=args.approve)
        return plan_upload(token, args.source, args.plan_file)
    if cmd == "download":
        return download_all(token, args.destination, manga_id=args.manga_id)
    if cmd == "list":
        return export_list(token, args.output)
    if cmd == "conflicts":
        _, sha, _, _, entries = snapshot(token)
        rows = title_conflicts(entries)
        _csv_file(
            args.output,
            [
                {
                    "normalisedTitle": row["normalisedTitle"],
                    "mangaIds": ", ".join(cast(list[str], row["mangaIds"])),
                    "count": row["count"],
                }
                for row in rows
            ],
            ["normalisedTitle", "mangaIds", "count"],
        )
        return {"status": "conflicts-report", "revision": sha, "pairs": len(rows), "report": str(args.output)}
    if cmd == "upload-covers":
        from .hf_cover_zip import cover_zip_upload

        if args.apply and not args.approve:
            raise ControllerError("Cover ZIP upload requires both --apply and --approve")
        return cover_zip_upload(token, args.zip, args.plan_file, approve=args.apply and args.approve)
    if cmd in ("verify", "health", "covers"):
        return export_report(token, args.output, depth="quick" if cmd == "covers" else args.mode)
    if cmd == "sync":
        return local_sync(token, args.bundles, args.output)
    if cmd == "backup-catalogue":
        return catalogue_backup(token, args.output)
    if cmd == "restore":
        if args.apply and not args.approve:
            raise ControllerError("Restoration requires --apply and --approve")
        return restore_delisted(
            token,
            args.manga_id,
            args.source_revision,
            args.plan_file,
            approve=args.apply and args.approve,
        )
    if cmd == "delete":
        if args.apply:
            if not args.approve:
                raise ControllerError("De-listing requires --apply and --approve")
            return delete_apply(token, args.manga_id, args.plan_file, args.confirm_title)
        return delete_preview(token, args.manga_id, args.plan_file)
    if cmd == "chapters":
        return chapters_report(token, args.output)
    if cmd == "compare-retriever":
        return compare_retriever(token, args.inventory, args.output)
    if cmd == "metadata-report":
        _, sha, _, _, entries = snapshot(token)
        result = completeness(entries)
        from .hf_manage import _json_data, _new_file

        result["revision"] = sha
        _new_file(args.output, _json_data(result))
        return {
            "status": "metadata-report",
            "revision": sha,
            "complete": result["complete"],
            "manga": result["series"],
            "report": str(args.output),
        }
    if cmd == "metadata":
        from .hf_metadata import _api

        api = _api(token)
        if args.apply:
            return apply_metadata(api, token, args.candidates, args.plan_file, approve=args.approve)
        result = preview_metadata(api, token, args.candidates)
        from .hf_manage import _json_data, _new_file

        _new_file(args.plan_file, _json_data(result))
        return result
    if cmd == "cleanup":
        return local_download_cleanup(
            args.destination,
            args.output,
            apply=args.apply,
            confirm=args.confirm,
            older_than_days=args.older_than_days,
        )
    raise ControllerError("Unknown private manga operation")


def interactive_menu() -> None:
    actions = {
        "1": "Smart bulk upload (verify bundles, preview, approve)",
        "2": "Download all manga as original-image ZIPs",
        "3": "List all manga in private Hugging Face",
        "4": "Detect duplicate titles or aliases",
        "5": "Verify catalogue/manifests/media integrity",
        "6": "Compare local manga bundles with cloud (sync status)",
        "7": "Back up canonical catalogue",
        "8": "Restore a previously de-listed manga",
        "9": "Delete one manga from catalogue (reversible, media retained)",
        "10": "Review/upload actual manga covers and metadata",
        "11": "Full dataset wipe DISABLED (safety)",
        "12": "Export manga chapter inventory",
        "13": "Audit missing manga covers",
        "14": "Compare Manga Retriever inventory",
        "15": "Create private library health dashboard",
        "16": "Audit missing chapter manifests",
        "17": "Clean old LOCAL temporary downloads",
        "18": "Audit or repair publication metadata",
        "19": "Back up all manga media (download all)",
        "20": "Original offline manga tools",
        "0": "Exit",
    }

    def ask(message: str) -> str:
        return input(message + ": ").strip()

    def invoke(arguments: list[str]) -> None:
        parsed = parser().parse_args(arguments)
        print(json.dumps(run(parsed), indent=2, sort_keys=True))

    while True:
        print("\nTaiyou Manga Storage Controller | Private Hugging Face")
        for number, title in actions.items():
            print(f" {number:>2}. {title}")
        choice = ask("Choice")
        if choice == "0":
            return
        try:
            if choice == "1":
                source = ask("Local verified manga bundle(s) directory")
                plan = ask("NEW private preview JSON path (e.g. reports/upload-plan.json)")
                invoke(["bulk-upload", "--source", source, "--plan-file", plan])
                if ask("After reviewing preview, type APPROVE to run") == "APPROVE":
                    invoke(
                        [
                            "bulk-upload",
                            "--source",
                            source,
                            "--plan-file",
                            plan,
                            "--apply",
                            "--approve",
                        ]
                    )
            elif choice in ("2", "19"):
                invoke(["download", "--destination", ask("Private download folder (e.g. downloads)")])
            elif choice == "3":
                invoke(["list", "--output", ask("NEW private CSV path (e.g. reports/manga-list.csv)")])
            elif choice == "4":
                invoke(["conflicts", "--output", ask("NEW conflict CSV path")])
            elif choice in ("5", "16"):
                mode = "manifest" if choice == "16" else (ask("Mode (quick/manifest/deep)") or "quick")
                invoke(["verify", "--mode", mode, "--output", ask("NEW report JSON path")])
            elif choice == "6":
                invoke(
                    [
                        "sync",
                        "--bundles",
                        ask("Local bundles directory"),
                        "--output",
                        ask("NEW sync CSV path"),
                    ]
                )
            elif choice == "7":
                invoke(["backup-catalogue", "--output", ask("NEW private library.json path")])
            elif choice == "8":
                manga = ask("Immutable manga ID")
                source = ask("Original 40-character backup revision")
                plan = ask("NEW restore preview JSON path")
                invoke(["restore", "--manga-id", manga, "--source-revision", source, "--plan-file", plan])
                if ask("After reviewing plan, type RESTORE") == "RESTORE":
                    invoke(
                        [
                            "restore",
                            "--manga-id",
                            manga,
                            "--source-revision",
                            source,
                            "--plan-file",
                            plan,
                            "--apply",
                            "--approve",
                        ]
                    )
            elif choice == "9":
                manga = ask("Immutable manga ID")
                plan = ask("NEW de-list preview JSON path")
                proposal = run(parser().parse_args(["delete", "--manga-id", manga, "--plan-file", plan]))
                print(json.dumps(proposal, indent=2))
                title = ask("Type EXACT displayed title to de-list (pages retained)")
                if title == proposal["title"]:
                    invoke(
                        [
                            "delete",
                            "--manga-id",
                            manga,
                            "--plan-file",
                            plan,
                            "--apply",
                            "--approve",
                            "--confirm-title",
                            title,
                        ]
                    )
            elif choice == "10":
                source = ask("Private cover ZIP, or candidate metadata.json")
                plan = ask("NEW metadata and cover preview JSON path")
                command = (
                    ["upload-covers", "--zip", source, "--plan-file", plan]
                    if source.lower().endswith(".zip")
                    else ["metadata", "--candidates", source, "--plan-file", plan]
                )
                invoke(command)
                if ask("After reviewing preview, type APPROVE") == "APPROVE":
                    invoke([*command, "--apply", "--approve"])
            elif choice == "11":
                print("Whole-dataset deletion is disabled. Use reversible single-manga de-list instead.")
            elif choice == "12":
                invoke(["chapters", "--output", ask("NEW chapter inventory CSV path")])
            elif choice == "13":
                invoke(["covers", "--output", ask("NEW missing-cover CSV path")])
            elif choice == "14":
                invoke(
                    [
                        "compare-retriever",
                        "--inventory",
                        ask("Local Retriever JSON file"),
                        "--output",
                        ask("NEW comparison CSV path"),
                    ]
                )
            elif choice == "15":
                invoke(["health", "--mode", "quick", "--output", ask("NEW local health HTML path")])
            elif choice == "17":
                destination = ask("Local downloads folder")
                report = ask("NEW cleanup preview JSON path")
                invoke(["cleanup", "--destination", destination, "--output", report])
                if ask("To remove old LOCAL .part files, type DELETE OLD LOCAL TEMP FILES") == (
                    "DELETE OLD LOCAL TEMP FILES"
                ):
                    invoke(
                        [
                            "cleanup",
                            "--destination",
                            destination,
                            "--output",
                            report,
                            "--apply",
                            "--confirm",
                            "DELETE OLD LOCAL TEMP FILES",
                        ]
                    )
            elif choice == "18":
                invoke(["metadata-report", "--output", ask("NEW metadata report JSON path")])
                if ask("Do you also have candidates to reconcile? (yes/no)") == "yes":
                    source = ask("Private candidate JSON file")
                    plan = ask("NEW reconciliation preview JSON path")
                    invoke(["metadata", "--candidates", source, "--plan-file", plan])
                    if ask("After review, type APPROVE") == "APPROVE":
                        invoke(
                            ["metadata", "--candidates", source, "--plan-file", plan, "--apply", "--approve"]
                        )
            elif choice == "20":
                from .cli import interactive_menu as original

                original()
            else:
                print("Invalid selection")
        except (ControllerError, OSError, ValueError, EOFError) as exc:
            print(f"ERROR: {exc}")


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        result = run(args)
        if args.command != "menu":
            print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (ControllerError, OSError, ValueError) as exc:
        print(f"Manga controller operation refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
