"""Convert independently verified ReLIFE source artefacts to a private local candidate.

Only the 237 audited CBZ members are copied to a temporary source tree.
Their original bytes are checked against the Retriever's SHA-256 records.
The generic Controller then builds and verifies the single-series candidate.

This module NEVER uploads media or creates an approved HF production layout.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Any

from .builder import build, verify_bundle
from .domain import ControllerError
from .relife_intake import (
    ARTIFACT_RE,
    EXPECTED_CHAPTERS,
    EXPECTED_PAGES,
    _chapter_from_name,
    audit_relife_artifacts,
)

MAX_CBZ_BYTES = 500_000_000


def _chapter_label(chapter: str) -> str:
    value = Decimal(chapter)
    return f"Chapter {format(value, 'f')}"


def _copy_verified_cbz(
    archive: zipfile.ZipFile, member: str, output: Path, sha256: str, expected_bytes: int
) -> None:
    if output.exists() or output.is_symlink():
        raise ControllerError("Duplicate normalised ReLIFE chapter path")
    digest = hashlib.sha256()
    total = 0
    with archive.open(member) as source, output.open("xb") as target:
        while block := source.read(1024 * 1024):
            total += len(block)
            if total > MAX_CBZ_BYTES:
                raise ControllerError("ReLIFE chapter exceeds size budget")
            digest.update(block)
            target.write(block)
    if total != expected_bytes or digest.hexdigest() != sha256:
        raise ControllerError("ReLIFE chapter changed since preflight")


def stage_relife_candidate(
    artifact_dir: Path, output: Path, registry_file: Path, *, require_complete: bool = True
) -> dict[str, Any]:
    """Build locally with new provisional opaque IDs; no public or cloud publication."""
    if output.exists() or output.is_symlink():
        raise ControllerError("Candidate output already exists")
    if registry_file.exists() or registry_file.is_symlink():
        raise ControllerError("Provisional ReLIFE registry destination already exists")
    root = artifact_dir.resolve()
    if output.resolve().is_relative_to(root) or registry_file.resolve().is_relative_to(root):
        raise ControllerError("Output and identity registry must be outside the source artefacts")
    if registry_file.resolve().is_relative_to(output.resolve()):
        raise ControllerError("Identity registry must be outside candidate output")
    validation = audit_relife_artifacts(
        artifact_dir, deep_verify=True, require_complete=require_complete
    )
    if validation["status"] != "verified-content" or validation["readyForUpload"]:
        raise ControllerError("ReLIFE source validation did not meet local integrity gate")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".relife-intake-", dir=output.parent) as workspace:
        source_root = Path(workspace) / "source"
        chapters = source_root / "ReLIFE"
        chapters.mkdir(parents=True)
        seen: set[str] = set()
        for artifact in sorted(artifact_dir.iterdir(), key=lambda path: path.name):
            if ARTIFACT_RE.fullmatch(artifact.name) is None:
                raise ControllerError("Unexpected outer ReLIFE source artefact")
            with zipfile.ZipFile(artifact) as archive:
                try:
                    report = json.loads(archive.read("relife_quality_audit.json"))
                except (KeyError, ValueError) as exc:
                    raise ControllerError("Cannot read already-validated ReLIFE audit") from exc
                for item in report["archives"]:
                    number = _chapter_from_name(item["name"])
                    if number in seen:
                        raise ControllerError("Duplicate ReLIFE chapter when staging candidate")
                    seen.add(number)
                    source_member = "ReLIFE/" + item["relativePath"]
                    chapter_file = chapters / (_chapter_label(number) + ".cbz")
                    _copy_verified_cbz(
                        archive,
                        source_member,
                        chapter_file,
                        item["sha256"],
                        item["archiveByteSize"],
                    )
        if len(seen) != validation["cbzArchives"]:
            raise ControllerError("Source chapter count changed after validation")
        if require_complete and seen != EXPECTED_CHAPTERS:
            raise ControllerError("Normalised ReLIFE source is incomplete")
        created = build(
            source_root,
            output,
            registry_file,
            direction="vertical",
        )
        confirmed = verify_bundle(output)
        if (
            created["series"] != 1
            or created["chapters"] != validation["cbzArchives"]
            or created["pages"] != validation["pages"]
            or confirmed["chapters"] != validation["cbzArchives"]
            or confirmed["pages"] != validation["pages"]
        ):
            raise ControllerError("Staged ReLIFE candidate disagrees with verified source")
        if require_complete and confirmed["pages"] != EXPECTED_PAGES:
            raise ControllerError("Staged ReLIFE page count differs from run")
        return {
            "status": "verified-provisional-candidate",
            "series": 1,
            "chapters": confirmed["chapters"],
            "pages": confirmed["pages"],
            "readingDirection": "vertical",
            "sourceRunVerified": True,
            "persistentIdsAssigned": False,
            "readyForUpload": False,
            "requiresRemoteRightsAndContractApproval": True,
        }
