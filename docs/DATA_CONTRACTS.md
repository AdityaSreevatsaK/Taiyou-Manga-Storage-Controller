# Manga data contracts

Source reviewed: `Taiyous-Manga-Library/src/domain/types.ts`, `src/domain/validation.ts`, `docs/DATA_CONTRACTS.md` and proposed ADR-006 (18 November 2026). No production persistence design has been approved.

- `MangaEntry`: `kind: "manga"`, `id` with `mng_` prefix, title, aliases, creators, tags, publicationStatus, direction and ordered chapter list. No personal rating or read progress is included in generated catalogues.
- `MangaChapter`: `ch_` immutable ID, label, zero-based sequence, optional volume and page count.
- `ChapterManifest`: `{schemaVersion:1, mediaKind:"manga", chapterId, pages}`. Every page is `pg_` ID, `assetPath`, MIME, width, height, byteSize and SHA-256. Assets use strict relative `manga/<series>/<chapter>/<page>.<ext>` paths, never remote URLs.
- Progress stays in the Manga Library. It binds `chapterId`, zero-based `pageIndex` AND immutable `pageId`. Reordered/missing pages must be reconciled rather than silently advancing positions.
- Source rights: optional private `rights.json` mirrors `SourceRights` v1, but a declaration is **not independent legal verification**. No remote write is authorised by its presence alone.
- The private `inventory.json` object carries `controllerCandidateVersion:1` and counts/warnings. It is **not** a proposed production HF catalogue schema. The `ids.json` registry is private local configuration, not a browser contract.

Treat incompatible future schema versions as errors. Any migration must include a signed-off source/target contract, dry-run inventory diff, verified full-media backup and recovery tests. Do not copy novel EPUB identifiers or personal data.
