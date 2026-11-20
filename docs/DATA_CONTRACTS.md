# Canonical Manga Hugging Face dataset contract (20 November 2026)

The Manga Library application owns the public JSON shape and runtime parser. The Novel Storage Controller supplies naming, recovery and workflow conventions, but **its EPUB/book schema is not reused for manga**.

The canonical private dataset is `AdityaSreevatsaK/Taiyous-Manga`. The reader expects exactly:

```json
{"schemaVersion": 1, "mediaKind": "manga", "entries": []}
```

Published at **`data/library.json`**. Each `entries` item is a validated `MangaEntry` with stable `mng_*` and `ch_*` IDs, user-visible metadata and ordered chapters. Progress, ratings, notes and other personal fields are separate from this catalogue.

## Canonical files

- `data/library.json`: JSON envelope with `schemaVersion:1`, `mediaKind:"manga"` and `entries`.
- `data/manga/<manga-id>/<chapter-id>/<page-id>.<original-extension>`: original validated raster page bytes, not transcoded automatically.
- `data/manifests/<chapter-id>.json`: validated `{schemaVersion:1,mediaKind:"manga",chapterId,pages}` records. Each page has immutable `pg_*` ID, size, dimensions, checksum and reader-validated **relative** `assetPath: "manga/<manga-id>/<chapter-id>/<page-id>.<ext>"`.
- `data/covers/<manga-id>.webp`: planned cover management path, not required for the current ReLIFE migration.

Manga may contain PNG, JPEG, WebP or AVIF source pages. Converting them all to WebP would modify originals and invalidate SHA-256 checksums; preserve their existing format and page IDs unless a **separate approved transformation** is tested.

## Existing ReLIFE upload: legacy format

The already complete ReLIFE upload exists under:
- `catalogue.json`: old raw array (not the reader's envelope).
- `manifests/<chapter-id>.json`: 237 chapter manifests.
- `assets/manga/<manga-id>/<chapter-id>/<page-id>.<ext>`: 5,606 verified original pages.
- `control/relife-identities.json`, `ingest/relife-v1/`: persistent metadata and checkpoints.

**Do not delete, move or overwrite these legacy files.** The temporary read-only Manga Library fallback can display the old catalogue until a safe migration. It does not provide private media page delivery.

## Required migration gates

1. Read the private dataset at an immutable SHA and verify its ReLIFE entry, all 237 manifests and 5,606 legacy image paths.
2. Pin the entire original tree as a private HF recovery branch; also make an independent full-media backup, not just a JSON catalogue copy.
3. Test the source-to-destination copy plan on an isolated private staging dataset and validate its result using the reader's schema.
4. Use only **append-only** copy operations with the expected-parent revision, preserving image bytes and original IDs. Publish `data/library.json` last. Never change `catalogue.json` or existing media paths.
5. Confirm that the reader can access `data/library.json`, the chapter manifests and page objects using its authorised private gateway, with a rollback path verified.
6. Only then authorise additional manga uploads, which must atomically merge `entries` without replacing other titles.

The module `hf_layout.py` implements only the **read-only inventory, schema validation and deterministic preview**, not remote mutation. `hf_recovery.py` creates only a private, revision-pinned recovery reference, not an independent backup. No main-branch data migration is currently authorised.

## Controller v1 local candidate is not the HF schema

The builder's `catalogue.json`, `manifests/` and `assets/manga/` are a local intermediate **source bundle**. Nothing may upload these paths as-is to the private dataset. All future upload plans must transform the validated bundle to the canonical `data/` paths and envelope while keeping IDs immutable.
