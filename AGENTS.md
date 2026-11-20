# Agent operating contract

- This repository owns only **Taiyou-Manga-Storage-Controller**. Read the Manga Library contracts, but do not change `Taiyous-Manga-Library` or the Novels Controller without specific permission.
- `master` is canonical. Work on focused branches, open PRs and merge verified changes; describe any unavailable checks accurately.
- Public code, synthetic fixtures and automated CI only. Never check in private manga originals, personal metadata, rights evidence, token files, HF exports or backups.
- Preserve opaque IDs, zero-based page indices and immutable page-ID semantics. Use `src/domain/types.ts`, `src/domain/validation.ts` and ADR-006 in the Manga Library as compatibility references; ADR-006 is **proposed**, not approved storage.
- For every untrusted image or archive, verify bytes, dimensions, MIME and CRC/decompression limits. Never extract archive names as destination paths without validation.
- Never enable general-purpose Hugging Face writes, create a dataset, bulk-delete media or bypass rights checks. Exception: owner explicitly authorised the existing private ReLIFE dataset upload on 20 November 2026. Only the scoped, protected, revision-guarded ReLIFE workflow can use live writes; any other title or mutation requires separate approval.
- Guard all future mutations with preview, explicit owner authorisation, revision preconditions, immutable backups, failure recovery and tests.
- Keep Python 3.11/3.12 and Windows PowerShell working. `python -m unittest discover -s tests -v` needs no paid accounts.
- Do not claim green CI if jobs have not executed. Document the exact failed/unavailable gate.

- CRITICAL P0 (2026-11-20): **No further HF manga image uploads or catalogue edits** until canonical `data/library.json` format, full independent backup, private disposable migration test and reader compatibility are verified. Root `catalogue.json` is a legacy **source** only. Existing ReLIFE bytes and IDs must not be deleted or overwritten. PR #20 was closed. Do not merge or reinstate a job that writes legacy root `catalogue.json`.
