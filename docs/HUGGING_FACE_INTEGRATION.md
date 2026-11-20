# Hugging Face manga storage: authorised ReLIFE import (historical)

> **Historical ReLIFE upload runbook, superseded as a current storage description.** The original root catalogue.json/manifests/assets paths shown below are preserved legacy recovery paths, not the current reader-compatible dataset. ReLIFE was subsequently migrated to **data/library.json**, data/manifests/ and data/manga/, and four more titles were uploaded. Read [current data contract](DATA_CONTRACTS.md) and [Repository Handbook](REPOSITORY_HANDBOOK.md) before any new operation. The migration hold documented at the bottom of this page **was resolved** on 20 November 2026. Do not rerun a historic workflow as a general manga upload.


**Private destination:** `AdityaSreevatsaK/Taiyous-Manga`, previously verified through the protected GitHub environment `hf-manga-upload` and its `HF_TOKEN` secret.

**User approval:** On 20 November 2026 the owner affirmed permission to store these ReLIFE English scans on this private Hugging Face dataset and authorised the upload. This is a user attestation, not independent legal verification.

## Persisted reader-compatible layout

- `catalogue.json`: one ReLIFE series with 237 chapters, published in the final commit only
- `manifests/ch_*.json`: 237 validated chapter manifests
- `assets/manga/<series-id>/<chapter-id>/<page-id>.<ext>`: 5,606 original page images
- `control/relife-identities.json`: backed-up deterministic series/chapter identity mapping
- `ingest/relife-v1/part-NNN.json`: revisioned, append-only page checkpoints
- `ingest/relife-v1/attestation.json`: private source acknowledgement and permission statement
- `ingest/relife-v1/complete.json`: final completion marker, committed with catalogue

These paths preserve the Manga Library v1 catalogue and chapter/page contracts. The Controller-only `inventory.json` is not published as a reader contract. Personal progress and ratings are not uploaded.

## Guarded upload procedure

The new `.github/workflows/relife-private-hf-upload.yml` workflow runs once on first merge to `master` and may be manually rerun. It uses the protected `hf-manga-upload` environment and is serialised via `hf-manga-private-write`.

1. Retrieve the original 12 ReLIFE Github Actions ZIPs, which expire 26 November 2026, into temporary runner storage.
2. Independently verify all 237 original CBZ archives and 5,606 pages, including checksums and dimensions.
3. Generate the single-series candidate with deterministic opaque IDs, then verify its reader manifests.
4. Check the private dataset revision and write an exact local preview; recheck revision and candidate before mutation.
5. Append original page assets in batches of at most 200 files, with a checksum checkpoint in the same optimistic-concurrency commit. No file replacement or deletion is allowed.
6. Resume safely from committed checkpoint digests if a prior attempt stopped. Refuse any uncheckpointed remote file, changed file list or existing foreign catalogue.
7. Commit all chapter manifests, identity registry, attestation, catalogue and completion marker only after the pages are present.
8. Verify published file inventory, and delete runner-only media and temporary credentials regardless of outcome.

GitHub Actions never publishes source manga media as public workflow artefacts. The source and private HF token are provided only to their respective steps. The remote revisions permit recovery of previous dataset states but do not replace independent backups.

The owner approval is specific to the ReLIFE title and cannot be reused as permission for other scans. Live uploads must not be enabled for arbitrary unreviewed source content, and must not alter or clear other dataset content.

## Reader integration

After successful upload, the existing Manga Library still needs a private Hugging Face asset adaptor before the new ReLIFE entry can be read in the deployed UI. Upload success must not be presented as completed reader integration.

## Migration hold after ReLIFE success

The old ReLIFE upload **completed** but its remote layout is legacy. See [the canonical manga storage contract](DATA_CONTRACTS.md). The old upload workflow has been retired. **Do not use it or the superseded four-title proposal to append further titles** until the canonical `data/library.json` contract and private staging migration have been verified. Existing media remains unchanged.
