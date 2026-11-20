# Manga Storage Controller: Novel Controller workflow parity

Reference: Taiyou-Novels-Storage-Controller `00_storage_menu.cmd`, its
`docs/USER_GUIDE.md` and Python implementation. Manga uses a different
data model: images, chapter manifests and verified cover bytes, not EPUB
or novel original.zip conventions.

## Windows startup

Install Python 3.11 or 3.12. From the Manga Controller folder run:

    py -3 -m pip install -e ".[huggingface]"
    rem Set a scoped HF_TOKEN privately in the current shell; do not persist or paste it
    00_manga_storage_menu.cmd

In PowerShell, set the token for the current terminal with
`$env:HF_TOKEN`. Do not save it in the repository, screenshots or
GitHub workflows. The default Windows entry now shows the Novel-style 20-option
private Manga Controller. Existing synthetic/offline commands remain under
option 20 (or `py -3 -m taiyou_manga offline-menu`).

**Live Hugging Face writes do not run on opening the menu.** Preview first;
every write uses an explicit approval or exact-title confirmation.

## Feature comparison

| Novel option | Manga implementation | Notes |
|---|---|---|
| 1 Smart bulk upload | Bulk upload verified single-manga bundles | Validates immutable IDs, source permissions and all image SHA-256s; 125-file batches; revision checks; local plan and private catalogue backups; never overwrites existing manga |
| 2 Download all | ZIP archive per manga with original image bytes, manifests, covers and catalogue | Pinned to one private dataset revision; skip existing ZIP, no transcoding |
| 3 List novels | List all manga to private CSV | Shows manga IDs, chapters, pages, authors, covers and publication status |
| 4 Detect conflicts | Normalised title and alternative-name checks | Cross-ID duplicate detection |
| 5 Verify integrity | Quick, manifest or full image decoding+SHA-256 | Deep is slow and transfers media; quick checks folder/manifests, not image bytes |
| 6 Sync status | Compare local verified bundles with remote catalogue | Content identity not established by structural comparison alone |
| 7 Backup catalogue | Exact byte-for-byte copy of private `data/library.json` | **Catalogue backup is not a full-media backup** |
| 8 Restore novel | Restore a reversibly de-listed manga | Requires saved private `control/delist-backups/<revision>/library.json` and original media present; dry-run + approval |
| 9 Delete novel | Reversible de-list of one manga | Original images, chapters, covers, manifests and personal data remain intact; no permanent deletion |
| 10 Upload covers | Direct ZIP or candidate-based private metadata/cover uploader | Accepts a bounded ZIP with metadata.json and covers/, retaining original formats, source provenance, rights and snapshot backup |
| 11 CLEAR private HF data | **Deliberately disabled** | Entire-dataset wipe was unsafe in past; never recreated here |
| 12 Chapter inventory | All chapters in private CSV | Includes immutable chapter IDs and page counts |
| 13 Audit covers | Catalogue completeness CSV | Identifies missing cover references; use manifest/deep integrity to verify remote presence/bytes |
| 14 Compare Retriever inventory | CSV of exact ID matches, missing records and title-only manual reviews | Accepts local JSON list or `{"entries":[...]}` format |
| 15 Health dashboard | Local HTML (or JSON/CSV) | Escapes private manga titles and displays missing publication fields |
| 16 Backfill inspection manifests | **Read-only audit, no automated modification** | Existing canonical `data/manifests/` must be verified; rebuilding hashes without originals is unsafe |
| 17 Clean inspection downloads | Preview/clean old local `.part` files only | No original ZIPs or remote files deleted |
| 18 Metadata repair | Private metadata report and guarded reconciliation | Existing `hf_metadata` preview/apply supports original covers and provenance |

The Novel Controller itself labels some single-novel restore/delete launchers
as placeholders; Manga implements **reversible** versions instead of copying
unsafe destructive behaviour.

## Direct commands

    py -3 -m taiyou_manga.hf_cli list --output reports/all-manga.csv
    py -3 -m taiyou_manga.hf_cli conflicts --output reports/conflicts.csv
    py -3 -m taiyou_manga.hf_cli verify --mode manifest --output reports/integrity.json
    py -3 -m taiyou_manga.hf_cli verify --mode deep --output reports/deep.json
    py -3 -m taiyou_manga.hf_cli health --output reports/health.html
    py -3 -m taiyou_manga.hf_cli backup-catalogue --output backups/library.json
    py -3 -m taiyou_manga.hf_cli download --destination downloads
    py -3 -m taiyou_manga.hf_cli chapters --output reports/chapters.csv
    py -3 -m taiyou_manga.hf_cli metadata-report --output reports/metadata.json

## Bulk upload, without per-title custom workflows

The input is one candidate manga bundle produced by the existing `manifest`
command or a directory of such individually verified bundles. Each bundle
must contain catalogue.json, inventory.json, manifests/, assets/manga/,
and a valid rights.json matching its source manga. Keep the private
`.manga-controller/ids.json` registry backed up for stable identities.

Example manga source layout (chapters may be CBZs or page folders):

    incoming/
      Example Manga/
        Chapter 1.cbz
        Chapter 2.cbz
      Another Manga/
        Chapter 1/
          001.jpg
          002.jpg

Build one verified single-manga bundle per title using the existing
`python -m taiyou_manga manifest --source PATH --output BUNDLE --rights-json RIGHTS`
workflow. Chapter paths inferred by the builder must be checked in the
preview; labels are not stable IDs.

Bulk upload:

    py -3 -m taiyou_manga.hf_cli bulk-upload --source bundles --plan-file reports/new-plan.json
    # Review every status/ID and any conflicts in new-plan.json.
    py -3 -m taiyou_manga.hf_cli bulk-upload --source bundles --plan-file reports/new-plan.json --apply --approve

Upload is **append-only**. Existing manga with matching immutable IDs and
identical chapter structure are skipped without replacing source genres or
manually corrected metadata. Conflicting titles, unknown rights, partial
uncheckpointed media, missing pages or different chapter IDs block the run.
For network interruptions, rerun the preview before restarting the apply.
Partial media batches retain exact checksum checkpoints. The final publication
of each title follows verified upload of its chapter manifests and page bytes,
and backs up the old catalogue in the private dataset.

## Upload covers directly from a ZIP

A cover ZIP contains one metadata.json (or candidates.json) using the
existing canonical publication metadata candidate format, plus original
cover image files under covers/. No extra schema is introduced. All files
are private and locally extracted only into a disposable directory; unsafe
paths, symlinks, duplicate names, excessive compression and oversized images
are refused.

    py -3 -m taiyou_manga.hf_cli upload-covers --zip private-covers.zip --plan-file reports/cover-plan.json
    # Inspect conflicts, permissions, hashes, affected fields and source IDs.
    py -3 -m taiyou_manga.hf_cli upload-covers --zip private-covers.zip --plan-file reports/cover-plan.json --apply --approve

The existing metadata reconciliation implementation backs up the prior catalogue,
preserves manually corrected fields and only adds original cover bytes to new
private paths. The catalogue and cover image are committed together with
source attribution and permission evidence.

## Delete one manga safely, then restore it

    py -3 -m taiyou_manga.hf_cli delete --manga-id mng_... --plan-file reports/delist-plan.json
    # Review the exact ID/title and whether this title should leave the catalogue.
    py -3 -m taiyou_manga.hf_cli delete --manga-id mng_... --plan-file reports/delist-plan.json --apply --approve --confirm-title "Exact Manga Title"

This removes only the catalogue record, preserving the immutable original
pages, chapter manifests and cover for later restoration. The previous
`data/library.json` is saved under `control/delist-backups/<source-revision>/library.json`.
No entire dataset delete command or permanent purge exists.

To restore:

    py -3 -m taiyou_manga.hf_cli restore --manga-id mng_... --source-revision <pre-delist-revision> --plan-file reports/restore-plan.json
    py -3 -m taiyou_manga.hf_cli restore --manga-id mng_... --source-revision <pre-delist-revision> --plan-file reports/restore-plan.json --apply --approve

The restore checks all original manifests, page paths and any original cover.
No page is reuploaded and no personal reading data is changed.

## Privacy and limitations

- All exports belong in ignored local backups/, downloads/ or reports/.
- A downloaded ZIP contains original pages, not reconstructed CBZ editions;
  image bytes and immutable names are retained.
- Re-downloading a title with an existing ZIP skips it. Inspect/retain local
  archives carefully; the tool never overwrites them.
- Deep integrity can take significant time and bandwidth for thousands of pages.
- Automatic metadata scraping and automatic manga downloads still belong in the
  Manga Retriever, not this Controller.
- Original pages and private images must never be committed to this public code repository.
- Owner-authenticated private dataset and revision preconditions are mandatory.
- The developer tests are fully synthetic; they do not require private HF tokens.


## Option 21: Flat numbered manga images

The Windows menu now also includes **21. Import flat chapter_page JPG/PNG manga**.
It previews files named `1_0.jpg`, `1_1.jpg`, `2_0.jpg`, etc., builds
the existing original-byte verified manga bundle, and optionally prepares
the guarded private HF upload with explicit approval. For commands and
constraints, see [Import formats](IMPORT_FORMATS.md#flat-numbered-chapter_page-image-import).
For the reader-side specification, see
[Manga Library integration note](LIBRARY_FLAT_CHAPTER_IMPORT_CONTRACT.md).
