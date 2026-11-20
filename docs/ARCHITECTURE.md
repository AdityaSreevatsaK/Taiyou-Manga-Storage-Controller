# Manga Controller Architecture

**Updated:** 20 November 2026. This describes the current code, including private Hugging Face operations that did not exist in the original offline-only architecture.

## Component boundary

This Python repository is a **storage management and integrity control plane**, not a reader or downloader. It validates owner-supplied image pages and publication metadata, constructs a Manga Library-compatible catalogue, performs safe private storage operations and provides audit/recovery utilities.

- **Manga Retriever:** source discovery, source-specific downloads, original cover candidates, source evidence.
- **Manga Storage Controller:** safety validation, stable identity registry, canonical private HF catalogue/media, management operations, backups and metadata reconciliation.
- **Manga Library:** browser navigation, public UI, authenticated Cloudflare/HF page gateway, offline reading and personal progress.
- **Novel Controller:** operational design reference, with its own separate EPUB and book data contract.

## Data flow

    Owner-supplied ZIP / CBZ / chapter image folders
                  |
                  v
            sources.py
       bounded, safe file discovery
                  |
                  v
            images.py
       full decode, MIME, dimensions, SHA
                  |
                  v
            builder.py
       private identity registry,
       catalogue/manifest/assets bundle
                  |
                  +----> verify_bundle()
                  |      mock storage / full local backup
                  |
                  v
             hf_bulk.py
       revision-pinned preview
       125-file checkpointed media batches
       validated source rights declaration
       catalogue update only after media complete
                  |
                  v
           Private HF dataset
           data/library.json
           data/manifests/*.json
           data/manga/... image files

       Retriever source metadata / cover ZIP
                  |
                  v
           metadata.py
       validate source provenance and owner-supplied identities
       reject ambiguous/occupied/manual-data conflicts
                  |
                  v
           hf_metadata.py
       same private HF dataset, revision-pinned
       one expected-parent commit including backup,
       optional original cover bytes and rights sidecars

Local/cloud management functions:
- hf_manage.py: private snapshot, list, report, integrity quick/manifest/deep, downloads, backups, local sync, reversible de-list and restore.
- hf_extra.py: chapter inventory, Retriever comparison and local-only temporary download cleanup.
- hf_cli.py: new Windows menu and standalone management commands.
- cli.py: existing offline/demo/mock/registry command family and menu dispatch.

Production data **must** match [DATA_CONTRACTS.md](DATA_CONTRACTS.md) rather than any local bundle layout.

## Identities and storage consistency

Local build registers opaque IDs in .manga-controller/ids.json, protected by a cross-process lock and atomic update. Page IDs are tied to original image content. IDs, page order and chapter order must survive display-title changes and metadata enrichment.

The private HF catalogue is data/library.json with schemaVersion:1/mediaKind:manga/entries. Each chapter has one manifest under data/manifests/<ch_id>.json, with page references relative to data/. Original image bytes remain under data/manga/. Covers have separate private descriptors and image files. Private control/ and ingest/ subtrees store backups, rights evidence, provenance and checkpoints.

A human-readable reader URL is resolved by the Manga Library. A slug change is **not** a reason to change an opaque ID.

## Trust model

Inputs are untrusted: archive paths, candidate JSON, filenames, provider references and image headers. Sources are constrained by member counts, path rules, symlink rejection, decompression ratios and input budgets. Images undergo signature/decoder checks, dimension limits and SHA-256 verification. Metadata is matched by stable manga ID and vetted provider source edition; title-only matches are never silently applied.

Private dataset uploads require approved plan, exact prior SHA and conflict-free state. Existing object names and manual metadata must not be overwritten. For new manga, media batches are checkpointed and canonical catalogue entry publication happens last.

Never use browser links containing HF bearer tokens. The reader's authenticated gateway handles private asset delivery. Rights evidence is retained only privately, and owner-requested private retention is not an independent redistribution licence.

## CLI surfaces

**Original offline commands:** python -m taiyou_manga fixtures/scan/manifest/verify/inventory/plan-upload/mock-upload/backup/check-backup/restore/identity-migrate, plus offline-menu. Offline operations should run without Hugging Face credentials.

**Private management commands:** python -m taiyou_manga.hf_cli with bulk-upload, download, list, conflicts, verify, sync, backup-catalogue, restore, delete, upload-covers, covers, chapters, compare-retriever, health, metadata-report, metadata, cleanup and menu. Default 00_manga_storage_menu.cmd enters the Novel-style private management menu.

## CI and live evidence

Normal ci.yml runs Ruff, mypy, unittest and pip-audit on Windows/Linux, Python 3.11/3.12 with synthetic inputs. No private content is needed.

A separately protected live read-only smoke workflow checks private data at one revision. Historic one-off upload/migration workflows may contain private writes and should never be triggered as generic CI. The existence of an Actions workflow is **not evidence** that a live upload succeeded.

## Architectural limitations and extensions

- The on-disk candidate bundle is an intermediate format, not the canonical HF dataset.
- The fast file-list integrity audit is not an image byte audit; manifest mode checks paths and deep mode decodes actual page images.
- Generic bulk upload and de-list tools have synthetic tests, but isolated staging/production acceptance should precede any new risky live mutation.
- Source path moves require explicit identity-migrate procedure; do not infer new IDs.
- Client-side progress, personal tags and collections are outside this package.
- Browser reader UX, offline asset caching and private media authentication belong to Manga Library.
- Dangerous full-dataset wipe and irreversible per-title purge remain unavailable.

For fuller design, operational usage and failure handling, start with [REPOSITORY_HANDBOOK.md](REPOSITORY_HANDBOOK.md) and [AI_AGENT_PLAYBOOK.md](AI_AGENT_PLAYBOOK.md).
