# P0 publication metadata and private covers: Controller contract proposal

Status: Proposed for Manga Library and Retriever agreement. This PR edits only
Taiyou-Manga-Storage-Controller. It has no live Hugging Face writes.

## Canonical private dataset

The catalogue remains data/library.json with schemaVersion 1, mediaKind manga.
Existing fields id, title, aliases, creators, tags, synopsis,
publicationStatus, direction and chapters stay unchanged.

Proposed optional entry fields:
- cover: object with assetPath, mimeType, width, height, byteSize, sha256.
  assetPath is relative to data/, for example
  covers/mng_aaaaaaaaaaaa.webp, physically data/covers/mng_aaaaaaaaaaaa.webp.
  Never put a signed URL, token, public endpoint or absolute path here.
- creatorRoles: array of {"name":"Writer","role":"author"} or
  {"name":"Artist","role":"artist"}. The existing creators array is populated
  for older consumers too.
- metadataSources: a map keyed by the enriched field (creators, aliases,
  tags, synopsis, publicationStatus, creatorRoles, cover), with provider,
  sourceId, sourceUrl and retrievedAt. Provenance URLs are plain HTTPS
  publication references only, never signed media delivery URLs.

Publication tags are distinct from personal tags. Publication completed status
is not a reader's Finished shelf. No chapter or manifest schema changes.

Library compatibility: its current parser discards optional keys it does not
recognise. The Library must opt into cover, creatorRoles and metadataSources
and load covers through an authenticated gateway, not browser Hugging Face
tokens. Until both teams agree on the exact cover object, DO NOT publish
metadata that assumes the Library can display it.

## Retriever candidate format

The Retriever supplies verified local metadata candidates; no remote
download logic is added to the Controller. One example:

{
  "schemaVersion": 1,
  "mediaKind": "manga-metadata-candidates",
  "candidates": [
    {
      "mangaId": "mng_aaaaaaaaaaaa",
      "title": "Demo Manga",
      "source": {
        "provider": "mangadex",
        "sourceId": "source-title-id",
        "sourceUrl": "https://mangadex.org/title/source-title-id",
        "retrievedAt": "2026-11-20T08:30:00Z"
      },
      "metadata": {
        "aliases": ["Alternative title"],
        "creatorRoles": [
          {"name": "Writer", "role": "author"},
          {"name": "Artist", "role": "artist"}
        ],
        "tags": ["Romance"],
        "publicationStatus": "completed",
        "synopsis": "Verified publication synopsis.",
        "cover": {
          "file": "covers/source-cover.webp",
          "rightsEvidence": "Evidence that private cover storage is permitted",
          "attribution": "Copyright holder"
        }
      }
    }
  ]
}

The relative source cover file resides next to the metadata JSON under
covers/. It is decoded, bounds-checked, verified against the original
file type and SHA-256 hashed. Covers are never transcoded.

Permission for private storage of artwork must be verified independently.
The existence of an image on a website is not proof of permission.

## Conflict and preservation policy

- A candidate without a stable mangaId is preview-only and always requires
  manual review, even if its displayed title matches exactly one manga.
- Mismatched IDs or names, repeated candidates, ambiguous matches, an existing
  non-empty field with different values, or an occupied cover path are
  conflicts. Never attach metadata solely because two names look similar.
- Missing values can be filled, and empty incoming values are ignored.
  Existing non-empty or manually corrected values are never overwritten.
- Existing series IDs, chapter IDs, page IDs and chapters are unchanged.
  No original pages, manifests, reading progress or collections are rewritten.
- Every approved change uses a revision-pinned preview. One expected-parent
  commit adds new private covers (only if paths are free), a byte-identical
  backup of the prior catalogue at
  control/metadata-backups/<revision>/library.json, and new data/library.json.
- For every new cover, its attribution and permission evidence are saved
  separately at control/cover-rights/<mangaId>/<coverSha256>.json within the
  private dataset. Rights evidence is not exposed in the reader catalogue.
- Any concurrent change means preview approval becomes invalid. No deletion,
  bulk copy or destructive migration is part of this feature.

## Offline-first workflow

Read-only private metadata audit:
    python -m taiyou_manga.hf_metadata --report-only

Preview:
    python -m taiyou_manga.hf_metadata --candidates metadata.json --plan-file preview.json

Apply after review of every conflict, permission and schema decision:
    python -m taiyou_manga.hf_metadata --candidates metadata.json --plan-file preview.json --apply --approve

Set HF_TOKEN through a secure local environment variable. Do not commit private
input, covers, preview output or token. Do not print a private report in
a public GitHub Actions job. The Controller code PR performs no HF writes.
