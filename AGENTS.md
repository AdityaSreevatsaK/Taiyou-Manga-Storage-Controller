# Agent operating contract

- This repository owns only **Taiyou-Manga-Storage-Controller**. Read the Manga Library contracts, but do not change `Taiyous-Manga-Library` or the Novels Controller without specific permission.
- `master` is canonical. Work on focused branches, open PRs and merge verified changes; describe any unavailable checks accurately.
- Public code, synthetic fixtures and automated CI only. Never check in private manga originals, personal metadata, rights evidence, token files, HF exports or backups.
- Preserve opaque IDs, zero-based page indices and immutable page-ID semantics. Use `src/domain/types.ts`, `src/domain/validation.ts` and ADR-006 in the Manga Library as compatibility references; ADR-006 is **proposed**, not approved storage.
- For every untrusted image or archive, verify bytes, dimensions, MIME and CRC/decompression limits. Never extract archive names as destination paths without validation.
- Never create public media datasets, bulk-delete originals, delete entire Hugging Face datasets, or bypass rights checks. The owner authorised ReLIFE, four additional manga and verified metadata uploads on 20 November 2026. All future mutations, including general uploads and reversible catalogue de-listing, require per-operation preview, explicit local approval, stable immutable IDs, a private destination, revision guards and pre-change catalogue snapshots. No live HF writes in CI.
- Guard all future mutations with preview, explicit owner authorisation, revision preconditions, immutable backups, failure recovery and tests.
- Keep Python 3.11/3.12 and Windows PowerShell working. `python -m unittest discover -s tests -v` needs no paid accounts.
- Do not claim green CI if jobs have not executed. Document the exact failed/unavailable gate.

- CRITICAL P0 (updated 2026-11-20): Canonical `data/library.json` migration and the five-manga metadata/cover backfill are complete. Root `catalogue.json` is a legacy **source** only. Never overwrite existing original manga bytes, manifests or immutable IDs. Any destructive *permanent* media removal requires a separately verified independent off-platform full-media backup and explicit new owner approval. Only reversible de-listing is implemented in the generic management menu. Full dataset reset remains disabled.
