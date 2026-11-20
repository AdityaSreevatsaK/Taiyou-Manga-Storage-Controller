# Manga Library Integration Note: Flat Numbered Image Imports

**Date:** 20 November 2026  
**Controller repository:** https://github.com/AdityaSreevatsaK/Taiyou-Manga-Storage-Controller  
**Library repository:** https://github.com/AdityaSreevatsaK/Taiyous-Manga-Library  
**Scope:** This note is for the **Manga Library agent**. The Controller converts the owner's images into the **existing canonical v1 manga format**; it does not add a parallel schema.

## 1. Owner's source filename convention

One local folder contains **one entire manga**. Image filenames follow:

    <chapter_number>_<page_number>.<original_image_extension>

Examples:

    1_0.jpg
    1_1.jpg
    1_2.jpg
    ...
    1_10.jpg
    2_0.jpg
    2_1.jpg

The first numeric component is the chapter number; the second is the **page number within that chapter**. The parser does numeric sorting, so page 10 appears **after page 9**, not after page 1. Both zero-based and one-based page numbering are accepted **within a chapter**, provided numbers are contiguous. Each manga may begin its chapter labels at any number; missing chapter numbers are surfaced as a preview warning and never filled with invented pages. Invalid names, repeated chapter/page number pairs, missing page numbers, truncated images and MIME mismatches fail closed.

## 2. Storage contract: identical to the existing Reader contract

**Private HF dataset:** AdityaSreevatsaK/Taiyous-Manga.

A local flat-image source is first validated and converted by the Controller's existing builder to one candidate bundle containing catalogue.json, chapter manifests, original page assets, inventory.json and source rights evidence. That bundle is then uploaded by the **existing** revision-guarded, append-only HF bulk uploader.

The published private dataset remains:

    data/library.json
    data/manifests/<ch_id>.json
    data/manga/<mng_id>/<ch_id>/<pg_id>.jpg

A typical **synthetic example** of the new manga entry in the existing data/library.json:

    {
      "kind": "manga",
      "id": "mng_aaaaaaaaaaaa",
      "title": "Example Manga",
      "aliases": [],
      "creators": [],
      "tags": [],
      "publicationStatus": "unknown",
      "direction": "rtl",
      "chapters": [
        {
          "id": "ch_bbbbbbbbbbbb",
          "label": "Chapter 1",
          "sequence": 0,
          "pageCount": 11
        },
        {
          "id": "ch_dddddddddddd",
          "label": "Chapter 2",
          "sequence": 1,
          "pageCount": 2
        }
      ]
    }

The enclosing catalogue envelope is **unchanged**:

    {"schemaVersion":1,"mediaKind":"manga","entries":[...]}

The chapter sequence field is **zero-based** regardless of the chapter number in the input filename. Chapter labels retain the visible source chapter number (for example "Chapter 12"). A page's original source filename **does not become its remote storage filename**.

Example data/manifests/ch_bbbbbbbbbbbb.json:

    {
      "schemaVersion": 1,
      "mediaKind": "manga",
      "chapterId": "ch_bbbbbbbbbbbb",
      "pages": [
        {
          "id": "pg_cccccccccccc",
          "assetPath": "manga/mng_aaaaaaaaaaaa/ch_bbbbbbbbbbbb/pg_cccccccccccc.jpg",
          "mimeType": "image/jpeg",
          "width": 800,
          "height": 1200,
          "byteSize": 123456,
          "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        }
      ]
    }

The actual chapter manifest's pages array contains **all** page entries in numeric page order. All displayed IDs, sizes and hashes above are illustrative, not real data.

The physical remote asset path is **data/** plus each page.assetPath, and must be fetched by the Library's existing authenticated media gateway. Do not expose Hugging Face tokens or unrestricted media URLs.

## 3. Required Manga Library behaviour

1. **No new filename parser in the Library.** The Controller fully resolves 1_0.jpg etc. The Library receives only the same IDs, catalogue envelope, ordered chapter list and page manifests as existing manga.
2. **Catalogue refresh:** When a new private dataset revision is published, invalidate/revalidate the Library's cached catalogue and display the newly added manga/chapter entries.
3. **Ordering:** Render chapter navigation by each chapter's sequence, and pages by **array position in that chapter's manifest**. Do not lexicographically sort opaque page IDs, assume filenames 1_0/1_1 survive, or derive a chapter number from its immutable ID.
4. **User-facing page number:** The file named 1_0.jpg becomes the **first manifest page**. Display as **page 1** in the UI if the reader uses 1-based page counters and URLs (for example ?page=1). The original numeric suffix is not the user-visible page counter.
5. **Private images:** Continue to use the existing owner-authorised private image proxy/gateway and its caching/error handling. The Controller does not enable public artwork access.
6. **Routes and bookmarks:** Continue to resolve opaque IDs internally. Readable routes like /manga/<slug>/chapters/<chapter-slug>?page=1, if supported by the Library, are a UI routing concern. Preserve legacy opaque-ID links and existing progress references during navigation changes.
7. **Metadata:** Flat JPG image imports do not inherently include publication cover, synopsis, tags, author or artist. Use the current safe fallback if absent; those fields can be added later via the existing Controller metadata/cover reconciliation process, using the same optional cover/creatorRoles/metadataSources contract.
8. **Progress/offline preservation:** Refreshing the catalogue or introducing new chapters must not erase existing reading progress, offline copies, collections, ratings or personal tags. The Controller stores only publication data.
9. **Reader tests:** Add or confirm regression coverage for manga with pages starting at source number 0, 1_10 numerical ordering, chapters 1/2/10 ordering, new catalogue revision refresh, missing/failed private page fetch, and navigation across chapter boundaries on mobile.

**Compatibility assessment:** The data produced by this helper uses the same schema as the current five uploaded manga. There is **no mandatory new Library schema field**. App changes are only required where its current catalogue refresh, chapter navigation, reader URL handling, or private image caching do not already meet the behaviour above.

## 4. Controller import flow and safety

The Controller adds:

    python -m taiyou_manga flat-preview --source "C:\Manga\Example" --series-title "Example Manga"

The preview reports chapter count, page count, chapter numbers and gaps; **no HF write**.

    python -m taiyou_manga flat-build --source "C:\Manga\Example" --series-title "Example Manga" --manga-key "example-manga-owner-key" --rights-json "private\rights.json" --output "bundles\example"

This creates the verified original-byte candidate bundle in local private storage using the same builder/manifest validators as other imports. The --manga-key is an optional operator-supplied stable key, distinct from the title and remote immutable ID; it keeps existing registry identities stable even when moving the local source folder, provided the same private registry is retained.

Next:

    python -m taiyou_manga.hf_cli bulk-upload --source "bundles\example" --plan-file "reports\example-plan.json"

The plan checks the current private dataset SHA, duplicate manga titles and aliases, existing identities, all original images, source permission evidence and append-only constraints. **The upload is a separate approved action**:

    python -m taiyou_manga.hf_cli bulk-upload --source "bundles\example" --plan-file "reports\example-plan.json" --apply --approve

The Windows menu additionally exposes a guided "flat chapter_page images" helper that performs preview, local build and optional protected remote upload. Actual remote mutation requires a private HF_TOKEN and explicit operator confirmation.

**Current safety limitation:** The existing general bulk uploader is **new-series append-only**. If the remote catalogue already contains the same manga ID with a different chapter list, it **refuses** the update rather than inserting chapters or replacing pages. Thus the helper is intended for adding a **new complete manga** from a flat folder, not silently modifying an existing uploaded manga. Incremental chapter addition to an existing series would need a separately designed, revision-safe workflow and no ID churn.

## 5. What the Manga Library agent should check

- Does the currently deployed app load and refresh data/library.json from the authenticated backend?
- Does it use manifest order and sequence instead of filename sorting?
- Does it correctly number the first page as 1 when the original flat source used 0?
- Do lazy/private image requests and offline caching survive chapter changes?
- Can it render chapters without creators/cover/synopsis and later refresh them when added?
- Are URLs, bookmarks, progress and manual metadata preserved on catalogue updates?

No Manga Library code is modified by this Controller task. Implement only any **actual gaps** found by inspecting the current Library source and live deployment.

**Do not interpret this note as confirmation that a particular user manga was uploaded.** The note defines the conversion and shared read contract. Verify actual private HF revision and uploaded page counts after each approved upload.
