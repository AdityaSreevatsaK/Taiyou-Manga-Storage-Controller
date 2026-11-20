# AI Agent Operating Contract

**Repository:** AdityaSreevatsaK/Taiyou-Manga-Storage-Controller.
**Canonical branch:** master. **Updated:** 20 November 2026.

**Mandatory reading:** [Repository Handbook](docs/REPOSITORY_HANDBOOK.md), [AI Agent Playbook](docs/AI_AGENT_PLAYBOOK.md), [Canonical Data Contract](docs/DATA_CONTRACTS.md), and the actual code/tests relevant to the current task. These documents provide detail; this file gives the essential guardrails.

## Your mission

Maintain the **public Python-based controller for the owner's private manga dataset**. Its responsibilities are validated manga image/CBZ imports, stable IDs, canonical Hugging Face metadata and covers, safe bulk uploads/downloads, catalogue inventory, quality checks, recovery, and non-destructive lifecycle management.

The controller **is not** the Manga Library reader, a scraper, a translator, a Cloudflare backend or the Novel Controller. Related repositories are:
- Manga Library: AdityaSreevatsaK/Taiyous-Manga-Library (private reader, UI, progress, private asset gateway).
- Manga Retriever: RichardDaffern/Manga-Retriever (source discovery, download artefacts and source metadata).
- Novel Controller: AdityaSreevatsaK/Taiyou-Novels-Storage-Controller (operational UX reference, not a manga data contract).

Do not edit unrelated repositories without separate explicit owner approval.

## Start every task by checking reality

1. Inspect latest master SHA, status, open PRs, GitHub Actions conclusions and affected code/tests.
2. Read this file and the relevant current contracts. Dated migration write-ups and old conversation summaries may be obsolete.
3. Distinguish implementation, merged changes, successful CI, **read-only private validation** and **confirmed production writes**. Never conflate them.
4. For tasks involving the private dataset, fetch the **current** dataset SHA and verify it is private. If access is unavailable, state that honestly.
5. Identify exact manga, chapter and page IDs affected, expected backups and rollback.
6. Scope work to a focused branch and PR. Do not bypass required CI gates.
7. A new request for documentation or code does **not** authorise a live HF mutation.

## Non-negotiable invariants

- Private HF dataset: **AdityaSreevatsaK/Taiyous-Manga**. Source code is public; original manga pages, covers, identity registries, private inventories, backups, permission records and credentials are not.
- Canonical live catalogue: **data/library.json** with exactly schemaVersion 1, mediaKind "manga" and entries. Local catalogue.json is a **candidate bundle**; root catalogue.json is historical legacy backup, **not** the live reader catalogue.
- Canonical original page path: data/manga/<mng_id>/<ch_id>/<pg_id>.<original-extension>. Chapter manifests: data/manifests/<ch_id>.json. Private covers: data/covers/<mng_id>.<original-extension>.
- Preserve immutable mng_*, ch_* and pg_* IDs, chapter sequence and manifest page ordering. Human-readable manga titles or URL slugs must **never** replace IDs. A user-facing rename must not break existing progress or bookmarks.
- Preserve original image bytes and their SHA-256, MIME and dimensions. Never silently transcode, move or overwrite pages or covers.
- Distinguish publication tags/status from personal reading tags/status. Never mutate personal progress, collections, ratings, notes or bookmarks through metadata updates.
- Existing non-empty or manually corrected metadata is protected. New source metadata only fills missing values unless separately reviewed; ambiguous title/edition matches are conflicts.
- Do not expose bearer tokens, HF signed media links or private source files to the browser or GitHub.
- **Never delete the entire dataset.** "Delete one manga" in the menu is a **reversible catalogue de-list**; page images, manifests and covers remain unchanged. A real purge is not part of ordinary work.
- A catalogue JSON backup is **not** an independent full-media backup. A pinned HF branch is also not an independent full-media backup.

## Mandatory private-write requirements

**Only perform a live write when expressly authorised for that exact operation.**
Require all of the following: private dataset visibility, validated source and rights evidence, exact immutable IDs, accepted canonical schema, input byte/hash integrity, nonempty manual metadata preservation, current read-only inventory, conflict-free detailed preview, **explicit approval of that preview**, expected-parent revision checks, original pre-change catalogue backup and post-write read-back verification.

For potential loss of original media require **independently verified off-platform full-media backup** and an isolated recovery rehearsal. A past ReLIFE/five-title permission or approved run **does not authorise unrelated future uploads or deletion**.

Keep the catalogue publication **last** after complete validated media. Use checkpoint comparisons for resumable batches. Reject uncheckpointed collisions and stale plans. Never hide errors, weaken guards, fabricate source hashes or approve your own write based only on a zero-conflict parser result.

## Security, privacy and rights

- Treat ZIP/CBZ/image files and source metadata as hostile until validated. Enforce path traversal, symlink, duplicate name, decompression ratio, file count/size, pixel budget, MIME, decoded integrity and checksum limits.
- Keep original files and private reports under gitignored local paths. Do not commit real manga pages or real covers as tests; use synthetic images.
- Permission to store privately is not proof of permission to redistribute. Record attribution and supplied rights evidence; do not expose unrestricted artwork URLs.
- Do not make a private dataset public, create a new dataset as a workaround, or use an unscoped environment token.
- Ordinary CI is synthetic and token-free. Historic protected GitHub Actions workflows may read/write private HF under explicit owner-approved gates; treat them as **special-case operations**, not a general CI exception.

## Implementation and testing expectations

- Python 3.11 and 3.12, Windows and Linux. Windows PowerShell/Command Prompt menu must continue to work.
- Make changes to correct modules, not parallel duplicate implementations. Relevant mapping is in [AI Agent Playbook](docs/AI_AGENT_PLAYBOOK.md).
- Add regression tests for new behaviours and negative tests for unsafe inputs, stale revisions, manual metadata conflicts, partial uploads and restore failures.
- Run:
  
      python -m unittest discover -s tests -v
      python -m ruff format --check .
      python -m ruff check .
      python -m mypy src/taiyou_manga
      python -m pip_audit

- Check the **actual four CI jobs** (Windows/Linux x Python 3.11/3.12) for the exact PR SHA. Queued, skipped or unrelated old passing jobs are not evidence.
- Do not edit master directly when a scoped PR is possible. Do not leave temporary workflows or output artefacts.
- For schema changes, compare the **current Manga Library validators** and coordinate a single optional-field contract. Never independently invent cover/page fields.
- For public repository documentation, avoid printing real private manga titles from the owner's current catalogue unless already public and necessary; never publish private source URLs/tokens or checksum manifests associated with copyrighted artwork.

## Current state and dated caveats

On 20 November 2026 the private canonical dataset's **read-only** verification observed **5 manga, 587 chapters, 14,635 pages, five covers and complete publication metadata**, revision 0942616f03e165c7f9e4258110c9fdb4b085f1fc. Check current data; these figures are **not** permanent invariants. See [the read-only live check](https://github.com/AdityaSreevatsaK/Taiyou-Manga-Storage-Controller/actions/runs/44721448011).

ReLIFE and four other selected titles were migrated/uploaded; five-title cover/metadata backfill completed. The general-purpose Novel-style menu and API were merged in PR #28. General bulk uploads, cover ZIP imports and reversible de-listing have **synthetic CI coverage**, not comprehensive production write tests. Do not describe them as end-to-end production-proven without new evidence.

**Historic root ReLIFE artefacts are recovery sources only.** Old documents still referencing paused migrations, ReLIFE-only writes or unimplemented HF tools are historical; update them carefully rather than reintroducing obsolete restrictions.

## Required end-of-task report

Report: repository and exact branch/PR, files changed, tests and CI conclusions, whether **any** private dataset files changed, revisions and backup if applicable, known limitations, and specific next safe action. If blocked, state precisely what is missing. Do not promise work will continue autonomously unless a scheduled automation has actually been created.
