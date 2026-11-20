"""Allowlisted GitHub Actions source runs for four explicitly approved manga.

The Downloader source run may include failed jobs for other manga; only successful,
individually audited batch artifacts belonging to the selected slug are imported.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .domain import ControllerError
from .relife_intake import EXPECTED_PAGES as RELIFE_EXPECTED_PAGES
from .relife_stage import _stable_registry as _relife_registry

SOURCE_REPO = "RichardDaffern/Manga-Retriever"


@dataclass(frozen=True)
class SelectedTitle:
    slug: str
    name: str
    run_id: int
    main_chapters: int
    audited_pages: int
    prefix: str
    source_id: str

    @property
    def ranges(self) -> list[tuple[int, int]]:
        return [(start, min(start + 19, self.main_chapters)) for start in range(1, self.main_chapters + 1, 20)]

    @property
    def artifact_names(self) -> set[str]:
        return {f"{self.prefix}{start}-{end}" for start, end in self.ranges}


TITLES = {
    "maid-sama": SelectedTitle(
        "maid-sama", "Kaichou wa Maid-sama!", 44587087000, 85, 3415,
        "Manga-maid-sama-Original-Ch", "d5e2bd89-e300-4262-a799-fb4f79bdb777",
    ),
    "last-game": SelectedTitle(
        "last-game", "Last Game", 44587087000, 56, 2022,
        "Manga-last-game-Original-Ch", "32600d3f-a43a-4f90-8a4e-c4e09f35c99b",
    ),
    "love-so-life": SelectedTitle(
        "love-so-life", "Love So Life", 44597036262, 106, 3326,
        "LoveSoLife-Original-Ch", "911a12ae-1022-448e-9219-b7b294d7fb3e",
    ),
    "onizuka-sawarida": SelectedTitle(
        "onizuka-sawarida", "Onizuka-chan and Sawarida-kun", 44675324997, 49, 274,
        "Onizuka-Original-Ch", "96b87943-6458-4045-a029-d3185d5cea57",
    ),
}


def selected_title(slug: str) -> SelectedTitle:
    if slug not in TITLES:
        raise ControllerError("Title not approved for private selected manga import")
    return TITLES[slug]


def selected_source_artifacts(slug: str, *, token: str) -> list[dict[str, object]]:
    """Require exactly one available original uploader-quality artifact per expected range."""
    from scripts.fetch_relife_actions_artifacts import _headers  # public Controller source-only helper

    title = selected_title(slug)
    if not token:
        raise ControllerError("GitHub Actions token missing for source downloads")
    url = f"https://api.github.com/repos/{SOURCE_REPO}/actions/runs/{title.run_id}/artifacts?per_page=100"
    try:
        with urllib.request.urlopen(  # noqa: S310 - fixed allowlisted GitHub HTTPS URL
            urllib.request.Request(url, headers=_headers(token)), timeout=30
        ) as response:
            data = json.load(response)
    except (OSError, ValueError) as exc:
        raise ControllerError("Cannot read authorised GitHub Actions source run") from exc
    if not isinstance(data, dict) or not isinstance(data.get("artifacts"), list):
        raise ControllerError("Invalid GitHub Actions artifact inventory")
    artifacts = [a for a in data["artifacts"] if isinstance(a, dict) and a.get("name") in title.artifact_names]
    names = [a["name"] for a in artifacts]
    if len(artifacts) != len(title.ranges) or set(names) != title.artifact_names:
        raise ControllerError("Selected manga source run lacks one or more expected batches")
    for item in artifacts:
        if (
            item.get("expired") is not False
            or not isinstance(item.get("id"), int)
            or type(item.get("size_in_bytes")) is not int
            or not 0 < item["size_in_bytes"] <= 500_000_000
        ):
            raise ControllerError("Selected manga artifact expired or has unsafe metadata")
    if sum(int(item["size_in_bytes"]) for item in artifacts) > 3_000_000_000:
        raise ControllerError("Selected manga artifact download exceeds total size budget")
    return sorted(artifacts, key=lambda item: str(item["name"]))


def download_selected_artifacts(slug: str, output: Path, *, token: str) -> dict[str, object]:
    """Download a single selected title, never unrelated manga from a shared run."""
    import shutil

    from scripts.fetch_relife_actions_artifacts import _signed_download_url, _stream_download

    title = selected_title(slug)
    if output.exists() or output.is_symlink():
        raise ControllerError("Temporary selected-title source directory already exists")
    artifacts = selected_source_artifacts(slug, token=token)
    output.mkdir(parents=True)
    total = 0
    try:
        for index, item in enumerate(artifacts, start=1):
            name = str(item["name"])
            url = _signed_download_url(token, int(item["id"]))
            total += _stream_download(url, output / (name + ".zip"), int(item["size_in_bytes"]))
            print(f"Fetched verified {slug} source batch {index}/{len(artifacts)}", flush=True)
    except Exception:
        shutil.rmtree(output)
        raise
    return {"title": title.name, "runId": title.run_id, "artifacts": len(artifacts), "bytes": total}


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Download only selected original-quality manga artifacts")
    parser.add_argument("--slug", choices=tuple(TITLES), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = download_selected_artifacts(args.slug, args.output, token=os.getenv("GITHUB_TOKEN", ""))
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ControllerError, OSError, urllib.error.URLError) as exc:
        print(f"Selected manga fetch refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
