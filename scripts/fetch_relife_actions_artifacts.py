"""Download approved-source GitHub Actions artefacts to temporary runner storage.

This helper uses only the job's short-lived GITHUB_TOKEN. It never receives an
HF credential, uploads media, checks in files or follows untrusted redirects.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RUN_ID = 44547390262
SOURCE_REPO = "RichardDaffern/Manga-Retriever"
EXPECTED_NAMES = frozenset(
    f"ReLIFE-Original-Quality-Ch{start}-{min(222, start + 19)}"
    for start in range(1, 222, 20)
)
MAX_ARTIFACT_BYTES = 500_000_000
MAX_TOTAL_BYTES = 3_000_000_000
HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "Taiyou-Manga-Controller-Audit/1.0",
    "X-GitHub-Api-Version": "2022-11-28",
}


class SourceAccessError(ValueError):
    """Source artefact unavailable, unsafe or expired."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _valid_blob_url(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and parsed.port in (None, 443)
        and (
            host.endswith(".blob.core.windows.net")
            or host.endswith(".actions.githubusercontent.com")
            or host.endswith(".githubusercontent.com")
        )
    )


def _headers(token: str) -> dict[str, str]:
    return {**HEADERS, "Authorization": "Bearer " + token}


def _list_artifacts(token: str) -> list[dict[str, object]]:
    url = f"https://api.github.com/repos/{SOURCE_REPO}/actions/runs/{RUN_ID}/artifacts?per_page=100"
    request = urllib.request.Request(url, headers=_headers(token))
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (OSError, urllib.error.HTTPError, ValueError) as exc:
        raise SourceAccessError("Cannot list source GitHub Actions artefacts") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("artifacts"), list):
        raise SourceAccessError("Invalid GitHub Actions artefact listing")
    results = payload["artifacts"]
    if len(results) != 12:
        raise SourceAccessError("Expected exactly 12 source artefacts")
    for item in results:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            or item["name"] not in EXPECTED_NAMES
            or item.get("expired") is not False
            or type(item.get("size_in_bytes")) is not int
            or not 0 < item["size_in_bytes"] <= MAX_ARTIFACT_BYTES
            or not isinstance(item.get("id"), int)
        ):
            raise SourceAccessError("Unexpected, expired or oversized source artefact")
    names = [item["name"] for item in results]
    if len(set(names)) != len(EXPECTED_NAMES):
        raise SourceAccessError("Duplicate or missing source artefact batch")
    return results


def _signed_download_url(token: str, artifact_id: int) -> str:
    endpoint = f"https://api.github.com/repos/{SOURCE_REPO}/actions/artifacts/{artifact_id}/zip"
    request = urllib.request.Request(endpoint, headers=_headers(token))
    try:
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=30):
            raise SourceAccessError("Unexpected non-redirect from GitHub artifact API")
    except urllib.error.HTTPError as exc:
        if exc.code not in (302, 303):
            raise SourceAccessError("GitHub artefact download access denied or unavailable") from exc
        redirect = exc.headers.get("Location", "")
    if not _valid_blob_url(redirect):
        raise SourceAccessError("GitHub returned an untrusted artefact download origin")
    return redirect


def _stream_download(blob_url: str, destination: Path, expected_size: int) -> int:
    request = urllib.request.Request(blob_url, headers={"User-Agent": HEADERS["User-Agent"]})
    written = 0
    try:
        with urllib.request.urlopen(request, timeout=120) as source, destination.open("xb") as output:
            while data := source.read(1024 * 1024):
                written += len(data)
                if written > MAX_ARTIFACT_BYTES:
                    raise SourceAccessError("Artefact download exceeds per-file quota")
                output.write(data)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    if written != expected_size:
        destination.unlink(missing_ok=True)
        raise SourceAccessError("Downloaded artefact size does not match GitHub metadata")
    return written


def fetch_all(directory: Path, token: str) -> dict[str, int]:
    if not token:
        raise SourceAccessError("GITHUB_TOKEN is missing")
    if directory.exists() or directory.is_symlink():
        raise SourceAccessError("Source download destination already exists")
    artifacts = _list_artifacts(token)
    if sum(int(item["size_in_bytes"]) for item in artifacts) > MAX_TOTAL_BYTES:
        raise SourceAccessError("Total source artefacts exceed download quota")
    directory.mkdir(parents=True, exist_ok=False)
    downloaded = 0
    total = 0
    try:
        for item in sorted(artifacts, key=lambda record: str(record["name"])):
            url = _signed_download_url(token, int(item["id"]))
            safe_name = str(item["name"])
            if not re.fullmatch(r"ReLIFE-Original-Quality-Ch\d{1,3}-\d{1,3}", safe_name):
                raise SourceAccessError("Unexpected artifact name")
            bytes_received = _stream_download(
                url, directory / (safe_name + ".zip"), int(item["size_in_bytes"])
            )
            downloaded += 1
            total += bytes_received
            print(f"Read source artefact {downloaded}/12; cumulative bytes {total}")
    except Exception:
        shutil.rmtree(directory)
        raise
    return {"artefacts": downloaded, "bytes": total}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Temporary ReLIFE source-only download")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        info = fetch_all(args.output, os.getenv("GITHUB_TOKEN", ""))
        print(json.dumps(info, sort_keys=True))
    except (SourceAccessError, OSError, urllib.error.URLError) as exc:
        print(f"ReLIFE source download failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
