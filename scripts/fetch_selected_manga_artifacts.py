"""Owner-approved sources only: download exact original-quality manga action ZIPs."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from taiyou_manga.domain import ControllerError
from taiyou_manga.selected_titles import TITLES, selected_title

SOURCE_REPO = "RichardDaffern/Manga-Retriever"


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
    artifacts = [
        a for a in data["artifacts"] if isinstance(a, dict) and a.get("name") in title.artifact_names
    ]
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
