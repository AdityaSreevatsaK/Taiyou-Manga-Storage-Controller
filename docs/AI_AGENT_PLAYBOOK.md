# AI Agent Playbook: Taiyou Manga Storage Controller

**Applies to:** coding agents, review agents, security agents and future ChatGPT/Codex sessions working in this repository. **Last verified:** 20 November 2026.

This file expands the mandatory short-form root [AGENTS.md](../AGENTS.md). Read the current [REPOSITORY_HANDBOOK.md](REPOSITORY_HANDBOOK.md), [DATA_CONTRACTS.md](DATA_CONTRACTS.md) and relevant source files before producing a plan or making modifications.

## A. Mission, boundaries and authority

You maintain the public codebase **AdityaSreevatsaK/Taiyou-Manga-Storage-Controller**, a private Hugging Face manga dataset management tool. You are responsible for:
- Reliable authorised import, validation and reconciliation of image-page manga.
- Correct canonical storage paths and stable manga/chapter/page IDs.
- Safe inventory, downloads, metadata, integrity auditing, backups and recovery.
- Security boundaries, cross-platform Windows/Linux operation and regression testing.
- Concise, accurate user-facing status based on actual tool evidence.

Do not treat this as a manga reader, chapter scraper or translation pipeline. The Manga Library and Manga Retriever are separate repositories. Never modify those repositories unless the owner has authorised that separate scope.

Do **not** infer permission to publish copyrighted material from a user request to store it privately. Public code and CI may include only synthetic assets. Access the owner's private dataset only for specifically requested, justified tasks using an approved protected mechanism.

### Source of truth hierarchy

1. **The owner's latest explicit instructions** and constraints (including paused work, prohibited actions or approval gates).
2. **The latest verified source code**, current branch/PR checks and the current private dataset revision where access is authorised.
3. **Root AGENTS.md**, current canonical contract and this playbook.
4. Current handbook, operational guides, tests, existing decisions.
5. Dated migration runbooks, session handovers, historical PR descriptions and conversational summaries.

If instructions conflict, report the conflict and choose the safer non-destructive option. Historical README statements about ReLIFE-only uploads or incomplete migration are obsolete; reconcile the documents with the latest code and live evidence instead of reverting the dataset.

## B. Mandatory start-of-session checklist

Before editing code, answer internally and then document succinctly:

1. **What is the exact target repository?** Check git remote, branch, SHA, default master and current open PRs. Do not trust a similar Novel Controller path.
2. **What is the requested outcome?** Separate user-visible behaviour from data-layer changes, and identify whether a live private dataset mutation is actually authorised.
3. **What exists already?** Read README.md, root AGENTS.md, the repository handbook, relevant code, tests, workflows and contracts. Search the code rather than implementing an unnecessary duplicate.
4. **What is the current canonical dataset revision?** If using private data, inspect visibility, exact SHA, catalogue and relevant paths. If no access, say "not verified" instead of guessing.
5. **Which identities are affected?** Explicitly enumerate manga IDs and chapter/page identity impact. Ensure title/slugs are display fields only.
6. **Which threat and failure modes apply?** Consider malformed archives, rights, privacy, stale revision, concurrency, partial upload, manifest mismatch, local symlinks and backup integrity.
7. **How will success be proved?** Define synthetic test coverage, CI matrix, read-only live checks and any staging-only mutation verification.
8. **Is a new owner approval required?** Do not infer durable authorisation for unrelated future media imports, cover replacement or deletion from a previous approved batch.

Prefer a focused branch and PR. Do not mix unrelated feature requests. Do not leave temporary diagnostic workflows or test artefacts behind.

## C. Critical data preservation rules

These are non-negotiable during ordinary engineering:

- **Immutable IDs:** Preserve existing mng_*, ch_* and pg_* values. The private .manga-controller/ids.json registry is not disposable; never regenerate it for an existing series to make tests pass.
- **Catalogue:** Read/write only the canonical data/library.json JSON envelope on Hugging Face. Never republish the old raw-array root catalogue.json or use the local bundle catalogue.json as live format.
- **Media:** Preserve original image bytes, extension, MIME and SHA-256. Never transcode, rename or rearrange original page objects as a side effect of metadata edits.
- **Manifest/page coupling:** A chapter manifest's page array is the reader order. Each page assetPath is data/-relative and refers to the same immutable manga and chapter.
- **Publication vs personal:** Do not write progress, bookmarks, personal ratings, personal tags, user notes, reading status or collections in publication catalogue operations.
- **Existing manual data:** Treat nonempty current metadata as protected. A new source with different values produces a conflict requiring review, never a silent overwrite.
- **Private paths:** Do not put public/signed media links, HF bearer tokens or arbitrary absolute paths in cover descriptors or metadata candidates.
- **Backup:** Before changing library.json, preserve exact pre-change bytes with SHA and parent revision; a JSON backup is not a full original-media backup.
- **Legacy data:** Root catalogue.json and legacy ReLIFE objects are retained recovery references; do not clean them up as "duplicates" without separate authorisation and independent full-media backup.

If a proposed change requires rewriting existing IDs, deleting originals or inventing page hashes, **stop and seek explicit owner approval** for that specific action, even if other parts of the task are approved.

## D. Private Hugging Face write gate

Before any **live write**, check **all** of the following. Missing evidence means fail closed.

1. User specifically authorised the targeted operation and media; publication/redistribution rights are not assumed.
2. Remote dataset is exactly the approved private AdityaSreevatsaK/Taiyous-Manga and reports private visibility.
3. Target manga IDs and any source edition IDs are explicitly verified.
4. Input is from a trusted operator-supplied path or vetted Retriever candidate and passes archive/image validation, SHA, MIME, dimensions, size and provenance checks.
5. Current catalogue is validated against schemaVersion 1 and all existing entries/IDs are preserved unless the specific operation is an approved reversible de-list.
6. A preview shows full intended changed fields, new files, conflicts, checksum/source digests and expected parent revision.
7. Existing nonempty/manual metadata and occupied media paths have no unresolved conflicts.
8. A pre-change catalogue backup and rollback path are recorded. If originals could be endangered, a verified independent media backup must exist.
9. Owner explicitly approved **this** preview, not an older similar plan. Destructive local cleanup also needs its documented exact typed phrase.
10. Commit uses expected-parent concurrency checks; checkpoints and catalogue publication order are safe.
11. Post-commit read-back verifies revision, catalogue, cover/media hashes and preservation of unrelated paths, plus counts against the approved plan.
12. Log a concise, non-sensitive result: run URL, previous/new revision, changed manga IDs/counts and any failures. Do not expose tokens, personal notes or original media URLs.

**Do not add or run a general "delete all dataset" command.** This remains intentionally disabled. The menu's "delete" action is only a reversible catalogue de-list; it preserves media. A separate true deletion/purge would require a new design, separate informed approval, an independent backup and end-to-end recovery rehearsal.

### No "helpful" auto-approval

Do not silently set --apply --approve as part of a background workflow, suppress conflict checks, downgrade a stale SHA gate, change the dataset ID or retry a failed commit without regenerating a current preview. A previous run's approval is not reusable if the source files, remote SHA or plan changed.

### Production workflow precautions

Normal .github/workflows/ci.yml uses synthetic fixtures and must not receive HF credentials. Several specifically authorised historical workflows have accessed real private data; they are exceptions, not templates to copy. Review their paths, environment gates, pinned data SHA, secret scope, artefact provenance, concurrency grouping and side effects before even dispatching one.

## E. Validation of untrusted input

**Input types:** ZIP, CBZ, page-image folder, candidate JSON and private cover ZIP.

Always enforce:
- Safe relative member names, no traversal, absolute paths, backslashes, embedded control characters, symlinks, special files or duplicate case-folded names.
- Bounded compressed and uncompressed bytes, ratio, entries, nesting depth and total size; do not extract untrusted content directly into the repository.
- Image file signature matching extension and MIME; complete image decode with Pillow; dimensions, pixel budget and per-file bytes.
- SHA-256, unique page IDs, safe asset paths, expected chapter count, sequence and pageCount.
- Provenance and permission checks; do not confuse a website address with ownership of copyright.
- Fail-closed behaviour on malformed documents, missing manifests or a mismatched source identity.
- Atomic/new-file local writes where supported; no accidental overwrite of a previous private export.

Images may contain extremely large dimensions despite small compressed sizes. Do not bypass the decode/memory budget. AVIF support depends on Pillow/platform; test availability rather than claiming universal support.

## F. Recommended work sequence for changes

1. **Audit:** inspect latest master and the relevant source/CI/tests; identify root cause and current behaviour.
2. **Scope:** choose only the Controller module(s); write acceptance criteria, explicit negative tests and data invariants.
3. **Branch:** create a focused feature/fix/docs branch from current master.
4. **Implementation:** prefer existing validators and canonical data contracts. Keep CLI commands cross-platform and Windows menu usable.
5. **Tests:** add synthetic unit/integration coverage for success and adversarial cases: stale revisions, duplicate titles/aliases, malformed ZIPs, occupied remote paths, conflicting metadata, partial batches, missing manifests and incorrect authorisation.
6. **Quality:** run Ruff format/check, mypy, unittest and dependency audit. Check Windows + Linux, Python 3.11 + 3.12.
7. **PR:** explain behaviour, exact changed files, preserved data, rollback, limitations and tests; do not include source manga images.
8. **Verification:** confirm actual job conclusions. CI "queued" or skipped does not mean green.
9. **Merge:** only after required gates and explicit data/policy approvals. Prefer normal PR workflows to direct changes on master.
10. **Post-merge:** verify master SHA and resulting workflow. For live data requests, report the actual private revision and independent verification; otherwise say "code merged, live data unchanged".
11. **Documentation:** update AGENTS/handbook/contracts, including dated evidence and deprecated procedure notes. Remove temporary workflows.
12. **Handover:** give next agent exact current status and blockers without promising work is ongoing after this turn.

### Quality command reference

    python -m pip install -e ".[dev,huggingface]"
    python -m unittest discover -s tests -v
    python -m ruff format --check .
    python -m ruff check .
    python -m mypy src/taiyou_manga
    python -m pip_audit

If a test fails on one Python or Windows runner, read its failure log, fix the underlying issue and re-run the complete matrix. Do not silently reduce test coverage, turn off lints or remove strict validation merely to make a workflow green.

## G. Where to change things

| Request | Primary code area | Key tests |
|---|---|---|
| New scan format, ZIP/CBZ import | sources.py, images.py, builder.py | test_bounded_import.py, test_controller.py |
| Chapter/page schema | domain.py, hf_layout.py | test_hf_layout.py, test_registry_validation.py |
| Source registry IDs, rename | builder.py, identity_migration.py | test_identity_migration.py, test_registry_concurrency.py |
| General remote uploads | hf_bulk.py, hf_cli.py | test_hf_operations.py, test_hf_upload.py |
| Private cover ZIP input | hf_cover_zip.py, metadata.py | test_hf_cover_zip.py, test_metadata.py |
| Publication metadata | metadata.py, hf_metadata.py | test_metadata.py |
| Catalogue listing, download, backups, health and de-list | hf_manage.py, hf_extra.py | test_hf_operations.py |
| Reader contract coordination | DATA_CONTRACTS.md and Manga Library's types/validation in read-only mode | add contract tests with synthetic entries |
| ReLIFE historical recovery | hf_canonical_migrate.py, hf_recovery.py, relife_stage.py | test_hf_canonical_migrate.py, test_hf_recovery.py |
| Existing selected-title workflows | selected_hf_upload.py, selected_stage.py | test_selected_hf_upload.py, test_selected_stage.py |
| Windows user experience | hf_cli.py, cli.py, 00_manga_storage_menu.cmd | CLI tests, Windows CI |

Never claim a module's tests are exhaustive merely because one file has a matching name. Examine the actual test assertions.

## H. Failure patterns to guard against

**Wrong canonical layout:** Legacy root catalogue.json is not data/library.json. Fixing a reader ingestion issue by reshuffling IDs is unacceptable. Preserve immutable keys and use safe canonical path reconciliation.

**Cover and metadata mismatch:** A title may have multiple editions, scripts or aliases. Accept stable ID matches with source-edition verification; title-only matches require review. Preserve manual publication metadata and provenance. Never attach the first visually plausible cover.

**Partial upload:** Check immutable checkpoints and the current parent SHA. Do not publish a chapter catalogue reference before its page files and manifests are present.

**Existing downloaded ZIP:** Do not assume "file exists" means valid; examine its revision, backup manifest and ZIP integrity before skipping. Never overwrite a previous complete backup without a deliberately new destination.

**Private HF access errors:** A failed download/401/403 is not a missing manga. Confirm correct token scope, dataset privacy and revision before interpreting availability.

**Data loss from cleanup:** No script should automatically delete original pages, legacy recovery objects, rights sidecars, personal records or verified media backups during ordinary migration or deduplication.

**Documentation drift:** Update reference docs when adding new operations or finishing a migration. Do not leave AGENTS.md forbidding functionality that is already safely implemented, and do not silently erase the historical rationale.

## I. Status reporting and evidence discipline

Use the following labels precisely:
- **Implemented locally:** code and unit tests exist, but no remote deployment proof.
- **PR open:** branch exists and PR has not been merged.
- **CI passed:** all required jobs for the exact SHA concluded success.
- **Merged:** exact PR merged to master.
- **Read-only live verified:** actual private dataset or manifest read succeeded at a recorded revision.
- **Production write confirmed:** an approved private commit completed, post-write validation passed, and the new SHA is known.
- **Blocked/pending:** state the exact owner approval, missing artefact, failed check or unavailable tool.

If access to a tool is missing, do not invent a GitHub or Hugging Face action, job ID, success flag or download link. Give a bounded diagnosis and a ready-to-run set of commands instead.

A useful final user report says what changed, where (PR/file), how it was tested, whether private data changed, and exactly what remains.

## J. Session handover template

Copy and fill this at the end of a large task:

    Repository:
    Branch / base SHA:
    PR / CI links and conclusions:
    Scope explicitly approved:
    What is already implemented:
    Source files changed:
    Test files changed:
    Canonical dataset repo, privacy and revision (only if verified):
    Media and catalogue impact:
    Immutable IDs preserved?:
    Pre-change backup and rollback location:
    Pending conflicts / questions:
    Known limitations:
    Immediate next safe action:
    Operations explicitly NOT performed:

The next agent must independently check the repo and live state again before applying a write. Do not reuse the previous session's approved plan if the dataset SHA has moved.

## K. Non-goals and intentional safeguards

The Controller does **not**:
- Download or scrape unauthorised manga pages.
- Work as a public image server or share HF media access tokens with the browser.
- Assign readable URL slugs for reader routes.
- Implement manga annotations, progress, rating, collection membership or personalised tags.
- Automatically fix publication metadata by asking an LLM to guess author, genre or status.
- Replace original images with compressed versions by default.
- Rebuild missing chapter manifests from guessed page numbering.
- Purge the entire private dataset.

These are deliberate boundaries. Escalate proposals that would cross them rather than quietly extending scope.

## L. Document index and maintenance

- [Repository Handbook](REPOSITORY_HANDBOOK.md): purpose, architecture, current state, schema, commands, recovery and limitations.
- [Data Contract](DATA_CONTRACTS.md): canonical dataset and page/cover metadata.
- [Architecture](ARCHITECTURE.md): component boundaries and data flow.
- [Novel Controller Parity](NOVEL_CONTROLLER_PARITY.md): 20-option menu details.
- [Metadata Reconciliation](METADATA_RECONCILIATION_CONTRACT.md): source candidate and cover safety contract.
- [Safety and Recovery](SAFETY_AND_RECOVERY.md): older recovery details, may include historical limitations.
- [Identity Migration](IDENTITY_MIGRATION.md): private registry moves.
- [Testing](TESTING.md): historical cases and commands; confirm latest CI separately.
- [Decisions](DECISIONS.md): rationale, dated decisions and supersessions.
- [Roadmap](ROADMAP.md): completed milestones and work still subject to approval.

When the implementation changes, update this index, README entry points and all affected active contracts. Prefer to mark a historical instruction superseded and link current policy rather than silently rewriting the migration history.
