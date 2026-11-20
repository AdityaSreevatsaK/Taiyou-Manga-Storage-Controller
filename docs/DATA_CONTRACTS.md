# Canonical Manga Storage Contract

**Updated:** 20 November 2026. **Status:** In use in the private dataset. This supersedes the original pre-migration proposal and hold recorded in the repository's historical migration guides.

**Contract owner:** Manga Library runtime validators and the Manga Controller's validated v1 schema. The Controller must coordinate optional fields with the Library before changing their meaning. The Novel Controller's EPUB schema does **not** apply.

## Canonical private repository

Hugging Face dataset: **AdityaSreevatsaK/Taiyous-Manga** (**private**).

    data/library.json
    data/manga/<mng_id>/<ch_id>/<pg_id>.<ext>
    data/manifests/<ch_id>.json
    data/covers/<mng_id>.<ext>
    control/metadata-backups/<revision>/library.json
    control/cover-rights/<mng_id>/<sha256>.json
    control/bulk-catalogue-backups/<revision>/library.json
    control/delist-backups/<revision>/library.json
    ingest/bulk-v1/<mng_id>/part-xxxx.json
    ingest/bulk-v1/<mng_id>/complete.json

Other control/ and ingest/ paths hold historical migration records or special-case checkpoints. Do not clear them merely because they are not part of the reader payload.

### Catalogue envelope

The root document at **data/library.json** must contain **exactly** the keys schemaVersion, mediaKind and entries:

    {
      "schemaVersion": 1,
      "mediaKind": "manga",
      "entries": []
    }

Each entry is a manga with the following required public publication fields:
- kind = "manga"
- id: opaque stable mng_* identifier
- title: display string, not an identifier
- aliases: array of alternative title strings
- creators: array of creator strings, maintained for compatibility
- tags: **publication** genres/tags, not personal tags
- publicationStatus: one of unknown, ongoing, completed, hiatus
- direction: one of vertical, rtl, ltr
- chapters: ordered chapter descriptors

Chapter descriptors require:
- id: immutable ch_* identifier
- label: display label (e.g. Chapter 1)
- sequence: non-negative chapter sequence, unique within the manga
- pageCount: number of pages, from 1 to 1000
- volume may appear if known

Optional publication fields:
- synopsis: text up to current validator limit
- creatorRoles: list of {name, role} objects where role is author or artist
- cover: validated original image descriptor
- metadataSources: provenance map by accepted publication field

Do **not** derive permanent IDs from the current display title, language or public browser slug.

### Chapter manifests and page media

Each data/manifests/<ch_id>.json file contains:

    {
      "schemaVersion": 1,
      "mediaKind": "manga",
      "chapterId": "ch_bbbbbbbbbbbb",
      "pages": [
        {
          "id": "pg_cccccccccccc",
          "assetPath": "manga/mng_aaaaaaaaaaaa/ch_bbbbbbbbbbbb/pg_cccccccccccc.jpg",
          "mimeType": "image/jpeg",
          "width": 800,
          "height": 1200,
          "byteSize": 123456,
          "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        }
      ]
    }

This is **synthetic illustration only**. Page assetPath is **relative to data/**; append data/ for the full HF filename. The manifest array determines reading page order. Keep the page's ID, path, width, height, MIME, byte size and SHA-256 mutually consistent. Original page extensions may be .png, .jpg, .jpeg, .webp and supported .avif. Do not silently transcode or renumber.

### Original covers

Optional cover descriptor:

    {
      "assetPath": "covers/mng_aaaaaaaaaaaa.webp",
      "mimeType": "image/webp",
      "width": 450,
      "height": 650,
      "byteSize": 123456,
      "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }

The file is stored at data/covers/mng_aaaaaaaaaaaa.webp. The actual extension can be PNG, JPEG, WebP or supported AVIF and must match the verified original bytes. Cover replacement is **not** an automatic overwrite operation. Existing covers and occupied paths are protected. The byte checksum and permission/attribution details are kept in a private control/cover-rights/ record.

**Never** store a bearer token, public HF URL, expiring signed URI, filesystem absolute path or external hotlink in cover.assetPath.

### Field-level source provenance

Optional metadataSources maps fields such as creators, creatorRoles, aliases, tags, synopsis, publicationStatus and cover to an object containing:
- provider: short source identifier
- sourceId: edition/source record ID
- sourceUrl: plain HTTPS publication reference, **not** a signed image URL
- retrievedAt: UTC timestamp

Metadata candidate **input format** is distinct from the published catalogue format. Candidate input uses schemaVersion 1, mediaKind "manga-metadata-candidates", candidates array, a stable mangaId, source provenance and proposed metadata. See [METADATA_RECONCILIATION_CONTRACT.md](METADATA_RECONCILIATION_CONTRACT.md). Candidate JSON and images may be placed in a private ZIP and passed through the validated hf_cover_zip wrapper. An ambiguous title-only candidate is preview-only and requires manual identity review.

An update fills genuinely missing/unknown data; it does not replace manually corrected or existing nonempty values without an explicit separate resolution.

## Stable identities and personal reading data

Manga IDs, chapter IDs, page IDs, catalogue-to-manifest associations and manifest page order must remain unchanged across metadata enrichment, source-title corrections and UI URL slug changes.

The Controller does not own reader progress, current chapter, favourites, ratings, personal tags, collections, bookmarks, offline downloads or reading state. These must remain separate. Publication completed does **not** mean the owner finished reading a title.

The local registry .manga-controller/ids.json is private and tracks stable source identities. Renaming or moving input folders requires a reviewed identity-migrate plan; never solve the problem by generating new IDs.

## Validation, upper bounds and privacy

Implementation validators in src/taiyou_manga/hf_layout.py, domain.py and metadata.py are authoritative for exact current size/length ceilings. At the handbook review date:
- canonical catalogue size: at most 4 MiB;
- up to 10,000 series and 2,000 chapters per series;
- chapter pageCount 1 to 1000;
- image dimensions 1 to 16,000 per axis, with total decoded-pixel cap;
- pages have bounded byte size and valid 64-character lowercase SHA-256;
- covers have their own stricter 5 MiB limit.

Do not bypass a validator to accommodate a private title. If a limit is insufficient, add explicit tests and a coordinated contract change.

The public GitHub repo must not contain private original manga images, actual cover files, personal catalogue exports, rights sidecars, media backups, HF access tokens or source manifests.

## Historical legacy layout and migration outcome

The first ReLIFE upload created legacy **root** catalogue.json, manifests/<ch_id>.json and assets/manga/<mng_id>/<ch_id>/<pg_id>.<ext>. These files are historical recovery sources, not the reader's active catalogue and not a valid destination for new imports.

The canonical migration completed on 20 November 2026 and the five-title catalogue/cover upload was verified subsequently. Historical migration preconditions and old docs should be read as **the procedure that was followed**, not instructions to pause every future upload. Do **not** delete the legacy originals without a new independently backed-up approval.

**Dated verification:** read-only protected run [44721448011](https://github.com/AdityaSreevatsaK/Taiyou-Manga-Storage-Controller/actions/runs/44721448011) confirmed 5 entries, 587 chapters, 14,635 pages, 5 covers/metadata and a sample chapter manifest per title at revision 0942616f03e165c7f9e4258110c9fdb4b085f1fc. Future agents must re-read the current private SHA.

## Write/rollback policy

1. Load and validate canonical current library and private dataset SHA.
2. Verify source identity, bytes, source authorisation and provenance.
3. Generate and review a conflict-free plan; approve **that** version only.
4. Require optimistic expected-parent revision and preserve byte-identical pre-change library.json as a private backup.
5. Upload original page media and manifests with checkpoints; publish new title in library.json **only after media**. Metadata-only updates use their own guarded one-commit path.
6. Read back and validate all intended files/paths, identities, SHA and unrelated record preservation.
7. On conflict, stop; regenerate preview and obtain fresh operator approval rather than forcing a write.

A library.json backup is not a full-media backup. Full-media deletion remains outside ordinary Controller functionality.

[Repository Handbook](REPOSITORY_HANDBOOK.md) | [AI Agent Playbook](AI_AGENT_PLAYBOOK.md) | [Novel-style operations](NOVEL_CONTROLLER_PARITY.md)
