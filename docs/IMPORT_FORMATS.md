# Import formats and limits

Implemented: direct chapter folders, nested candidate folder hierarchies, ordinary ZIP and CBZ archives; PNG/JPEG/WebP/AVIF pages. AVIF decoding depends on Pillow build support. Example candidate layout: `Source/Series/Volume 1/Chapter 1/001.png`; archives can replace chapter folders. Filenames receive natural numeric ordering, e.g. 1, 2, 10. Repeated/missing terminal page numbers are reported as warnings; duplicate decoded file content *within a chapter* is rejected.

Defaults: 25 MB per page, 16,000 pixels per side, 70 million pixels total, 1,000 pages per chapter/archive, 500 MB per chapter folder or archive (compressed and uncompressed), compression ratio <= 100, 5,000 MB total import, and 10,000 chapters per import, at most 12 directory levels and 100,000 total filesystem entries per scanned source tree. The walker counts encountered entries before sorting each folder and stops once a limit is reached. The CLI supports `--max-total-mb` (1-5000) and `--max-chapters` (1-10000) for both `scan` and `manifest`, plus `--max-source-depth` (1-12) and `--max-source-entries` (1-100000). The `Limits` Python model also supports tighter bounds in tests. A folder or ZIP/CBZ chapter is buffered one at a time; chapter metadata and hashes are retained but image bytes are not accumulated for all chapters. Ordinary safe ZIP directory entries are accepted. Standard CBZ archives may also contain one root-level `ComicInfo.xml` (maximum 256 kB); the metadata is CRC-checked and ignored, not parsed as rights evidence or written to candidate bundles. ZIP members cannot be traversals, encoded paths, symlinks, directories masquerading as pages, encrypted or invalid image types. Folder symlinks are rejected. Files are decoded and checked against their declared extension, not accepted based on suffix alone. No silent repair or OCR/transcoding is performed.

**Not implemented:** RAR/7z/CBR, PDF, manga downloads, DRM bypass, arbitrary external URLs, dynamic import recipes, ZIP nesting or a one-click remote import. Exact source packaging remains an owner decision.


## Flat numbered chapter_page image import

**New supported local source:** One manga whose source folder contains only
image files named \`<chapter>_<page>.<ext>\`, e.g. 1_0.jpg, 1_1.jpg, 1_10.jpg,
2_0.jpg. Both chapter and page components are parsed as integers, **not sorted
as raw text**. Page numbers in each chapter must start at 0 or 1 and be
contiguous. Chapter-number gaps appear in the preview as a warning; no empty
pages are invented. Numeric spelling collisions, such as 1_0.jpg and
01_0.jpg, are rejected. The source folder is never renamed or modified.

Examples (Windows PowerShell, running from a controller checkout):

    python -m taiyou_manga flat-preview --source "C:\Manga\My Story" --series-title "My Story"
    python -m taiyou_manga flat-build --source "C:\Manga\My Story" --series-title "My Story" --manga-key "my-story" --rights-json "private\rights.json" --output "bundles\my-story"
    python -m taiyou_manga verify --bundle "bundles\my-story"
    python -m taiyou_manga.hf_cli bulk-upload --source "bundles\my-story" --plan-file "reports\my-story-upload.json"
    # Explicit separate approval to perform a private HF write:
    python -m taiyou_manga.hf_cli bulk-upload --source "bundles\my-story" --plan-file "reports\my-story-upload.json" --apply --approve

Alternatively, use **Windows management menu option 21** for guided
preview/build/cloud-plan/explicit approval. The bundle builder requires
a verified source rights JSON using the existing v1 SourceRights fields:
schemaVersion, sourceType (original/owned/licensed), title,
permissionEvidence, attribution and UTC recordedAt. Do not fabricate rights
evidence to satisfy a check.

The \`--manga-key\` is an optional owner-defined stable import identity and
**not a public slug or remote manga ID**. Reuse the same key and backed-up
.manga-controller/ids.json on retries, even if the local source folder moves.
With no explicit key, the absolute folder path is used, making a future move
subject to explicit identity migration. Default reading direction is rtl,
configurable with \`--direction rtl|ltr|vertical\`.

Conversion outputs an ordinary local verified bundle: catalogue.json,
inventory.json, rights.json, manifests/<chapterId>.json, and original page
images under assets/manga/<mangaId>/<chapterId>/<pageId>.<ext>. The existing
append-only HF uploader publishes data/library.json,
data/manifests/<chapterId>.json and data/manga/... after validation.
No new reader JSON schema is introduced. The original filename page 0 is
the **first** page of the manifest and normally UI page 1.

**Limitation:** Uploading a new complete manga is supported. The existing
bulk uploader refuses altered chapters of an already uploaded manga. New
chapters for an existing remote title require a separate safe append workflow.
The flat importer does not generate author, synopsis, tags or cover artwork;
those use the existing Controller metadata and cover import path.

[Copyable Manga Library integration note](LIBRARY_FLAT_CHAPTER_IMPORT_CONTRACT.md)
