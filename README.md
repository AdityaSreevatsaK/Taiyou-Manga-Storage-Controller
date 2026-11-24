# Taiyou Manga Storage Controller

**The control plane for Taiyou's private Manga Library.** A Python 3.11/3.12, Windows-friendly tool for safely importing, verifying, managing, backing up and repairing original-image manga stored in a **private Hugging Face dataset**.

The public repository contains code and synthetic tests, **never private manga content**. It is not the manga reader, a scraper, an EPUB tool or a public hosting service.

## Start here

| Audience | Primary documentation |
|---|---|
| Owner using the Windows menu | [Windows and HF operating guide](docs/OPERATIONS.md) |
| New engineer exploring the repo | [Complete repository handbook](docs/REPOSITORY_HANDBOOK.md) |
| **AI coding agent** | **[AGENTS.md](AGENTS.md)** and [AI Agent Playbook](docs/AI_AGENT_PLAYBOOK.md) |
| New session / handover | [Ready-to-copy AI session prompt](docs/SESSION_HANDOVER_PROMPT.md) |
| Integrating Reader / Retriever | [Canonical data contract](docs/DATA_CONTRACTS.md) |
| Reviewing storage/security | [Architecture](docs/ARCHITECTURE.md), [Decisions](docs/DECISIONS.md), [Safety and recovery](docs/SAFETY_AND_RECOVERY.md) |
| Comparing against Novel Controller | [20-option feature parity](docs/NOVEL_CONTROLLER_PARITY.md) |
| Future priorities | [Current roadmap](docs/ROADMAP.md) |

**Important:** The Controller was initially offline-only, and some historical docs describe the earlier ReLIFE migration hold. That migration **completed**. Follow the current handbook, data contract and code rather than a dated migration warning.

## What you can do

- Import original image folders and ZIP/CBZ chapter sources into verified local manga bundles.
- Preserve stable opaque manga, chapter and page IDs through ordinary title changes.
- Create and verify private original-media backups; use a local mock for safe previews.
- Manage a private Hugging Face catalogue: bulk upload/download, list titles, detect title/alias conflicts, check integrity and sync status, export chapters and health reports.
- Import original cover ZIPs and source publication metadata with provenance and manual-value protection.
- Back up the canonical catalogue before remote updates.
- Reversibly de-list a single manga without deleting any media, and restore its catalogue entry from the saved private backup.

The **whole-dataset wipe option is disabled**. Permanent deletion, public media hosting and source scraping are not part of the Controller.

## Current storage model

Private dataset: **AdityaSreevatsaK/Taiyous-Manga**.

    data/library.json                      # v1: schemaVersion, mediaKind, entries
    data/manifests/<ch_id>.json            # chapter/page order, original hashes
    data/manga/<mng_id>/<ch_id>/<pg_id>.<original-extension>
    data/covers/<mng_id>.<original-extension>
    control/...                            # pre-change backups, rights, audit
    ingest/...                             # ingestion checkpoints

The reader owns URL slugs, private asset serving, offline reading, bookmarks, reading progress, personal tags and collections. Those are not the Controller's catalogue fields.

**Dated evidence, not a permanent inventory:** On 20 November 2026, a protected read-only live check verified **5 manga, 587 chapters, 14,635 pages and five real covers with metadata**, at dataset revision 0942616f03e165c7f9e4258110c9fdb4b085f1fc. See [the verified run](https://github.com/AdityaSreevatsaK/Taiyou-Manga-Storage-Controller/actions/runs/44721448011). Check the current revision before making claims about live data.

## Quick start: Windows

In PowerShell or Command Prompt:

    git clone https://github.com/AdityaSreevatsaK/Taiyou-Manga-Storage-Controller.git
    cd Taiyou-Manga-Storage-Controller
    py -3.11 -m venv .venv
    .venv\Scripts\python.exe -m pip install -e ".[huggingface]"
    .venv\Scripts\python.exe -m taiyou_manga menu

You can also open **00_manga_storage_menu.cmd** once the package is installed. The default interactive menu provides 20 numbered options. For the original **offline** local menu, run:

    .venv\Scripts\python.exe -m taiyou_manga offline-menu

Set an appropriately scoped private HF_TOKEN environment variable in your current terminal before cloud operations. Do **not** hardcode it or add it to tracked files.

## Flat numbered JPG/PNG manga importer

If a manga arrives as a **single folder** of images named `1_0.jpg`, `1_1.jpg`,
`1_10.jpg`, `2_0.jpg`, etc., the Controller can group the chapters
numerically, verify every image and prepare the **same canonical manga
catalogue and page manifests** already consumed by the Manga Library.

Use **Windows menu option 21** for a guided preview, bundle build and optional
approved Hugging Face upload, or follow
[Flat manga import instructions](docs/IMPORT_FORMATS.md#flat-numbered-chapter_page-image-import).
For the Manga Library agent, use the
[exact integration note](docs/LIBRARY_FLAT_CHAPTER_IMPORT_CONTRACT.md).

## Secure GitHub / ChatGPT agent-operated imports

For large private manga ZIPs, the owner can validate locally and **stage one
verified private bundle**, then let a ChatGPT agent issue GitHub Actions
preview and apply commands through the connected GitHub account. Original
artwork and access tokens are **never added to this public repository**.

See [GitHub agent private import guide](docs/GITHUB_AGENT_PRIVATE_IMPORT.md)
for the Windows staging command, protected Actions workflow and the dedicated
owner-only import queue.

## Basic commands

Use **python -m taiyou_manga.hf_cli** for private HF catalogue management:

    python -m taiyou_manga.hf_cli list --output reports/manga-list.csv
    python -m taiyou_manga.hf_cli conflicts --output reports/duplicate-titles.csv
    python -m taiyou_manga.hf_cli verify --mode quick --output reports/integrity.json
    python -m taiyou_manga.hf_cli verify --mode manifest --output reports/manifests.json
    python -m taiyou_manga.hf_cli metadata-report --output reports/metadata.json
    python -m taiyou_manga.hf_cli health --output reports/health.html
    python -m taiyou_manga.hf_cli backup-catalogue --output backups/library.json
    python -m taiyou_manga.hf_cli download --destination downloads

For an approved new upload or metadata repair, **preview first** and apply only the reviewed, still-current plan with explicit approval. Examples and recovery procedures are in [OPERATIONS.md](docs/OPERATIONS.md).

### Safe offline demo

No private token or copyrighted source media is needed:

    python -m taiyou_manga fixtures --output demo_manga
    python -m taiyou_manga scan --source demo_manga
    python -m taiyou_manga manifest --source demo_manga --output bundles/demo-1 --rights-json demo_manga-rights-example.json
    python -m taiyou_manga verify --bundle bundles/demo-1
    python -m taiyou_manga plan-upload --bundle bundles/demo-1 --mock-dir mock_remote
    python -m taiyou_manga backup --bundle bundles/demo-1 --output backups/demo-1.zip
    python -m taiyou_manga check-backup --backup backups/demo-1.zip

The local candidate bundle is not the canonical HF data/ layout. The mock cannot modify production.

## Development and CI

Install development dependencies:

    python -m pip install -e ".[dev]"
    python -m unittest discover -s tests -v
    python -m ruff format --check .
    python -m ruff check .
    python -m mypy src/taiyou_manga
    python -m pip_audit

Normal [CI](.github/workflows/ci.yml) runs these checks with synthetic inputs on **Windows and Linux, Python 3.11 and 3.12**. It never requires original manga images or private HF write tokens.

Some *separately protected*, historically owner-authorised GitHub workflows have performed real HF data operations; treat them as special cases requiring review, not reusable generic import tools. The [read-only live management smoke](.github/workflows/private-manga-management-smoke.yml) validates the private catalogue but has dated five-title expectations that must be updated as the library grows.

The original source registry and private exports stay in ignored locations such as .manga-controller/, reports/, backups/, downloads/, private/ and bundles/. Never commit those files.

## Safety and rights

- No public manga assets, cover images, private provenance or passwords in the code repository.
- Existing manga/chapter/page IDs, original bytes and manual metadata must be preserved.
- A private write requires a validated source, owner approval for the exact operation, a preview at the current revision, a pre-change catalogue backup and post-commit verification.
- A catalogue backup alone is **not** an independent full-media backup.
- Permission for private retention does not grant copyright redistribution rights.
- Whole-dataset deletion remains disabled. Normal "Delete manga" is reversible catalogue de-listing, retaining originals.

**For AI agents, [AGENTS.md](AGENTS.md) is mandatory before changing code.** This repository uses an MIT licence for its software; the licence does **not** apply to third-party manga artwork.
