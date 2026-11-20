# Taiyou Manga Storage Controller: Repository Handbook

**Last reconciled:** 20 November 2026. **Canonical branch:** master.
**Scope:** This is the operating and engineering handbook for the **Manga Storage Controller**. Read [../AGENTS.md](../AGENTS.md) before using an AI coding agent, and [AI_AGENT_PLAYBOOK.md](AI_AGENT_PLAYBOOK.md) for the full agent procedure.

## 1. What this repository is for

Taiyou Manga Storage Controller is the owner's Python-based, Windows-friendly **control plane for a private manga dataset**. It is not a reader, not a public manga hosting service and not a manga scraper.

Its purpose is to take owner-supplied, appropriately authorised manga page images and metadata, validate them, keep stable identities, store and inspect them in **one canonical, private Hugging Face dataset**, and preserve recoverability. It also provides the operational tools needed for maintaining a manga collection as it grows: inventory, title conflicts, integrity reports, local/cloud comparison, bulk uploads, bulk downloads, chapter exports, private cover import, publication metadata updates, catalogue backups, and reversible removal and restoration.

The repository's **source code is public**. The manga assets, identity registry, download bundles, private metadata proposals, credentials, original covers, rights evidence, backups and generated reports are **not** public. Never upload them as GitHub source files or public Actions artefacts.

The Controller deliberately separates:
- **Media identity and publication data:** manga, chapter and page IDs, metadata, covers and original image bytes.
- **Personal reading data:** bookmarks, progress, collections, personal tags, notes, ratings and reading state. Those are owned by the Manga Library or its separate persistence model, not by these Controller catalogue operations.
- **Source acquisition:** the Manga Retriever obtains authorised source files and proposes metadata. The Controller validates, reconciles and stores them. It does **not** scrape chapters.
- **Reader UX and delivery:** Taiyous-Manga-Library handles the browser interface, private media authorisation and reader URLs. The Controller does not implement that UI.

## 2. Related repositories and boundaries

| Component | Repository / location | Owner of responsibility |
|---|---|---|
| Manga Controller (this repo) | https://github.com/AdityaSreevatsaK/Taiyou-Manga-Storage-Controller | Validation, canonical data, storage, uploads/downloads, backups and operations |
| Manga Library | https://github.com/AdityaSreevatsaK/Taiyous-Manga-Library | Reader, UI, navigation, private page/cover delivery, bookmarks and progress |
| Manga Retriever | https://github.com/RichardDaffern/Manga-Retriever | Source discovery, downloads, provider evidence, source cover and publication metadata candidates |
| Novel Storage Controller | https://github.com/AdityaSreevatsaK/Taiyou-Novels-Storage-Controller | UX/operational reference only; its EPUB schema does not apply to manga |
| Private Hugging Face dataset | AdityaSreevatsaK/Taiyous-Manga | Original manga images, chapter manifests, canonical catalogue and private audit/control records |

Do not change another repository as part of a Controller task unless separately authorised. Reference its **current code**, not screenshots or descriptions of a past revision. Changes to shared schema require explicit cross-repository compatibility review.

## 3. Current verified production state (historical snapshot)

As verified via a **read-only private dataset smoke check** on 20 November 2026 (GitHub Actions run 44721448011), the canonical dataset contained:

| Metric | Verified value |
|---|---|
| Manga | 5 |
| Chapters | 587 |
| Pages | 14,635 |
| Real covers and complete publication metadata | 5 titles |
| Sample chapter manifests read | 5 |
| Remote mutations by that check | 0 |
| Dataset revision at that check | 0942616f03e165c7f9e4258110c9fdb4b085f1fc |

The five titles are **ReLIFE**, **Kaichou wa Maid-sama!**, **Last Game**, **Love So Life**, and **Onizuka-chan and Sawarida-kun**. These are a dated reference, **not a current live-state assertion**. Whenever working in a new session, fetch the latest private revision and inspect the catalogue again. Do not require exactly five titles forever; the smoke workflow used five as its then-current invariant and will need updating as the catalogue grows.

Historical milestones:
1. ReLIFE entered the dataset using an incompatible legacy root layout.
2. ReLIFE was migrated to the canonical data/ layout while preserving old media and identities.
3. The other four titles were uploaded through protected incremental workflows.
4. All five were enriched with original source-cover bytes, creator roles, synopsis, aliases, tags, publication status and source provenance.
5. Novel Controller-style manga management tools were merged in Controller PR #28 (with follow-up documentation PR #29 and protected read-only smoke PR #30). All four CI jobs succeeded after merge.

Useful evidence: [Controller PR #28](https://github.com/AdityaSreevatsaK/Taiyou-Manga-Storage-Controller/pull/28), [CI run 44721448283](https://github.com/AdityaSreevatsaK/Taiyou-Manga-Storage-Controller/actions/runs/44721448283), [read-only dataset smoke](https://github.com/AdityaSreevatsaK/Taiyou-Manga-Storage-Controller/actions/runs/44721448011).

**Rights caveat:** The owner's request to preserve private covers and pages does not establish an independently verified licence to redistribute those files. Never expose original media or tokens on a public endpoint.

## 4. Architecture and data flow

    Owner-supplied manga folders / ZIPs / CBZs    Manga Retriever metadata candidates
                      |                                        |
                      v                                        v
                  sources.py                          metadata.py / hf_cover_zip.py
                 (safe discovery)                    (provenance, match, decode)
                      |                                        |
                      v                                        |
                  images.py                                   |
          (MIME, full decode, limits, SHA-256)                 |
                      |                                        |
                      v                                        v
                  builder.py                      hf_metadata.py
           (immutable ID registry,               (revision-pinned preview
            catalogue + chapter manifests)        and guarded field updates)
                      |                                        |
                      v                                        |
          Private verified local bundle                       |
          (catalogue, manifests, assets)                      |
                      |                                        |
                verify_bundle                                 |
                      |                                        |
                      v                                        |
                    hf_bulk.py ------------------------------- |
           (append-only image/manifests upload,               |
            checkpoints, catalogue publication last)          |
                      |                                        |
                      +-----------------+----------------------+
                                        v
                             Private Hugging Face
                              data/library.json
                           data/manga/... page images
                         data/manifests/... JSON files
                            data/covers/... images
                            control/... audit records
                                        |
                                        v
                            Manga Library's private
                            authenticated media gateway
                              and browser-side reader

There are two complementary command surfaces:
- **Local/offline:** taiyou_manga.cli and the package entry point, responsible for fixtures, archive scanning, candidate bundle generation, mock storage, source ID migration, bundle verification and local full-media backups.
- **Private cloud management:** taiyou_manga.hf_cli, responsible for everyday Hugging Face operations. The default Windows menu opens this surface. The older local menu remains under offline-menu / menu option 20.

### Source directory and package map

| Path | Why it exists |
|---|---|
| 00_manga_storage_menu.cmd | Windows entry point for private controller menu |
| src/taiyou_manga/cli.py | Offline CLI, fixtures, bundle creation, mock operations and menu dispatch |
| src/taiyou_manga/hf_cli.py | Novel-style private cloud CLI and interactive menu |
| src/taiyou_manga/sources.py | Bounded image folders, ZIP/CBZ discovery; natural page order |
| src/taiyou_manga/images.py | Validates image magic/MIME, full decode, dimensions, bytes and checksums |
| src/taiyou_manga/domain.py | ID, page, manifest and asset-path validation |
| src/taiyou_manga/builder.py | Local bundles, private identity registry and verification |
| src/taiyou_manga/hf_layout.py | Canonical catalogue schema validation and read-only migration planning |
| src/taiyou_manga/hf_bulk.py | General append-only, checkpointed manga bundle upload |
| src/taiyou_manga/hf_manage.py | List, conflict report, private downloads, integrity, sync, backup, reversible de-list and restore |
| src/taiyou_manga/hf_extra.py | Chapter inventory, Retriever inventory comparison, local temporary-file cleanup |
| src/taiyou_manga/metadata.py | Publication metadata source candidates, reconciliation and completeness |
| src/taiyou_manga/hf_metadata.py | Private metadata/cover preview, parent-revision commits, backup and verification |
| src/taiyou_manga/hf_cover_zip.py | Safe ZIP wrapper for original cover bytes and existing metadata candidate format |
| src/taiyou_manga/identity_migration.py | Explicit preview and guarded migration of local source-path identity registry |
| src/taiyou_manga/backup.py | Verified local full-media bundle backup, restore preview and new-folder restore |
| src/taiyou_manga/storage.py | Mock storage and read-only Hugging Face adapter |
| src/taiyou_manga/hf_recovery.py, hf_canonical_migrate.py | Historic ReLIFE recovery and canonical data migration |
| src/taiyou_manga/relife_*, selected_* | Historic one-off ReLIFE/four-title source and upload workflows |
| scripts/prepare_five_metadata_handover.py | Historical five-title checksum-pinned source conversion |
| .github/workflows/ci.yml | Offline synthetic checks on Windows/Linux and Python 3.11/3.12 |
| .github/workflows/private-manga-management-smoke.yml | Owner-protected, read-only live data sanity check |
| docs/ | Contracts, decisions, operations, safety, recovery and historical migrations |
| tests/ | Synthetic unit/integration coverage, without private content |

Historic workflows are **not** generic upload recipes and must not be re-run against a changed dataset without renewed review.

## 5. Canonical private Hugging Face data contract

**Dataset:** AdityaSreevatsaK/Taiyous-Manga, private.

    data/
      library.json
      manga/<mng_id>/<ch_id>/<pg_id>.<original-extension>
      manifests/<ch_id>.json
      covers/<mng_id>.<original-extension>
    control/
      metadata-backups/<revision>/library.json
      cover-rights/<mng_id>/<sha256>.json
      bulk-catalogue-backups/<revision>/library.json
      delist-backups/<revision>/library.json
      ...
    ingest/
      bulk-v1/<mng_id>/part-xxxx.json
      bulk-v1/<mng_id>/complete.json
      ... historical ingestion checkpoints

The catalogue is **data/library.json**, not a root catalogue.json or the local builder's catalogue.json. It is a JSON envelope:

    {
      "schemaVersion": 1,
      "mediaKind": "manga",
      "entries": [
        {
          "kind": "manga",
          "id": "mng_aaaaaaaaaaaa",
          "title": "Example title",
          "aliases": [],
          "creators": [],
          "tags": [],
          "publicationStatus": "unknown",
          "direction": "vertical",
          "chapters": [
            {
              "id": "ch_bbbbbbbbbbbb",
              "label": "Chapter 1",
              "sequence": 0,
              "pageCount": 1
            }
          ]
        }
      ]
    }

The example is **illustrative and synthetic**, not actual private data. Optional publication fields include synopsis, creatorRoles, cover, and metadataSources. Publication status values: unknown, ongoing, completed, hiatus. Reading direction values: vertical, rtl, ltr. Cross-series chapter IDs must be unique; chapter sequence values are non-negative and distinct within the series. The reader validates the contract.

Each chapter manifest at data/manifests/ch_....json uses schemaVersion 1, mediaKind manga, chapterId and a pages array. Each page includes id (pg_*), **relative** assetPath (manga/<mng_id>/<ch_id>/<pg_id>.<ext>), mimeType, width, height, byteSize and sha256. Physical image files are prefixed with data/. Page order is the manifest array order; do not assume a new filename sort order.

Optional cover descriptor:
- cover.assetPath: covers/<mng_id>.<ext>, relative to data/;
- cover.mimeType, width, height, byteSize and sha256 must match the original image.
- Allowed originals include PNG, JPEG, WebP and supported AVIF. Do not silently transcode files.
- Never place a direct HF token, signed URL or public image location in catalogue entries.

creatorRoles is an optional list of author/artist {name, role} objects. The existing creators array is retained for older readers. metadataSources associates accepted fields with source provider, sourceId, HTTPS sourceUrl and UTC retrievedAt. Rights/permission evidence lives in **private** sidecar records, not a public UI field.

**Critical distinctions:**
- Immutable IDs are **not display slugs**. Human-readable browser routes belong to Manga Library routing. Renaming titles must not re-key chapter/page IDs.
- Publication status completed is not the user's personally Finished shelf.
- Publication tags are not personal tags.
- Controller local bundle layout (catalogue.json, manifests/, assets/manga/) is **not** the persisted HF dataset layout.
- The old root catalogue.json, root manifests/, assets/manga/ are **legacy recovery copies**, not the live reader's source of truth.

See [DATA_CONTRACTS.md](DATA_CONTRACTS.md) and [METADATA_RECONCILIATION_CONTRACT.md](METADATA_RECONCILIATION_CONTRACT.md) for field-level validation and cross-repo expectations.

## 6. Getting started (Windows)

Prerequisites: Python 3.11 or 3.12, Windows PowerShell or Command Prompt, network access for HF tools, and an owner-approved private Hugging Face token with appropriate limited permissions.

    git clone https://github.com/AdityaSreevatsaK/Taiyou-Manga-Storage-Controller.git
    cd Taiyou-Manga-Storage-Controller
    py -3.11 -m venv .venv
    .venv\Scripts\python.exe -m pip install -e ".[dev,huggingface]"
    .venv\Scripts\python.exe -m taiyou_manga menu

To provide the token in PowerShell for the **current session only**, use the HF_TOKEN environment variable. Never add a literal token to tracked .env files, example commands, code, documentation, logs or issue reports. Avoid shared shell transcripts containing tokens.

Alternative entry: double-click 00_manga_storage_menu.cmd after installation; it invokes the Python menu. For offline demonstrations, use python -m taiyou_manga offline-menu.

Basic checks without any private token:

    python -m unittest discover -s tests -v
    python -m ruff format --check .
    python -m ruff check .
    python -m mypy src/taiyou_manga
    python -m pip_audit

The CI workflow runs these checks on four OS/Python combinations. Dev checks must be green before merging even documentation revisions if repository policy requires all checks.

## 7. Day-to-day command reference

All remote commands below use **python -m taiyou_manga.hf_cli**. Their output files should be under ignored reports/, backups/ or downloads/, and must use **new paths** because the tools refuse to overwrite existing exports.

| Windows menu | Corresponding action | Operational notes |
|---|---|---|
| 1 | bulk-upload | Preview verified one-title-per-bundle candidates; apply only with an approved, unchanged plan |
| 2 | download | Original page bytes, manifests, cover and catalogue packaged into one ZIP per manga; optional --manga-id |
| 3 | list | CSV showing all catalogue manga IDs, titles, creators, chapters and page counts |
| 4 | conflicts | Normalised title and alias collisions across IDs |
| 5 | verify | quick / manifest / deep; quick verifies listings, deep downloads and decodes pages |
| 6 | sync | Compare private local verified bundles to remote catalogue; not a byte-level sync |
| 7 | backup-catalogue | Exact-byte catalogue backup, **not media backup** |
| 8 | restore | Preview/approve re-listing previously de-listed manga, using original backup revision |
| 9 | delete | **Reversible de-list only**; keeps pages, manifests and cover; requires exact title |
| 10 | upload-covers or metadata | Original cover ZIP or local candidate JSON through the same revision-guarded contract |
| 11 | none | Full-dataset wipe intentionally disabled |
| 12 | chapters | Private CSV of manga/chapter IDs, sequence, labels, volumes and counts |
| 13 | covers | Cover metadata completeness report; verify mode separately checks object presence |
| 14 | compare-retriever | Compares local Retriever inventory without automatically matching title-only candidates |
| 15 | health | Private HTML/JSON/CSV report |
| 16 | verify --mode manifest | Read-only missing-manifest and page-path audit |
| 17 | cleanup | Old local *.part files only, with exact confirmation |
| 18 | metadata-report / metadata | Missing metadata report and safe reconciliation |
| 19 | download | All-series archive backup export |
| 20 | offline-menu | Original local synthetic, identity and mock workflow |
| 21 | flat-preview / flat-build + bulk-upload | Import one complete manga from images named chapter_page.jpg, using the existing canonical manifests and protected upload |

Example **read-only** commands:

    python -m taiyou_manga.hf_cli list --output reports/manga-list.csv
    python -m taiyou_manga.hf_cli conflicts --output reports/title-conflicts.csv
    python -m taiyou_manga.hf_cli verify --mode quick --output reports/quick-integrity.json
    python -m taiyou_manga.hf_cli verify --mode manifest --output reports/manifest-integrity.json
    python -m taiyou_manga.hf_cli metadata-report --output reports/metadata.json
    python -m taiyou_manga.hf_cli health --output reports/health.html
    python -m taiyou_manga.hf_cli backup-catalogue --output backups/library.json
    python -m taiyou_manga.hf_cli download --destination downloads

**Deep integrity** downloads and decodes page files and may be expensive in network transfer, time or quota. Do not equate the fast directory-listing check to independent image SHA verification. The above commands read private data and write local files, but do not mutate HF.

### Preview, approvals and writes

Bulk upload (read local bundle(s), plan before upload):

    python -m taiyou_manga.hf_cli bulk-upload --source bundles --plan-file reports/upload-plan.json
    # Read each proposed manga ID, title, status, conflict and checksum.
    python -m taiyou_manga.hf_cli bulk-upload --source bundles --plan-file reports/upload-plan.json --apply --approve

Metadata and covers:

    python -m taiyou_manga.hf_cli metadata --candidates private/metadata.json --plan-file reports/metadata-plan.json
    python -m taiyou_manga.hf_cli upload-covers --zip private/source-covers.zip --plan-file reports/covers-plan.json

Only apply the exact unchanged preview after reviewing source provenance, rights evidence, manual-value conflicts, intended IDs and remote revision. Avoid automatic approval based solely on clean source hashes. Any status of conflict means stop and review. Reversible single-manga de-list:

    python -m taiyou_manga.hf_cli delete --manga-id mng_... --plan-file reports/delist-plan.json
    # Only after explicit owner confirmation:
    python -m taiyou_manga.hf_cli delete --manga-id mng_... --plan-file reports/delist-plan.json --apply --approve --confirm-title "Exact existing title"

A delist is not irreversible deletion. Original binaries remain available for restoration using the saved backup revision and separately reviewed restore plan. Do not implement a real media purge as an implicit follow-up.

## 8. Key engineering and safety invariants

1. **The private dataset must stay private.** Fail closed if unavailable or public.
2. **No secrets or original media in public GitHub.** Use synthetic inputs for code, tests, demos and ordinary CI.
3. **No duplicate or silently reissued IDs.** Preserve mng_*, ch_*, pg_* identities and the local .manga-controller/ids.json registry.
4. **Original bytes remain original.** Verify SHA-256, dimensions, MIME and decoder limits. A catalogue listing is not proof of image integrity.
5. **Never overwrite existing media as an upload shortcut.** New uploads are append-only; batch markers attest source files; catalogue publication comes last.
6. **No cross-title guessing.** Title-only matches, near matches, alternate scripts or mismatched source URLs require manual ID review.
7. **No silent manual metadata loss.** Empty or less reliable proposals cannot displace nonempty, manually corrected fields.
8. **Every remote mutation has a specific approval.** Snapshot the exact SHA, preview, require the operator's explicit approval and expected parent revision, preserve pre-change catalogue bytes, verify the result.
9. **No general full reset.** The menu does not offer permanent deletion. Reversible de-listing is the only normal single-manga removal.
10. **No mixed personal data.** Do not mutate progress, collections, ratings or personal tags.
11. **No unsafe archive extraction.** Reject traversal, absolute paths, symlinks, excessive expanded size, file-count limits, compression bombs and unrecognised media.
12. **No deceptive status statements.** A merged PR is not proof of production upload; a passing synthetic test is not proof of real HF functionality.

The presence of an image on MangaDex does not establish redistribution rights. Retain appropriate attribution/permission evidence privately and do not publicise cover or page URLs.

## 9. Failure, backup and recovery runbook

**Before a mutation:** Obtain the canonical current remote SHA; verify private visibility; confirm the intended series ID and verified source checksum; produce a fresh plan; inspect all conflicts; retain a local independent full-media backup for any operation that could risk original media; record rollback instructions. The Controller's automatic pre-change catalogue backup protects JSON metadata only.

**After a network or process interruption:** Do not blindly restart at a guessed index. Fetch the current revision, read checkpoints/part digests, compare source hashes, regenerate a fresh plan and refuse uncheckpointed remote paths. A stale plan is expected to fail if another commit moved main.

**Missing or corrupted chapter manifest:** First run the manifest integrity check. Do not fabricate pages or IDs from filenames. Compare with retained original source bytes and an independent backup. File presence is not image integrity.

**Lost or moved identity registry:** Do not create a new registry to replace existing IDs. Use the identity-migrate preview procedure and saved registry backup; require explicit reviewed mapping and matching revision.

**Catalogue conflict:** Stop. Compare the existing record and its field-level provenance to the new proposed metadata. Keep existing manual fields. Do not silently change a title or series ID to force upload.

**Cover conflict:** Verify exact original cover checksum, dimensions, source edition, rights evidence and candidate identity. A cover for a different manga or revision is never automatically attached.

**Accidental de-list:** Locate control/delist-backups/<pre-delist-SHA>/library.json and use the restore preview. Verify that every original manifest and page still exists. Do not restore by rewriting whole data trees.

**Full disaster recovery:** A copied library.json and a Hugging Face branch are not substitutes for an independent, verified media backup. A complete recovery requires original images, manifests, registry, catalogue, provenance records, hashes, and an isolated restoration rehearsal. Never delete the dataset to fix a schema problem.

## 10. CI, protected workflows and evidence

Normal CI at .github/workflows/ci.yml is **synthetic and offline**: Ruff format, Ruff lint, mypy, unittest and pip-audit on Linux/Windows and Python 3.11/3.12. It has no paid image APIs or HF write tokens.

The protected read-only private-manga-management-smoke.yml verifies a **dated** live catalogue snapshot and samples one manifest for each of five known titles. It should be updated when inventory changes and must never be used as a generic source of truth without inspecting its hardcoded assumptions.

Other .github/workflows files include historical, narrowly scoped real-data operations for ReLIFE recovery/canonical migration, selected-title uploads, HF private health and the five-title metadata backfill. Some can mutate private data. **Do not rerun or generalise them automatically** merely because they exist. Review job environment, scoped secrets, permissions, exact dataset SHA, operations, stored source artefacts, expiration, and recovery preconditions.

Evidence hierarchy: actual live read-only revision + file/manifests verification > complete successful live upload run and post-commit audit > synthetic CI > PR merge > planned feature documentation. Distinguish each tier in status reports.

## 11. Known limitations and priorities for later improvements

- Generic new-title HF uploads, cover ZIP imports and reversible de-list/restore have synthetic regression coverage and CI, but were **not all exercised with live production mutations** at the time of this handbook. Require isolated private staging tests before describing them as production-proven.
- Quick inspection counts and file paths, not complete image SHA-256s. Deep mode may be resource-intensive. The read-only smoke samples manifests, not every page.
- Local sync is catalogue-structure comparison, not complete byte-for-byte local/remote reconciliation.
- Title matching cannot prove a source edition is correct. Ambiguous sources require human review.
- Automatic source acquisition, OCR, translation, manga reader changes and personal progress synchronisation are outside this repo.
- Historical one-off workflows and some older docs refer to the state **before** the successful canonical migration. The current contract in this handbook takes precedence, but the implementation and live dataset must still be inspected for freshness.
- Future improvements should prioritise safer interrupted-batch recovery, separate independent media backup verification, staged real-HF operation tests, reporting/documentation consistency, zip/import scalability and explicit cross-repo schema tests.

See [AI_AGENT_PLAYBOOK.md](AI_AGENT_PLAYBOOK.md) for the mandatory checklist whenever an AI agent continues this work.

New flat-image chapter imports are covered by [Manga Library integration note](LIBRARY_FLAT_CHAPTER_IMPORT_CONTRACT.md).
