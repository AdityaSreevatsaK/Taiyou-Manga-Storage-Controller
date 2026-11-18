"""Storage ports and safe offline mock. Live HF data is strictly read-only."""

from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from collections.abc import Iterator
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .builder import load_json, verify_bundle, write_json
from .domain import ControllerError


class RevisionConflict(ControllerError):
    """Remote changed after preview; refresh and start again."""


class RemoteWritesDisabled(ControllerError):
    """Real Hugging Face dataset writes deliberately unavailable."""


@dataclass(frozen=True)
class Plan:
    revision: str | None
    status: str
    new_pages: int
    unchanged_pages: int
    conflicting_pages: int

    def as_json(self) -> dict[str, object]:
        return {"expectedRevision": self.revision, "status": self.status, "newPages": self.new_pages,
                "unchangedPages": self.unchanged_pages, "conflictingPages": self.conflicting_pages}


class StorageReader(Protocol):
    def health(self) -> dict[str, object]: ...


class HuggingFaceReadOnly:
    """Read-only API boundary. No mutation method, token, or default dataset ID."""

    def __init__(self, repo_id: str) -> None:
        if not repo_id or "/" not in repo_id or any(char.isspace() for char in repo_id):
            raise ControllerError("Supply an explicit organisation/dataset identifier")
        self.repo_id = repo_id

    def health(self) -> dict[str, object]:
        try:
            from huggingface_hub import HfApi
            from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError, RevisionNotFoundError
        except ImportError as exc:
            raise ControllerError("Install the optional huggingface dependency") from exc
        try:
            info = HfApi().dataset_info(self.repo_id)
        except RepositoryNotFoundError as exc:
            raise ControllerError("Dataset missing, private without permission, or invalid credentials") from exc
        except GatedRepoError as exc:
            raise ControllerError("Dataset access is not authorised") from exc
        except RevisionNotFoundError as exc:
            raise ControllerError("Dataset revision not found") from exc
        except (OSError, ConnectionError, TimeoutError) as exc:
            raise ControllerError("Network unavailable during read-only health check") from exc
        if not info.private:
            raise ControllerError("Dataset is not private; refusing manga integration")
        return {"private": True, "repoType": "dataset", "revision": info.sha,
                "mode": "read-only", "remoteWrites": False}

    def write(self, *args: object, **kwargs: object) -> None:
        raise RemoteWritesDisabled("Remote writes are disabled pending owner approval")


class MockStorage:
    """Versioned local simulation, never a real remote adapter."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _head(self) -> str | None:
        path = self.root / "head.json"
        if not path.exists():
            return None
        data = load_json(path)
        if not isinstance(data, dict) or not isinstance(data.get("revision"), str):
            raise ControllerError("Mock remote head corrupt")
        return data["revision"]

    def health(self) -> dict[str, object]:
        return {"kind": "mock", "revision": self._head(), "writesAreLocalOnly": True}

    @staticmethod
    def _fingerprints(bundle: Path) -> dict[str, str]:
        result = {}
        for path in sorted((bundle / "manifests").glob("*.json")):
            doc = load_json(path)
            for page in doc["pages"]:
                if page["assetPath"] in result:
                    raise ControllerError("Duplicate asset path in manifests")
                result[page["assetPath"]] = page["sha256"]
        return result

    def preview(self, bundle: Path) -> Plan:
        verify_bundle(bundle)
        revision = self._head()
        new = self._fingerprints(bundle)
        previous = self._fingerprints(self.root / "snapshots" / revision) if revision else {}
        conflicting = sum(1 for p in new if p in previous and previous[p] != new[p])
        unchanged = sum(1 for p in new if p in previous and previous[p] == new[p])
        created = len(new) - unchanged - conflicting
        missing = len(previous.keys() - new.keys())
        status = "conflict" if conflicting or missing else ("no-op" if not created else "new")
        return Plan(revision, status, created, unchanged, conflicting + missing)

    @contextmanager
    def _write_lock(self) -> Iterator[None]:
        """Portable exclusive local lock; crashed stale locks require manual inspection."""
        self.root.mkdir(parents=True, exist_ok=True)
        lock = self.root / "write.lock"
        try:
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise RevisionConflict("Mock remote has a concurrent or stale writer lock") from exc
        try:
            os.close(fd)
            yield
        finally:
            lock.unlink(missing_ok=True)

    def apply(self, bundle: Path, expected_revision: str | None, approve: bool = False) -> str:
        if not approve:
            raise ControllerError("Explicit approval is required for mock writes")
        with self._write_lock():
            return self._apply_locked(bundle, expected_revision)

    def _apply_locked(self, bundle: Path, expected_revision: str | None) -> str:
        if self._head() != expected_revision:
            raise RevisionConflict("Mock remote revision changed since preview")
        plan = self.preview(bundle)
        if plan.revision != expected_revision:
            raise RevisionConflict("Mock remote changed while planning")
        if plan.status == "conflict":
            raise ControllerError("Conflict: mock updates cannot overwrite or delete files")
        if plan.status == "no-op":
            return expected_revision or ""
        # Snapshot commit is immutable, allowing full-media recovery.
        contents = hashlib.sha256()
        for page, checksum in sorted(self._fingerprints(bundle).items()):
            contents.update(page.encode("utf-8") + b"\0" + checksum.encode("ascii"))
        revision = contents.hexdigest()
        dest = self.root / "snapshots" / revision
        self.root.mkdir(parents=True, exist_ok=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            stage = Path(tempfile.mkdtemp(prefix=".mock-stage-", dir=dest.parent))
            try:
                shutil.copytree(bundle, stage / "bundle", symlinks=False)
                (stage / "bundle").rename(dest)
                verify_bundle(dest)
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
        # Check again under an exclusive lock before the atomic pointer switch.
        if self._head() != expected_revision:
            raise RevisionConflict("Mock remote changed before final revision switch")
        tmp = self.root / "head.tmp"
        write_json(tmp, {"revision": revision})
        tmp.replace(self.root / "head.json")
        return revision
