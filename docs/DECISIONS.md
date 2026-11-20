# Architecture and Operational Decisions

**Updated:** 20 November 2026. This is a **dated decision log**, not an authorisation to perform new private data mutations. Earlier design restrictions remain part of the history but are clearly marked when superseded.

| Date | Decision | Rationale / consequences |
|---|---|---|
| 18 November 2026 | Public Controller code, private manga assets and rights evidence | GitHub holds no original pages, covers, private exports, credentials or personal media |
| 18 November 2026 | Python 3.11/3.12 with Pillow; Windows and Linux CI | Portable owner-friendly scripts, synthetic media-only test matrix |
| 18 November 2026 | Manga Library v1 page and chapter ID contract | Stable opaque identities and private page assets, not an EPUB-shaped schema |
| 18 November 2026 | Support ZIP/CBZ and folders as **input** only | Intermediate source bundle must be validated, never uploaded using legacy root paths |
| 18 November 2026 | Identity registry locking and atomic replacement | Avoid concurrent lost identities; path moves require explicit previewed mapping |
| 18 November 2026 | Local mock previews, no cloud writes at initial milestone | Establish safety and contract tests before private live integration |
| 18 November 2026 | Full media backups differ from catalogue JSON backups | A catalogue-only copy cannot recover original pages |
| 20 November 2026 | Owner authorised specifically scoped private ReLIFE upload | Validation, expected-parent writes and provenance required; **not** redistribution permission |
| 20 November 2026 | Canonical private dataset at AdityaSreevatsaK/Taiyous-Manga | data/library.json schemaVersion 1, mediaKind manga; manifests and image assets under data/ |
| 20 November 2026 | ReLIFE legacy root layout migrated to data/ and retained as recovery originals | Never use root catalogue.json for future publication; preserve existing IDs and media |
| 20 November 2026 | Four additional selected manga uploaded and enriched alongside ReLIFE | All five source records received verified publication metadata and original covers under owner-requested private storage |
| 20 November 2026 | Add optional cover, creatorRoles and metadataSources | Private original cover assets, author/artist roles, per-field source evidence; no token/signed URL in catalogue |
| 20 November 2026 | Adopt Novel Controller-style management workflows for manga (PR #28) | 20-option menu for catalogue listing, bulk upload/download, conflict reports, integrity, backup, cover import, metadata and safe delist/restore; no EPUB schema reuse |
| 20 November 2026 | Keep whole-dataset wipe disabled | One mistaken menu action must not erase the full private manga collection |
| 20 November 2026 | Single-manga delete is reversible **catalogue de-list** | Original pages/manifests/covers preserved; pre-change catalogue backup and exact-title confirmation |
| 20 November 2026 | Every future private write requires its own preview and explicit authorisation | A prior batch's approval cannot become a blanket permission to upload arbitrary chapters or purge media |
| 20 November 2026 | Validate live private state with read-only protected workflow (PR #30) | Avoid claiming implementation success solely from synthetic tests, PR merge or partial workflow results |
| 20 November 2026 | Consolidate current docs and AI operating instructions | Future sessions must not mistake obsolete migration-hold and offline-only notes for active requirements |

## Superseded restrictions

The original 18 November statement that **all Hugging Face writes were unimplemented** was accurate then but is **superseded** by subsequent reviewed, scoped private workflows and general management code.

The old 20 November **"no further uploads until ReLIFE canonical migration"** hold was a necessary safety gate during the migration. The migration and five-manga private data backfill were subsequently verified. That hold is **not a permanent ban**, though every new write still needs a fresh approved plan, validated source rights, revision guard and recovery strategy.

The original "cover path planned as WebP" example is superseded by the actual optional cover descriptor accepting the verified **original** PNG/JPEG/WebP/AVIF extension. Do not normalise to one image format without an explicitly approved conversion project.

Some older standalone migration write-ups intentionally retain their pre-migration warnings as historical procedure. Do not delete or rewrite their technical evidence; refer to the current [DATA_CONTRACTS.md](DATA_CONTRACTS.md) and [REPOSITORY_HANDBOOK.md](REPOSITORY_HANDBOOK.md) for operations today.

## Decisions still requiring case-specific owner review

- Approval, provenance, appropriate rights and source edition for **each new** manga or cover.
- Staging and rollback requirements before new categories of real HF operations.
- True permanent deletion, pruning legacy media or full-dataset cleanup (not implemented).
- Storage schema changes, including reader-compatible cover/creator metadata expansion.
- Private reader access or Cloudflare gateway changes (Manga Library repo).
- Source acquisition and website support (Manga Retriever repo).
- Data retention, independent full-media backup cadence and disaster recovery arrangements.

The date of a decision does not provide current dataset status. Always read the latest private SHA before asserting that a title is present or an operation is safe.

[AI Agent Playbook](AI_AGENT_PLAYBOOK.md) | [Repository Handbook](REPOSITORY_HANDBOOK.md)
