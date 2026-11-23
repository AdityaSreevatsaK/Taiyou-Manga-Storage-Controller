# Private Manga Upload Through GitHub With a ChatGPT Agent

The Controller supports a protected GitHub Actions workflow that imports a verified manga from private staging. **Original manga ZIPs, page images, covers, rights evidence and credentials never enter the public GitHub repository or its public Actions artifacts.** The source images are only transferred to the existing private Hugging Face dataset under an opaque staging ticket.

## One-time setup

The GitHub workflow is in .github/workflows/private-agent-manga-ingest.yml, running from master using the existing protected hf-manga-upload environment and its HF_TOKEN secret. This must be configured with read/write access to the private dataset. The public code repository stays public; the Hugging Face dataset remains private.

On Windows, update your Manga Storage Controller checkout:

    git pull origin master
    py -3.11 -m pip install -e ".[huggingface]"

## Prepare the manga locally, without uploading canonical data

For Acquainted: Encounter Spin-Off, the local folder contains the pages ZIP, metadata ZIP, separate cover image, and the private working directory created by the existing uploader. Run its **no-write** validation first:

    py scripts\upload_acquainted_windows.py --folder "C:\Users\krish\Downloads\Acquainted" --dry-run

When the original source ZIP was repaired by replacing an image with an intact source copy, use --refresh-source-images --dry-run once instead. When using a visually reviewed repaired candidate, use --use-reviewed-repairs --dry-run. Never approve an image with missing grey/blank artwork.

This builds the existing verified local candidate at:

    C:\Users\krish\Downloads\Acquainted\.acquainted-private-import\bundle
    C:\Users\krish\Downloads\Acquainted\.acquainted-private-import\metadata\candidates.json
    C:\Users\krish\Downloads\Acquainted\.acquainted-private-import\metadata\covers\...

## Securely stage the verified source once

Run:

    py scripts\stage_manga_for_github.py --work-dir "C:\Users\krish\Downloads\Acquainted\.acquainted-private-import"

This requires your scoped HF token, from the current HF_TOKEN environment variable or a hidden prompt. It validates the complete local bundle and source metadata, creates an immutable checksum-pinned ZIP and uploads only to these private staging paths:

    ingest/agent-queue/<ticket>/package.zip
    ingest/agent-queue/<ticket>/manifest.json

It **does not change data/library.json or publish canonical manga pages**. It prints an opaque 32-character hexadecimal ticket.

Send that ticket to ChatGPT in this conversation, asking to trigger and verify the GitHub import. The ChatGPT agent can then use its connected GitHub account to post commands to the dedicated public GitHub issue titled **Private manga import queue**, without posting any source data.

## GitHub agent-triggered protocol

On [issue #36](https://github.com/AdityaSreevatsaK/Taiyou-Manga-Storage-Controller/issues/36), with the exact title **Private manga import queue**, only comments authored by the repository owner may initiate an import. The workflow and parser both pin the issue number; another issue with the same title cannot initiate an import. The command format is:

    /manga-import <32-character-ticket> preview

The protected GitHub Action reads the private source at an immutable HF revision and fully decodes and hashes **every** page. It validates page dimensions, MIME types, byte counts, immutable IDs, ordered manifests, metadata, cover paths, permission evidence and title conflicts. The owner does **not** need to visually review thousands of individual pages. Fully valid but incorrect/blank source images may still require exception-based visual review. It prints a **sanitised** one-line JSON preview including the current 40-character dataset revision and a 64-character fingerprint of the exact approved plan. No canonical writes occur.

To apply the **same** unchanged preview, the agent posts:

    /manga-import <32-character-ticket> apply <40-character-expected-revision> <64-character-fingerprint>

Apply refuses changes in the private dataset, source bytes, title/ID conflicts or metadata between preview and apply. The owner must separately approve the specific preview summary, source/rights context and any exceptions before asking an agent to apply. A successful automated check, a fingerprint printed by GitHub or control of the repository account is **not** itself permission to proceed. Require a human approval gate on the `hf-manga-upload` environment and verify its configuration before enabling apply. The existing Controller performs checkpointed append-only media uploads, creates an automatic catalogue backup, publishes the manga entry last, and then performs revision-guarded metadata/cover enrichment. Original media are never overwritten. Existing catalogue entries and original page identities are preserved.

The agent reads workflow job results and reports the verified dataset revision and chapter/page totals. After a new manga is published, the workflow downloads and rechecks every newly uploaded page against its manifest SHA-256, MIME, dimensions and byte size. This potentially consumes substantial time and bandwidth for large manga; it does not re-download every existing title. The workflow prints no original media URLs or tokens and never uploads GitHub Actions artifacts.

## Manual fallback

From GitHub Actions, choose **Owner-agent private manga ingest (preview then protected apply)** and select **Run workflow**. Enter the ticket, phase (preview or apply) and, for apply, the exact revision and fingerprint from the preview result. It uses the same protected code path as owner-authored issue comments.

## Source and privacy guarantees

- GitHub cannot directly read your Windows files. One secure upload into the existing private HF staging area is necessary.
- Do not attach original manga ZIPs or cover images to public GitHub issues, releases or artifacts.
- Staged originals remain private after upload for recovery. Cleanup/deletion is not automatic.
- New-series import is append-only. Changing pages or chapter IDs of a previously uploaded manga is deliberately refused.
- If the process is interrupted, post a new preview for the same ticket, then use a new fingerprint. Never reuse a stale approval.
- A pre-change catalogue JSON backup is **not** an off-platform full-media backup. Before any write that could endanger existing original bytes, require an independently verified full-media backup and isolated recovery rehearsal. The Library Master correction endpoint has distinct backup behaviour. Controller PR #37 aligned its accepted `dropped` status with the Library, while the meaning of that status versus a personal dropped-reading state still needs a joint contract decision (Controller issue #38).
- The canonical destination remains AdityaSreevatsaK/Taiyous-Manga and its data/library.json, data/manifests/, data/manga/, data/covers/ paths. Manga Library needs no new schema.
- The workflow can be retried by ChatGPT through GitHub comments once a ticket has been staged. New tickets require separate validation. If image/media upload succeeds but metadata/cover enrichment fails, the manga may already be catalogued: preserve it, report a partial publication, obtain a fresh snapshot and a separately reviewed metadata-only plan. Do not automatically roll back or overwrite page originals.
