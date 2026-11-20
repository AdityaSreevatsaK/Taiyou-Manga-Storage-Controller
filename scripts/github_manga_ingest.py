"""Owner-triggered GitHub Actions import from immutable *private* HF staging.

A public GitHub repository never receives manga pages, cover bytes or an
uploaded source artifact. The only public command is an opaque staging ticket.
A preview fingerprint pins the exact dataset revision and complete source.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from taiyou_manga.builder import load_json, verify_bundle
from taiyou_manga.domain import ControllerError
from taiyou_manga.hf_bulk import plan_upload, prepare_plan, upload
from taiyou_manga.hf_manage import quick_integrity, snapshot
from taiyou_manga.hf_metadata import _api, apply as apply_metadata, preview as preview_metadata
from taiyou_manga.hf_upload import DATASET
from taiyou_manga.metadata import load_candidates, reconcile
from taiyou_manga.hf_layout import canonical_library

ROOT = "ingest/agent-queue"
QUEUE_ISSUE_TITLE = "Private manga import queue"
OWNER = "AdityaSreevatsaK"
COMMAND = re.compile(
    r"^/manga-import (?P<ticket>[0-9a-f]{32}) (?P<phase>preview|apply)"
    r"(?: (?P<revision>[0-9a-f]{40}) (?P<fingerprint>[0-9a-f]{64}))?$"
)
TICKET_RE = re.compile(r"^[0-9a-f]{32}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_PACKAGE_BYTES = 5_000_000_000
MAX_FILES = 5500
MAX_STAGE_MANIFEST = 32_000


def _fail(message: str) -> None:
    raise ControllerError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_event(event: dict[str, Any], name: str, actor: str, ref: str) -> dict[str, str]:
    """Reject untrusted comments before any token or private data is accessed."""
    if actor != OWNER or ref != "refs/heads/master":
        _fail("Only the repository owner on master may start a private manga import")
    if name == "issue_comment":
        issue = event.get("issue")
        comment = event.get("comment")
        if (
            not isinstance(issue, dict)
            or issue.get("title") != QUEUE_ISSUE_TITLE
            or issue.get("pull_request") is not None
            or not isinstance(comment, dict)
            or not isinstance(comment.get("body"), str)
            or comment.get("user", {}).get("login") != OWNER
        ):
            _fail("An owner comment on the dedicated import queue is required")
        match = COMMAND.fullmatch(comment["body"].strip())
        if not match:
            _fail("Malformed private import command")
        values = {name: (value or "") for name, value in match.groupdict().items()}
    elif name == "workflow_dispatch":
        values = event.get("inputs", {})
        if not isinstance(values, dict):
            _fail("Malformed manual import inputs")
        values = {key: str(values.get(key, "") or "") for key in ("ticket", "phase", "revision", "fingerprint")}
    else:
        _fail("Unsupported GitHub event")
    if not TICKET_RE.fullmatch(values["ticket"]) or values["phase"] not in ("preview", "apply"):
        _fail("Invalid private manga ticket or phase")
    if values["phase"] == "preview":
        if values["revision"] or values["fingerprint"]:
            _fail("Read-only preview must not carry approval credentials")
    elif not HEX40.fullmatch(values["revision"]) or not HEX64.fullmatch(values["fingerprint"]):
        _fail("Apply requires the exact revision and fingerprint from its preview")
    return values


def _read_stage(token: str, ticket: str) -> tuple[Path, dict[str, Any], str]:
    from huggingface_hub import hf_hub_download

    api = _api(token)
    info = api.dataset_info(DATASET, token=token)
    if info.private is not True or not isinstance(info.sha, str):
        _fail("Private staging dataset is unavailable or not private")
    revision = info.sha
    prefix = f"{ROOT}/{ticket}"
    manifest_path = Path(
        hf_hub_download(
            repo_id=DATASET,
            filename=f"{prefix}/manifest.json",
            repo_type="dataset",
            revision=revision,
            token=token,
        )
    )
    if manifest_path.stat().st_size > MAX_STAGE_MANIFEST:
        _fail("Private stage manifest exceeds size limits")
    manifest = json.loads(manifest_path.read_bytes())
    if (
        not isinstance(manifest, dict)
        or manifest.get("schemaVersion") != 1
        or manifest.get("kind") != "private-manga-github-stage"
        or manifest.get("ticket") != ticket
        or not isinstance(manifest.get("packageBytes"), int)
        or not 0 < manifest["packageBytes"] <= MAX_PACKAGE_BYTES
        or not isinstance(manifest.get("packageSha256"), str)
        or not HEX64.fullmatch(manifest["packageSha256"])
    ):
        _fail("Invalid or mismatched private staging receipt")
    package = Path(
        hf_hub_download(
            repo_id=DATASET,
            filename=f"{prefix}/package.zip",
            repo_type="dataset",
            revision=revision,
            token=token,
        )
    )
    if package.stat().st_size != manifest["packageBytes"] or sha256_file(package) != manifest["packageSha256"]:
        _fail("Staged manga package bytes do not match its immutable receipt")
    return package, manifest, revision


def extract_private_package(archive: Path, destination: Path) -> tuple[Path, Path]:
    """Bounded extraction of one verified candidate bundle and metadata package."""
    with zipfile.ZipFile(archive) as source:
        members = source.infolist()
        if not 1 <= len(members) <= MAX_FILES:
            _fail("Private manga stage contains too many files")
        seen: set[str] = set()
        total = 0
        for item in members:
            name = item.filename
            parts = PurePosixPath(name).parts
            if (
                not name
                or name.startswith("/")
                or "\\" in name
                or ":" in name
                or "\x00" in name
                or any(part in ("", ".", "..") for part in parts)
                or len(parts) < 2
                or parts[0] not in ("bundle", "metadata")
                or item.is_dir()
                or item.flag_bits & 1
            ):
                _fail("Unsafe private manga staging ZIP path")
            mode = item.external_attr >> 16
            if stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                _fail("Private manga ZIP contains a symlink or unsupported file type")
            key = name.casefold()
            if key in seen:
                _fail("Duplicate private manga staging ZIP path")
            seen.add(key)
            if item.file_size <= 0:
                _fail("Private manga staging ZIP contains an empty file")
            if item.file_size > max(1, item.compress_size) * 250:
                _fail("Private manga stage compression ratio exceeds limit")
            total += item.file_size
            if total > MAX_PACKAGE_BYTES:
                _fail("Private manga stage exceeds import size limit")
            target = destination.joinpath(*parts)
            if not target.resolve().is_relative_to(destination.resolve()):
                _fail("Private manga staging path escapes extraction directory")
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(item) as reader, target.open("xb") as writer:
                count = 0
                while chunk := reader.read(1024 * 1024):
                    count += len(chunk)
                    if count > item.file_size:
                        _fail("Private source grew during extraction")
                    writer.write(chunk)
                if count != item.file_size:
                    _fail("Incomplete original manga source in staged package")

    bundle = destination / "bundle"
    candidate = destination / "metadata" / "candidates.json"
    if not (bundle / "catalogue.json").is_file() or not candidate.is_file():
        _fail("Staged package is missing its verified manga bundle or candidates")
    return bundle, candidate


def _preflight(
    bundle: Path, candidate: Path, stage_manifest: dict[str, Any],
    revision: str, files: set[str], catalogue: bytes, old: list[dict[str, Any]]
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    candidate_rows, candidate_sha = load_candidates(candidate)
    verified = verify_bundle(bundle)
    entries = load_json(bundle / "catalogue.json")
    if len(entries) != 1 or len(candidate_rows) != 1:
        _fail("Expected one verified manga and one metadata source candidate")
    entry = entries[0]
    if (
        entry["id"] != stage_manifest.get("mangaId")
        or verified["pages"] != stage_manifest.get("pages")
        or verified["chapters"] != stage_manifest.get("chapters")
        or candidate_sha != stage_manifest.get("metadataSha256")
        or candidate_rows[0].get("mangaId") != entry["id"]
    ):
        _fail("Staged manga identity, page count or metadata changed")
    plan, _ = prepare_plan(bundle, revision, files, catalogue, old)
    if plan["status"] != "ready" or plan["new"] not in (0, 1):
        _fail("Private manga source conflicts with an existing title, ID or media path")
    prospective = old if plan["new"] == 0 else [*old, entry]
    amended, covers, changes, conflicts = reconcile(prospective, candidate_rows, candidate.parent, files)
    if conflicts:
        _fail("Private publication metadata conflicts with existing manual fields")
    canonical_library(amended)
    extra = {
        "metadataChanges": len(changes),
        "coverCount": len(covers),
        "coverDigests": sorted([sha256_file(path) for path in covers.values()]),
        "candidateSha256": candidate_sha,
        "stagePackageSha256": stage_manifest["packageSha256"],
    }
    signature = hashlib.sha256(
        json.dumps({"plan": plan, "extra": extra}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return plan, signature, extra


def execute(token: str, values: dict[str, str]) -> dict[str, Any]:
    package, manifest, _stage_revision = _read_stage(token, values["ticket"])
    with tempfile.TemporaryDirectory(prefix="taiyou-remote-ingest-") as directory:
        root = Path(directory)
        bundle, candidate = extract_private_package(package, root)
        api, revision, files, catalogue, old = snapshot(token)
        plan, signature, extra = _preflight(bundle, candidate, manifest, revision, files, catalogue, old)
        summary: dict[str, Any] = {
            "status": "preview-ready",
            "ticket": values["ticket"],
            "expectedRevision": revision,
            "approvalFingerprint": signature,
            "newManga": plan["new"],
            "alreadyListed": plan["unchanged"],
            "chapters": manifest["chapters"],
            "pages": manifest["pages"],
            "metadataFieldsToAdd": extra["metadataChanges"],
            "coverUploads": extra["coverCount"],
            "existingMangaCount": len(old),
            "privateSource": True,
            "publicArtifacts": 0,
            "deleteOperations": 0,
        }
        if values["phase"] == "preview":
            return summary
        if values["revision"] != revision or values["fingerprint"] != signature:
            _fail("Approval fingerprint or private dataset revision changed: obtain a new preview")
        # The exact pinned, conflict-free preview is required to call the
        # existing revision-guarded append-only writer.
        approved = root / "approved-upload-plan.json"
        approved.write_text(json.dumps(plan, sort_keys=True) + "\n", encoding="utf-8")
        # Suppress sensitive title/ID logs from lower-level upload operations
        # in this public GitHub Actions repository.
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()):
            result = upload(token, bundle, approved, approve=True)
        metadata_plan = preview_metadata(_api(token), token, candidate)
        if metadata_plan["status"] == "conflict":
            _fail("Manga pages were published, but protected metadata fields need review")
        if metadata_plan["status"] == "ready":
            file = root / "approved-metadata-plan.json"
            file.write_text(json.dumps(metadata_plan, sort_keys=True) + "\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                apply_metadata(_api(token), token, candidate, file, approve=True)
        elif metadata_plan["status"] != "no-op":
            _fail("Unexpected metadata publication state")
        _, new_revision, current_files, _, current = snapshot(token)
        target_id = manifest["mangaId"]
        matches = [row for row in current if row["id"] == target_id]
        if len(matches) != 1:
            _fail("Published manga identity missing after private commit")
        final = matches[0]
        if (
            len(final["chapters"]) != manifest["chapters"]
            or sum(ch["pageCount"] for ch in final["chapters"]) != manifest["pages"]
        ):
            _fail("Published manga chapter/page counts do not match staged originals")
        if any(
            next((entry for entry in current if entry["id"] == prior["id"]), None) != prior
            for prior in old if prior["id"] != target_id
        ):
            _fail("A pre-existing, unrelated manga record changed during import")
        integrity = quick_integrity(current, current_files)
        if not integrity["complete"]:
            _fail("Post-publication private manga integrity check failed")
        return {
            "status": "private-canonical-upload-verified",
            "ticket": values["ticket"],
            "revision": new_revision,
            "uploadedNew": result["uploaded"],
            "chapters": manifest["chapters"],
            "pages": manifest["pages"],
            "coverPresent": bool(final.get("cover")),
            "metadataPresent": bool(final.get("synopsis") and final.get("creators")),
            "preExistingMangaPreserved": len(old) - int(target_id in {e["id"] for e in old}),
            "publicArtifacts": 0,
            "mediaDeleted": 0,
        }


def main() -> int:
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes())
        values = parse_event(
            event,
            os.environ.get("GITHUB_EVENT_NAME", ""),
            os.environ.get("GITHUB_ACTOR", ""),
            os.environ.get("GITHUB_REF", ""),
        )
        token = os.environ.get("HF_TOKEN", "")
        if not token:
            _fail("Protected private HF token is not configured")
        result = execute(token, values)
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0
    except (ControllerError, KeyError, ValueError, OSError, zipfile.BadZipFile) as exc:
        # Never print private titles, full filesystem paths or HF media URLs.
        print(f"PRIVATE_MANGA_IMPORT_REFUSED: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
