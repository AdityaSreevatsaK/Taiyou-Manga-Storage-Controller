# Acquainted: Encounter Spin-Off: invalid JPEG recovery

The Windows uploader now diagnoses the exact failed image and records the underlying Pillow exception. It does not skip pages, edit the original ZIP or silently recover damaged artwork. An apparent JPEG repair may hide missing artwork, so **visual review is required**.

## Step 1: Update Controller and diagnose without uploading

Open PowerShell in the Manga Storage Controller repository:

    git pull origin master
    py -3.11 -m pip install -e ".[huggingface]"
    py -3.11 scripts\upload_acquainted_windows.py --folder "D:\Manga\Acquainted" --dry-run

If page 7_9.jpg is invalid, the script creates a diagnostic report at:

    D:\Manga\Acquainted\.acquainted-private-import\image-diagnostics.json

If the JPEG is technically recoverable, a candidate appears at:

    D:\Manga\Acquainted\.acquainted-private-import\repaired-candidates\7_9.jpg

**Open the entire candidate image and inspect it.** Missing segments may be replaced by blank pixels. A decoder-accepted picture is not proof of intact art.

## Step 2a: The recovered candidate is visually complete

First validate the local candidate bundle, with no HF write:

    py -3.11 scripts\upload_acquainted_windows.py --folder "D:\Manga\Acquainted" --use-reviewed-repairs --dry-run

After checking the result, run without dry-run to use the original guarded, revision-pinned private Hugging Face uploader:

    py -3.11 scripts\upload_acquainted_windows.py --folder "D:\Manga\Acquainted" --use-reviewed-repairs

The tool builds a separate validated-pages folder and does not edit the original ZIP or original extracted pages.

## Step 2b: The candidate is unrecoverable or visibly incomplete

Find an intact, authorised source copy of the damaged image. Replace the page at the same location **inside your own manga ZIP**, retaining a backup of the earlier ZIP. Then rerun:

    py -3.11 scripts\upload_acquainted_windows.py --folder "D:\Manga\Acquainted" --refresh-source-images --dry-run

This archives, rather than deletes, the old extracted pages and any previous candidate bundle. It preserves the ID registry, so the series/chapter IDs remain stable. When the new local build is verified, run again normally without dry-run.

## Guarantees

- Every page must validate and decode fully; nothing is silently skipped.
- No repair candidate is used without the explicit use-reviewed-repairs option.
- Original images and private data remain preserved.
- Pages are not published until all local page manifests validate.
- Existing manga entries cannot be replaced or rewritten through this importer.
- The private dataset is AdityaSreevatsaK/Taiyous-Manga.
- The script does not claim that missing artwork can always be reconstructed.
