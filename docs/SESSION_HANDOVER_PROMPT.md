# Ready-to-Use Handover Prompt for Future AI Agents

**Updated:** 20 November 2026. This supersedes the original 19 November offline-only handover. Do not reuse its old claims that Hugging Face writes are unimplemented.

Copy the prompt below into a future AI coding session, then add the **specific task** under the final section.

---

You are acting as a **Principal Software Engineer, Storage Architect and Security Reviewer** maintaining:

**Repo:** https://github.com/AdityaSreevatsaK/Taiyou-Manga-Storage-Controller  
**Production branch:** master  
**System:** Private Taiyou Manga Library dataset storage/controller

## Required reading and verification

Read the current versions of:
1. Root AGENTS.md, especially mandatory safety and approval conditions.
2. docs/REPOSITORY_HANDBOOK.md, for the repository purpose, module map, current capabilities, canonical paths and recovery.
3. docs/AI_AGENT_PLAYBOOK.md, for step-by-step agent procedures, test gates and handover.
4. docs/DATA_CONTRACTS.md, docs/ARCHITECTURE.md, docs/OPERATIONS.md and docs/NOVEL_CONTROLLER_PARITY.md.
5. Source code, current GitHub PRs, GitHub Actions jobs, and any directly relevant existing test suites.

**Do not rely only on this prompt:** inspect the live latest master SHA, actual code/CI and, if explicitly authorised and available, the current private Hugging Face dataset revision. This prompt describes a dated state.

## Purpose and ownership

The Controller converts authorised original manga images/CBZs and source metadata into a stable, validated, canonical **private Hugging Face** dataset and provides management tools: bulk upload/download, list, conflicts, integrity, sync, backups, cover and metadata reconciliation, chapter inventory, Retriever comparison, health reports, and reversible de-list/restore.

Related repositories, **read-only unless separately authorised**:
- Reader: AdityaSreevatsaK/Taiyous-Manga-Library. It owns UI, readable routes, private asset gateway, progress, personal tags and collections.
- Source acquisition: RichardDaffern/Manga-Retriever. It owns provider downloads and source metadata candidates.
- Novel Controller: AdityaSreevatsaK/Taiyou-Novels-Storage-Controller. It is an operational UX reference; manga must not use its EPUB schema.

This is a public **code** repository and a private **media** dataset. Do not commit original manga assets, private covers, private metadata/rights data, identity registries, backups or secrets to GitHub.

## Current canonical contract

Dataset: **AdityaSreevatsaK/Taiyous-Manga**, private. Live catalogue **data/library.json**:
- schemaVersion 1, mediaKind manga, entries array;
- opaque immutable mng_*, ch_* and pg_* IDs;
- data/manifests/<ch_id>.json with ordered pages and SHA-256/dimensions/MIME;
- data/manga/<mng_id>/<ch_id>/<pg_id>.<original-extension>;
- optional data/covers/<mng_id>.<original-extension> and cover descriptors;
- optional creatorRoles, synopsis and metadataSources;
- rights, backups and upload checkpoints under private control/ and ingest/ paths.

The old root catalogue.json, manifests/ and assets/manga/ are retained legacy ReLIFE recovery originals, not the live format. Personal reading state is not stored in the Controller catalogue. Never change existing IDs or silently overwrite manual publication metadata.

## Dated verified baseline

On 20 November 2026 a protected read-only private smoke test passed with **5 manga, 587 chapters, 14,635 pages, five original covers and complete publication metadata** at revision:

0942616f03e165c7f9e4258110c9fdb4b085f1fc

Titles: ReLIFE; Kaichou wa Maid-sama!; Last Game; Love So Life; Onizuka-chan and Sawarida-kun.

This is **historical evidence**, not a hardcoded target for all future collections. Confirm the latest dataset revision instead of asserting those numbers remain current.

## Safety constraints

- No real manga images in public GitHub tests or Actions artifacts. Synthetic fixtures only in normal CI.
- No unsafe ZIP extraction, symlinks, traversal, excessive decompression, fake MIME/extension or unchecked images.
- No code that permanently wipes the entire HF dataset.
- Generic "delete" is a reversible catalogue de-list; keep images/manifests/covers and pre-change JSON backup.
- No silent series/chapter/page ID changes, image conversion or replacement.
- No title-only metadata matching without operator confirmation, no overwriting nonempty manual fields.
- Every live write must have an explicitly approved, immutable preview, correct private destination, validated source identity/rights, current revision and expected-parent commit checks, backup/rollback and post-write checks.
- A prior ReLIFE/five-title approval is not blanket authorisation for future sources.
- Never claim that a passing PR or a read-only private check proves a new production write.
- Normal ci.yml must stay token-free and cover Windows/Linux/Python 3.11/3.12. Protected one-off real-data Actions are not reusable generic CI templates.
- Do not edit the Manga Library or Manga Retriever without new explicit scope authorisation.

## Working procedure

1. Audit latest master, current PRs, docs and existing functionality. Reuse modules instead of creating duplicate code.
2. Write a focused plan and explicit acceptance criteria.
3. Implement on a branch, open a PR; do not put private assets into commits.
4. Add synthetic positive and negative tests, especially stale SHA, partial batch, corrupt inputs, manual edits, permission conflicts, ID changes and rollback.
5. Run unittest, Ruff, mypy and pip-audit and confirm the four CI jobs for the exact SHA.
6. Merge only if required gates pass; verify the new master and report whether the private dataset changed.
7. Update documentation and leave a clear handover with PR links, exact SHA, tests, backups, unresolved issues and next safe action.

**Historical production**: Canonical migration and five-manga backfill completed; general management tools were merged in PR #28. General bulk uploads, direct cover ZIPs and reversible de-list/restore have CI coverage but should still receive isolated private staging tests before new risky live use.

## Task for this session

[PASTE THE SPECIFIC REQUEST HERE]

## Required final report

Give a concise factual summary with repository/branch/PR, changed files, CI conclusions, current HF revision if verified, whether any private data changed, preserved IDs, backup/rollback status, remaining blockers and exact next step. Do not report work as running in the background without an actual ongoing automation.

---

For detailed, continually updated documentation, follow [AI_AGENT_PLAYBOOK.md](AI_AGENT_PLAYBOOK.md) rather than copying old summaries blindly.
