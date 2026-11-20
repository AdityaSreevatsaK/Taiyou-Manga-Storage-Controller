"""Prepare the five verified user-supplied Retriever records on a private Actions runner.

No real cover image, original chapter, private catalogue, or candidate metadata
is committed to this public repository. All source digests are pinned to the
owner-uploaded handover ZIP from 20 November 2026.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import stat
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from taiyou_manga.domain import ControllerError
from taiyou_manga.metadata import load_candidates
from taiyou_manga.relife_stage import _stable_registry
from taiyou_manga.selected_stage import stable_registry
from taiyou_manga.selected_titles import selected_title

SOURCES = {
    # slug: source MangaDex ID, exact candidate SHA, exact cover SHA, ext, title
    "relife": (
        "6e3553b9-ddb5-4d37-b7a3-99998044774e",
        "0fb5a07b1fd30a2c35ba30c64f7623c50b47cb50aef1d727428b2957311d74cb",
        "5ca50594536ad7c2cde24f234c5fd014b2dd57a72d9a442e89efcb3252a2b006",
        "png", "ReLIFE",
    ),
    "maid-sama": (
        "d5e2bd89-e300-4262-a799-fb4f79bdb777",
        "a8e061c6c5999112c0bac6aca1401dc42e0beb23cfbdaa586bf46c550fd3edc4",
        "6a1eb8308edd02584386bc062a78ebd885fc603547de1674b359e03bacf84df4",
        "jpg", "Kaichou wa Maid-sama!",
    ),
    "last-game": (
        "32600d3f-a43a-4f90-8a4e-c4e09f35c99b",
        "809be7f0102742bc84c0679f1c922423caf7f244fd4864ad95c6a5794e7b46bf",
        "68bfbb7b84d1f277d47a1d7818e7be247ae6fe1130b6ade135d100934001e52a",
        "jpg", "Last Game",
    ),
    "love-so-life": (
        "911a12ae-1022-448e-9219-b7b294d7fb3e",
        "ba1a1f8b608eb0593a1c4da4939f5063b31b2995de9ab359508d56643132897d",
        "8c1717cc78608454f8d07296a81141ab12a0e0bbdcc61c07ef578c8b111de3fd",
        "jpg", "Love So Life",
    ),
    "onizuka-sawarida": (
        "96b87943-6458-4045-a029-d3185d5cea57",
        "948c36132e6a2c3a2cf2519031e8dcaaf6eef733902e5aeb80c02da16f0fc190",
        "47b46212776b7f4c43ca952374df481a6e3564b838bf271d04e35805e5f566a2",
        "jpg", "Onizuka-chan and Sawarida-kun",
    ),
}

MAX_OUTER = 10_000_000
MAX_MEMBER = 5_000_000


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _archive(path: Path, *, limit: int = MAX_OUTER) -> dict[str, bytes]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ControllerError("Missing or excessive source artefact ZIP")
    with zipfile.ZipFile(path) as zipped:
        members = [item for item in zipped.infolist() if not item.is_dir()]
        if len(members) > 30:
            raise ControllerError("Untrusted source archive contains excessive files")
        output: dict[str, bytes] = {}
        for item in members:
            if (
                item.filename in output
                or not re.fullmatch(r"[A-Za-z0-9_./-]{1,150}", item.filename)
                or ".." in Path(item.filename).parts
                or item.file_size > MAX_MEMBER
                or (item.external_attr >> 16) & stat.S_IFMT(0o170000) == stat.S_IFLNK
            ):
                raise ControllerError("Unsafe Retriever archive member")
            with zipped.open(item) as stream:
                value = stream.read(MAX_MEMBER + 1)
            if len(value) != item.file_size or len(value) > MAX_MEMBER:
                raise ControllerError("Damaged or excessive Retriever source file")
            output[item.filename] = value
        return output


def _nested_artifact(path: Path, filename: str) -> dict[str, bytes]:
    outer = _archive(path)
    if set(outer) != {filename}:
        raise ControllerError("Unexpected source artefact attachment filenames")
    with zipfile.ZipFile(io.BytesIO(outer[filename])) as z:
        data: dict[str, bytes] = {}
        members = [i for i in z.infolist() if not i.is_dir()]
        if len(members) > 35:
            raise ControllerError("Nested source ZIP has too many files")
        for info in members:
            if (
                info.filename in data
                or not re.fullmatch(r"[A-Za-z0-9_./-]{1,150}", info.filename)
                or ".." in Path(info.filename).parts
                or info.file_size > MAX_MEMBER
            ):
                raise ControllerError("Unsafe nested Retriever archive path")
            with z.open(info) as stream:
                data[info.filename] = stream.read(MAX_MEMBER + 1)
            if len(data[info.filename]) != info.file_size:
                raise ControllerError("Incomplete nested source record")
    return data


def _identity(slug: str, title: str) -> str:
    if slug == "relife":
        return _stable_registry(set())["series:ReLIFE"]
    selected = selected_title(slug)
    if selected.name != title or selected.source_id != SOURCES[slug][0]:
        raise ControllerError("Stored manga source identity differs from uploaded handover")
    return stable_registry(selected, set())[f"series:{title}"]


def build(cover_artifact: Path, metadata_artifact: Path, output: Path) -> dict[str, object]:
    if output.exists() or output.is_symlink():
        raise ControllerError("Metadata staging directory must be new and private")
    cover_files = _nested_artifact(cover_artifact, "existing-five-verified-covers.zip")
    metadata_files = _nested_artifact(metadata_artifact, "manga-publication-metadata.zip")
    manifest = json.loads(cover_files["cover-attachment-manifest.json"])
    rows = manifest.get("covers")
    if not isinstance(rows, list) or len(rows) != 5:
        raise ControllerError("Five complete verified cover references required")
    by_slug = {row["slug"]: row for row in rows}
    if set(by_slug) != set(SOURCES):
        raise ControllerError("Retriever cover source IDs differ from the five requested manga")

    submitted = []
    output.mkdir(parents=True, mode=0o700)
    (output / "covers").mkdir(mode=0o700)
    for slug, (source_id, candidate_sha, cover_sha, ext, title) in SOURCES.items():
        name = f"candidates/{slug}.json"
        data = metadata_files.get(name)
        if data is None or sha256(data) != candidate_sha:
            raise ControllerError("Publication candidate digest differs from uploaded verified ZIP")
        record: dict[str, Any] = json.loads(data)
        if (
            record.get("candidateType") != "publication-metadata"
            or record.get("match", {}).get("sourceMangaId") != source_id
            or record.get("match", {}).get("canonicalTitle") != title
            or record.get("provenance", {}).get("sourceEditionMatched") is not True
            or record.get("provenance", {}).get("replaceManualMetadata") is not False
            or record.get("provenance", {}).get("operatorReviewRequired") is not True
        ):
            raise ControllerError("Untrusted manga publication source identity or review policy")
        cover_row = by_slug[slug]
        cover_path = f"covers/{slug}.{ext}"
        cover = cover_files.get(cover_path)
        if (
            cover is None or sha256(cover) != cover_sha
            or cover_row.get("sha256") != cover_sha
            or cover_row.get("path") != cover_path
            or cover_row.get("sourceMangaId", source_id) != source_id
            or cover_row.get("sourceUrl") != record["coverCandidate"]["sourceUrl"]
            or cover_row.get("rightsClearedForRedistribution") is not False
            or record["coverCandidate"].get("rightsClearedForRedistribution") is not False
        ):
            raise ControllerError("Manga cover bytes, source ID, or rights status differs")
        from taiyou_manga.images import check_bytes

        inspected = check_bytes(cover, cover_path)
        if (
            inspected.checksum != cover_sha or inspected.byte_size != cover_row["bytes"]
            or inspected.width != cover_row["width"]
            or inspected.height != cover_row["height"]
            or inspected.mime != cover_row["mimeType"]
        ):
            raise ControllerError("Manga cover integrity and declared dimensions disagree")
        (output / cover_path).write_bytes(cover)

        meta = record["metadata"]
        source = record["provenance"]
        when = datetime.fromisoformat(source["retrievedAtUtc"]).astimezone(UTC)
        origin = {
            "provider": "mangadex",
            "sourceId": source_id,
            "sourceUrl": source["sourceUrl"],
            "retrievedAt": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        submitted.append({
            "mangaId": _identity(slug, title),
            "title": title,
            "source": origin,
            "metadata": {
                "aliases": meta["aliases"],
                "creators": meta["creators"],
                "creatorRoles": [
                    {"name": item["name"], "role": item["role"]}
                    for item in meta["creatorRoles"]
                ],
                "tags": meta["tags"],
                "synopsis": meta["synopsis"],
                "publicationStatus": meta["publicationStatus"],
                "cover": {
                    "file": cover_path,
                    # Owner consent for private retention is not a public
                    # redistribution licence; preserve the distinction.
                    "rightsEvidence": (
                        "Owner requested private-library preservation of the supplied cover; "
                        "redistribution permission unverified."
                    ),
                    "attribution": (
                        "MangaDex cover source; rights retained by respective copyright holders."
                    ),
                },
            },
        })

    candidate = {
        "schemaVersion": 1,
        "mediaKind": "manga-metadata-candidates",
        "candidates": submitted,
    }
    dest = output / "candidates.json"
    dest.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    checked, _ = load_candidates(dest)
    if len(checked) != 5:
        raise ControllerError("All five publication metadata candidates must be valid")
    return {"status": "five-verified-metadata-candidates", "covers": 5, "candidates": 5}


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare owner-uploaded five-title source metadata")
    parser.add_argument("--cover-artifact", type=Path, required=True)
    parser.add_argument("--metadata-artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build(args.cover_artifact, args.metadata_artifact, args.output)
    except (ControllerError, KeyError, ValueError, OSError, zipfile.BadZipFile) as exc:
        parser.exit(2, f"Refusing unsupported private metadata import: {exc}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
