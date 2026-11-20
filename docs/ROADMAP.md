# Manga Storage Controller Roadmap and Current State

**Reviewed:** 20 November 2026. See [Repository Handbook](REPOSITORY_HANDBOOK.md) for the current contract; this is a planning document, not permission for live HF writes.

## Completed

1. **Offline import and integrity engine:** Windows entry point, Python 3.11/3.12, synthetic manga fixtures, folder/ZIP/CBZ discovery, natural page order, media validation, SHA-256, chapter manifests, private local bundles, mock revision checks.
2. **Identity and archive hardening:** persistent opaque IDs, cross-process registry lock and atomic writes, explicit path-rename identity migration, traversal/symlink/decompression quotas, bundle integrity verification.
3. **Backup/recovery basics:** verified local full-media bundle backups, non-destructive local restore, canonical data migration with preserved ReLIFE originals, JSON catalogue backup paths and revision-guarded writes.
4. **Private canonical dataset and selected uploads:** data/library.json and original pages/manifests under data/ in AdityaSreevatsaK/Taiyous-Manga. ReLIFE plus Maid-sama!, Last Game, Love So Life and Onizuka-chan and Sawarida-kun were verified.
5. **Publication metadata and original cover support:** creators, author/artist roles, synopsis, tags, publication status, alternative titles, source provenance, image checksums and private rights records for the initial five.
6. **Novel Controller-style manga operations (PR #28):** 20-option Windows menu, bulk append-only upload, original-page ZIP download, list/conflicts/health/integrity, sync reports, catalogue backup, cover ZIP ingestion, Retriever comparison, metadata reports and reversible de-list/restore.
7. **CI and live read-only smoke:** Windows/Linux and Python 3.11/3.12 synthetic CI, plus separately protected read-only private dataset verification.

**Dated live baseline:** Five manga, 587 chapters, 14,635 pages, five complete covers/metadata at HF revision 0942616f03e165c7f9e4258110c9fdb4b085f1fc on 20 November 2026. This baseline must be refreshed in future sessions.

## Next engineering improvements (not authorised live operations)

**P0 reliability and recovery**
- Rehearse new generic uploads, cover ZIP import and reversible de-list/restore against an isolated **private disposable dataset** with synthetic or explicitly permitted test assets, including interrupted batches and concurrent remote writes.
- Strengthen independent off-platform full-media backup and restoration procedures; verify media image bytes and rights/manifests, not only catalogue JSON.
- Provide safe diagnostic reports for corrupt/missing objects and avoid false "complete" claims from quick file-list checks.
- Review existing special-case workflows for hardcoded five-title assumptions, retention of historical artefacts and actions that should be retired or kept manual only.

**P1 operator experience**
- Improve resumable local multi-manga downloads (bounded concurrency, retries and progress reports) without replacing verified backups.
- Make local sync status distinguish catalogue equivalence from byte equality.
- Improve exact-ID matching and source-title collision evidence; never infer editions from fuzzy titles.
- Strengthen cover provenance review and rights evidence without exposing private URLs.

**P2 sustainability**
- Add cross-repository contract test fixtures for Manga Library reader compatibility.
- Maintain a single current documentation/AI-agent handover and mark old procedures historical.
- Add a configurable, owner-approved inventory baseline for the private smoke workflow as the collection grows.
- Review resource ceilings and AVIF platform availability.

## Deliberate non-goals

- Manga scraping/download acquisition: Manga Retriever.
- Reader URLs, progress, offline UX, collections and Cloudflare private media gateway: Manga Library.
- EPUB or book metadata conventions: Novel Controller.
- Public content hosting or publication of original page images.
- Whole-dataset deletion or automatic irreversible single-title purge.

## Prioritisation rule

Avoid making a live HF mutation to validate a code change when a synthetic or private staging test can prove it safely. Before any production operation, obtain separate owner approval and fulfil the preview, exact SHA, backup and post-write checks in [AGENTS.md](../AGENTS.md).
