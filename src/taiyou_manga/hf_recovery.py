"""Private ReLIFE full-revision recovery ref before migrating any original media.

Creating a branch pointing to the exact pre-migration HEAD retains the full
Git/Xet snapshot, but is not an independent off-platform media backup.
No files are moved, overwritten, re-uploaded or removed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .domain import ControllerError
from .hf_layout import read_legacy_preview

DATASET = "AdityaSreevatsaK/Taiyous-Manga"
BACKUP_BRANCH = "backup/relife-before-layout-migration-20261120"
REQUIRED_RELIFE_SERIES = 1
REQUIRED_CHAPTERS = 237
REQUIRED_PAGES = 5606


def create_recovery_ref(token: str, *, apply: bool) -> dict[str, object]:
    from huggingface_hub import HfApi

    plan = read_legacy_preview(DATASET, token)
    if (
        plan["series"] != REQUIRED_RELIFE_SERIES
        or plan["chapters"] != REQUIRED_CHAPTERS
        or plan["pages"] != REQUIRED_PAGES
    ):
        raise ControllerError("Existing ReLIFE inventory differs from uploaded verified baseline")
    expected = str(plan["expectedRevision"])
    api = HfApi(token=token)
    references = api.list_repo_refs(DATASET, repo_type="dataset", token=token)
    matches = [ref for ref in references.branches if ref.name == BACKUP_BRANCH]
    if len(matches) > 1:
        raise ControllerError("Multiple ambiguous pre-migration recovery branches exist")
    if matches:
        if matches[0].target_commit != expected:
            raise ControllerError("Recovery branch already refers to a different original revision")
        status = "already-protected"
    elif apply:
        # Branch creation is the only mutation here; it does not modify main.
        api.create_branch(
            repo_id=DATASET,
            branch=BACKUP_BRANCH,
            revision=expected,
            repo_type="dataset",
            token=token,
            exist_ok=False,
        )
        status = "recovery-branch-created"
    else:
        status = "recovery-branch-proposed"
    if apply or matches:
        pinned = api.dataset_info(DATASET, token=token, revision=BACKUP_BRANCH)
        if pinned.private is not True or pinned.sha != expected:
            raise ControllerError("Private HF recovery branch failed pinned revision validation")
        before = set(api.list_repo_files(DATASET, repo_type="dataset", revision=expected, token=token))
        after = set(api.list_repo_files(DATASET, repo_type="dataset", revision=BACKUP_BRANCH, token=token))
        if before != after:
            raise ControllerError("Recovery branch file inventory is not identical to original revision")
    return {
        "status": status,
        "datasetPrivate": True,
        "recoveryBranch": BACKUP_BRANCH,
        "protectedRevision": expected,
        "files": plan["filesToCopyWithoutDeletingLegacy"],
        "verifiedChapters": REQUIRED_CHAPTERS,
        "verifiedPages": REQUIRED_PAGES,
        "mainModified": False,
        "independentOffPlatformBackup": False,
        "migrationEnabled": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Pin full private ReLIFE revision before layout migration")
    parser.add_argument("--create-recovery-ref", action="store_true")
    args = parser.parse_args()
    try:
        result = create_recovery_ref(os.environ.get("HF_TOKEN", ""), apply=args.create_recovery_ref)
    except (ControllerError, OSError, ValueError) as exc:
        print(f"Private recovery guard refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
