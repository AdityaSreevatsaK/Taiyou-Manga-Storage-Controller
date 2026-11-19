# Session handover: Taiyou Manga Storage Controller

Act as the **Principal Python Engineer, Storage Architect, Hugging Face Integration Engineer, Data Integrity Engineer and Security Auditor**.

## Repository and ownership

- Canonical repository: https://github.com/AdityaSreevatsaK/Taiyou-Manga-Storage-Controller
- Canonical branch: `master`; work on focused branches and merge only after verified CI.
- Related **read-only references**: `AdityaSreevatsaK/Taiyous-Manga-Library` and `AdityaSreevatsaK/Taiyou-Novels-Storage-Controller`. Do not modify them without explicit permission.
- Repository is public. Media, rights evidence, CSV exports, candidate manifests, original backups, identity registries and credentials must remain **private**. The controller does not download or scrape manga.

## Verified status as of 19 November 2026

**First offline milestone completed.** Python 3.11/3.12, Windows/Linux GitHub Actions, synthetic image generator, interactive Windows menu and non-interactive CLI are implemented. Source discovery accepts folders and ZIP/CBZ candidate archives. Pillow validates decoded PNG/JPEG/WebP and supported AVIF; archives are checked for traversal, symlinks, oversized or suspicious entries. Natural page order, stable series/chapter IDs, content-derived page IDs, SHA-256, versioned candidate manifests, catalogue inventory and rights declarations are implemented.

- Local mock upload preview requires explicit approval and an expected revision to apply, and **never** contacts Hugging Face.
- Verified full-media ZIP backups, preview-only restoration and new-destination restoration exist. A catalogue export is **not** a complete media backup.
- `hf-health` is optional and strictly read-only; HF dataset creation, upload, mutation and deletion are disabled.
- JSON inventory and private, Excel-safe chapter-level CSV exports are available.
- Import discovery and bundle generation process chapters incrementally, and enforce 500 MB folder/archive chapter bounds plus 5,000 MB/10,000-chapter default total limits. `scan` and `manifest` accept `--max-total-mb` and `--max-chapters` within these ceilings. Standard safe CBZ directory entries are accepted.
- Rights are *declared*, not legally adjudicated; no real source media has been imported.

Merged improvements, all validated via GitHub Actions:

1. [PR #2](https://github.com/AdityaSreevatsaK/Taiyou-Manga-Storage-Controller/pull/2): complete mock snapshot integrity, catalogue/order/rights drift detection, malformed/orphan bundle rejection.
2. [PR #3](https://github.com/AdityaSreevatsaK/Taiyou-Manga-Storage-Controller/pull/3): private CSV inventory export, safe-new-file operation, spreadsheet injection protection.
3. [PR #4](https://github.com/AdityaSreevatsaK/Taiyou-Manga-Storage-Controller/pull/4): exclusive cross-process identity registry lock, secure atomic registry writes and fault-injection tests.
4. [PR #6](https://github.com/AdityaSreevatsaK/Taiyou-Manga-Storage-Controller/pull/6): bounded chapter-by-chapter imports, aggregate quotas, safer standard CBZ directory handling and regression tests.
5. [PR #7](https://github.com/AdityaSreevatsaK/Taiyou-Manga-Storage-Controller/pull/7): reject duplicate/invalid immutable-ID registry contents and independently verify full staged bundles before publication.

At PR #7, **52 synthetic tests passed**, with lint, formatting, mypy and dependency audit passing on all four CI jobs (Windows/Linux, Python 3.11/3.12). Verify current CI rather than assuming future runs remain green.

## Windows reproduction

```powershell
git clone https://github.com/AdityaSreevatsaK/Taiyou-Manga-Storage-Controller.git
cd Taiyou-Manga-Storage-Controller
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m taiyou_manga fixtures --output demo_manga
python -m taiyou_manga manifest --source demo_manga --output bundles/demo-1 --rights-json demo_manga-rights-example.json --max-total-mb 5000 --max-chapters 10000
python -m taiyou_manga inventory --bundle bundles/demo-1
python -m taiyou_manga export-csv --bundle bundles/demo-1 --output reports/demo-1.csv
python -m taiyou_manga verify --bundle bundles/demo-1
python -m taiyou_manga plan-upload --bundle bundles/demo-1 --mock-dir mock_remote
python -m taiyou_manga backup --bundle bundles/demo-1 --output backups/demo-1.zip
python -m taiyou_manga check-backup --backup backups/demo-1.zip
python -m unittest discover -s tests -v
```

Run `python -m taiyou_manga menu` or `00_manga_storage_menu.cmd` for the interactive menu. `mock-upload` needs `--approve` and an exact `--expected-revision`. `restore` defaults to preview and only writes to a new location after `--approve`.

## Technical boundaries

- The Manga Library's `src/domain/types.ts`, `src/domain/validation.ts`, `docs/DATA_CONTRACTS.md` and **proposed** ADR-006 are the compatibility reference. The controller's candidate bundle is **not** an approved persisted Hugging Face schema.
- Identity registry `.manga-controller/ids.json` must be backed up and kept private; unexpected key types, case-colliding keys and duplicate IDs are rejected before the build. The fully staged bundle is verified before identities are persisted or the output becomes visible. Moving or renaming source paths needs a deliberate identity-remapping plan; otherwise IDs can change. If a crashed import leaves `ids.json.lock`, inspect it before manual recovery.
- Mock content-addressed revisions now include catalogue, manifests, inventory and rights evidence as well as pages. Old disposable mock snapshots use a different hash scheme and are not silently migrated; start a fresh disposable mock after separately retaining any needed local data.
- Media never shares the Novels dataset. Personal reading progress, ratings, tags and annotations remain separate from media.
- Use only lawfully held or licensed images; never add public copyrighted test images or unapproved provider scraping.

## Next independent development

Prioritise: (1) configurable source mapping without assuming supplied folders or archive naming, (2) safe source-path identity reconciliation/migration with preview and rollback, (3) more granular image/resource ceilings and deep-tree traversal limits, (4) image decoding isolation and AVIF portability tests, (5) deeper backup and interrupted-operation fault injection, and (6) read-only HF manifest/inventory/download adapter tests with no remote writes. Keep each in a focused PR with Windows/Linux CI.

**Owner approvals still required before remote writes:** actual manga image structure, rights provenance and permitted content, exact private HF dataset and whether it should be created, storage layout/reader adapter, quotas and retention, private owner authorisation, revision-guarded commit protocol, rollback/backups and cloud security. Do not choose these implicitly.

Inspect the latest `master`, open PRs, workflows and docs before proceeding. Do actual implementation and tests wherever independent of these approvals. Never enable bulk dataset reset or live HF writes without an explicit new review gate.
