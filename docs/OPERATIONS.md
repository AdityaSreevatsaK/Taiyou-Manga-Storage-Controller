# Windows and Private Hugging Face Operating Guide

**Updated:** 20 November 2026. Begin with [Repository Handbook](REPOSITORY_HANDBOOK.md) for architecture and recovery. For the complete menu mapping, see [Novel Controller Parity](NOVEL_CONTROLLER_PARITY.md).

## 1. Install on Windows

From the public Manga Storage Controller checkout:

    py -3.11 -m venv .venv
    .venv\Scripts\python.exe -m pip install -e ".[dev,huggingface]"

Keep a private scoped HF_TOKEN environment variable in the current shell. For PowerShell, use the standard $env:HF_TOKEN variable in your session. Never paste token values into issues, Markdown, screenshots, GitHub source files or scripts.

Open **00_manga_storage_menu.cmd** or:

    .venv\Scripts\python.exe -m taiyou_manga menu

The main menu offers 20 options including bulk upload/download, list, conflict checks, status, integrity, sync, catalogue backup, covers, metadata, Retriever comparison and **reversible** single-manga de-list/restore. The full dataset clear option is deliberately disabled.

## 2. Read-only status first

From an activated virtual environment:

    python -m taiyou_manga.hf_cli list --output reports/manga-list.csv
    python -m taiyou_manga.hf_cli conflicts --output reports/duplicate-titles.csv
    python -m taiyou_manga.hf_cli metadata-report --output reports/publication-metadata.json
    python -m taiyou_manga.hf_cli verify --mode quick --output reports/integrity-quick.json
    python -m taiyou_manga.hf_cli verify --mode manifest --output reports/integrity-manifests.json
    python -m taiyou_manga.hf_cli health --output reports/health.html

The reports/ folder is ignored by Git. Each new report must use a **new** output path. "Quick" verifies path presence and high-level counts; "manifest" reads real chapter manifests and checks page path existence; "deep" decodes original image bytes and hashes and may be slow for large libraries.

A report is private even if it contains no images: manga titles, author names, source evidence, manifest IDs and collection inventories should not be publicly attached by default.

## 3. Bulk manga upload

Input must be existing verified single-manga local bundle(s), not arbitrary unvalidated CBZs. Use the offline manifest builder first:

    python -m taiyou_manga scan --source "C:\Manga\AuthorisedInput"
    python -m taiyou_manga manifest --source "C:\Manga\AuthorisedInput" --output bundles\example --state-file .manga-controller\ids.json --rights-json private\rights.json
    python -m taiyou_manga verify --bundle bundles\example

Check the inferred chapters, rights declaration, source and immutable ID registry. The local bundle is **not** the live HF layout.

Then preview the general append-only uploader:

    python -m taiyou_manga.hf_cli bulk-upload --source bundles --plan-file reports/upload-preview.json

Read every record, title/alias conflict, existing/new status, hash and expected remote revision. Only after the owner has specifically approved that exact plan:

    python -m taiyou_manga.hf_cli bulk-upload --source bundles --plan-file reports/upload-preview.json --apply --approve

Media is uploaded in bounded checkpointed batches; the new manga's catalogue entry is published only after its page objects/manifests are verified. Existing titles/occupied paths cannot be silently replaced. If a network interruption occurs, inspect the remote revision and regenerate the preview rather than using a stale plan.

## 4. Download and back up

Download all original images/manifests/covers into one ZIP per manga:

    python -m taiyou_manga.hf_cli download --destination downloads

Download a specific manga only:

    python -m taiyou_manga.hf_cli download --destination downloads --manga-id mng_...

Existing ZIPs are not blindly overwritten; current implementation checks the saved manifest/revision and ZIP integrity before skipping. Retain the manifest and checksum records. This is an **export**, not automatic proof of a rehearsed disaster recovery plan.

Catalogue-only copy (small, fast, but **not** a media backup):

    python -m taiyou_manga.hf_cli backup-catalogue --output backups/library.json

Before any operation risking existing media, independently verify a complete off-platform backup and rehearse restoration in a separate private location. Do not use the HF repository's own branches as the only safety copy.

## 5. Cover and publication metadata

Two compatible input methods:

    python -m taiyou_manga.hf_cli metadata --candidates private\candidates.json --plan-file reports\metadata-plan.json
    python -m taiyou_manga.hf_cli upload-covers --zip private\covers.zip --plan-file reports\cover-plan.json

For cover ZIPs, the archive must contain exactly one metadata.json or candidates.json and original images under covers/. The ZIP is securely extracted only temporarily and passed to the **same** candidate reconciler, which verifies source provenance, immutable manga identity, image bytes and rights declarations. Do not invent an alternative cover schema.

Use --apply --approve only after reviewing every changed field, existing metadata protection and private cover provenance. A clean syntactic preview is not an independent copyright licence.

## 6. Reversible de-list and restoration

There is **no** permanent delete-all operation. To hide one manga from the canonical catalogue while **retaining** all original pages and manifests:

    python -m taiyou_manga.hf_cli delete --manga-id mng_... --plan-file reports\delist-plan.json

After reviewing the exact title, ID and revision, and with specific owner approval:

    python -m taiyou_manga.hf_cli delete --manga-id mng_... --plan-file reports\delist-plan.json --apply --approve --confirm-title "Exact manga title"

The Controller writes a byte-identical pre-change catalogue backup under control/delist-backups/<revision>/library.json. For accidental removal, inspect the backup revision and preview:

    python -m taiyou_manga.hf_cli restore --manga-id mng_... --source-revision <revision> --plan-file reports\restore-plan.json

Restoration is separately approved; it verifies original chapter manifests and page paths without redownloading or rewriting existing images.

## 7. Other tools

    python -m taiyou_manga.hf_cli chapters --output reports/chapters.csv
    python -m taiyou_manga.hf_cli covers --output reports/missing-covers.csv
    python -m taiyou_manga.hf_cli compare-retriever --inventory private/retriever.json --output reports/retriever-comparison.csv
    python -m taiyou_manga.hf_cli sync --bundles bundles --output reports/sync.csv
    python -m taiyou_manga.hf_cli cleanup --destination downloads --output reports/cleanup-preview.json

Cleanup only removes old **local temporary .part files** with its separately documented exact confirmation phrase. It must never remove original ZIPs or remote media.

## 8. Offline and diagnostic functions

The historical local menu still exists:

    python -m taiyou_manga offline-menu

Useful commands:

    python -m taiyou_manga fixtures --output demo_manga
    python -m taiyou_manga inventory --bundle bundles\example
    python -m taiyou_manga export-csv --bundle bundles\example --output reports\example.csv
    python -m taiyou_manga plan-upload --bundle bundles\example --mock-dir mock_remote
    python -m taiyou_manga backup --bundle bundles\example --output backups\example.zip
    python -m taiyou_manga check-backup --backup backups\example.zip
    python -m taiyou_manga identity-migrate --state-file .manga-controller\ids.json --mapping-json private\path-change.json

The synthetic generator creates fictional images for safe CI. Mock upload does not contact HF. Identity migration is preview-only until separately approved with an exact expected revision and private backup.

## 9. Troubleshooting and evidence

- **HTTP 401/403:** check private dataset visibility and token scope; do not misclassify as missing manga.
- **Stale-plan/conflict:** re-read current HF SHA, compare source hashes and manual metadata; do not force apply.
- **Missing pages:** manifest mode identifies paths; deep mode validates actual file bytes. Do not invent IDs or repair manifests from guessed filenames.
- **Duplicated titles:** use aliases/IDs and source edition provenance to review manually.
- **Renamed/moved source folder:** use the backed-up identity registry and identity-migrate preview.
- **Interrupted upload:** inspect matching checkpoints and current revision; never overwrite existing uncheckpointed assets.

Record a run URL, current SHA and whether a private write actually occurred. A green synthetic CI result alone is not a production data update.

## 10. Developer checks

    python -m unittest discover -s tests -v
    python -m ruff format --check .
    python -m ruff check .
    python -m mypy src/taiyou_manga
    python -m pip_audit

The GitHub workflow checks Windows/Linux with Python 3.11 and 3.12.

See [AI Agent Playbook](AI_AGENT_PLAYBOOK.md) for contributor protocols and [Data Contract](DATA_CONTRACTS.md) for storage schema.
