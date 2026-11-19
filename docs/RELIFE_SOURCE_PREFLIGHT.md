# ReLIFE GitHub Actions artefact preflight

This process **only reads and verifies source material**. It never writes to Hugging Face, publishes manga images as a new Actions artefact, alters the Retriever run or updates any reader catalogue.

Source: [ReLIFE run #44547390262](https://github.com/RichardDaffern/Manga-Retriever/actions/runs/44547390262), verified with GitHub metadata on 20 November 2026. The 12 original Actions ZIPs expire on **26 November 2026**.

## Automated source check

The Controller's workflow **ReLIFE source artefacts deep preflight (read-only)** runs after a change to its workflow file is merged to `master`, and can be rerun from the Actions tab. It:

1. Uses its short-lived `GITHUB_TOKEN` to request exactly the 12 `ReLIFE-Original-Quality-Ch*-*` source artefacts from run #44547390262.
2. Follows only validated GitHub-owned HTTPS signed download origins, without forwarding the GitHub token to storage.
3. Saves ZIPs temporarily on the isolated runner, never inside the repository or in new downloadable artefacts.
4. Runs `python -m taiyou_manga relife-preflight --artifact-dir "$RUNNER_TEMP/relife-archives"`. This verifies 222 integer chapter identities, the 15 expected decimal-numbered extras, the expected 5,606 pages, and every CBZ SHA-256/page hash/size/dimension.
5. Builds one temporary, private candidate with all 237 chapters in numeric reading order, verifies its chapter/page manifests and original image bytes, and checks that the reader-facing catalogue contains only **ReLIFE**.
6. Deletes all temporary downloads, candidate media and provisional identity files regardless of success or failure.

**Important:** Results may still reveal that the source files are inconsistent. The Retriever jobs reported 237 CBZs and 5,606 pages, but those logs are not a substitute for the independent audit. The audit validates the MangaDex downloader's auxiliary `cover.jpg` by actual decoded image format (which may differ from the `.jpg` filename) and `download.db` SQLite tracking file without treating either as a CBZ chapter or an authorisation record. Both are discarded with the temporary source artefacts. The original source permission/rights statement does not confer upload permission.

If GitHub's repository-scoped `GITHUB_TOKEN` cannot fetch the other public repository's artefact ZIPs, the owner will need a separate fine-grained GitHub token restricted to `RichardDaffern/Manga-Retriever` with `Actions: read`; do **not** use an unrestricted personal access token or the HF token for this purpose.

## Local alternative

If you have already downloaded the **outer GitHub artefact ZIPs** (all 12, still compressed), put them in a new private folder and run:

```powershell
python -m taiyou_manga relife-preflight --artifact-dir "C:\\Manga\\ReLIFE-Actions-Zips"
```

Use `--metadata-only` for a faster preview that does **not** verify media bytes and is not an upload gate.

## Pending for actual HF storage

**The dataset `AdityaSreevatsaK/Taiyous-Manga` is confirmed private and readable** through the existing protected workflow. Upload remains disabled pending content permission for remote storage, a chapter/series and dataset layout approved for reader integration, immutable backups and revision-checked recovery. A secret being present does not automatically grant rights to host third-party manga scans.

This preflight intentionally requires no `HF_TOKEN`; it cannot write to the dataset.

## Staging boundaries

`python -m taiyou_manga relife-stage --artifact-dir "C:\\Manga\\ReLIFE-Actions-Zips" --output "C:\\Manga\\ReLIFE-Candidate" --state-file "C:\\Manga\\ReLIFE-Provisional-Ids.json"` produces a **new local private** bundle only after a complete, fresh deep verification of all 12 batches. It never modifies an existing bundle or registry.

The candidate standardises source chapter labels as `Chapter 1` through `Chapter 222` with the 15 decimal extras placed numerically in between, and sets reading direction to `vertical`. The source-specific uploader group and volume metadata are not silently invented. ReLIFE source provenance remains associated with the original audit, not falsely presented as upload permission.

**The opaque IDs in this one-time staging run are provisional and discarded with the runner.** Before any real upload, design a persistent, backed-up identity registry and align the Manga Library's private persistence adapter. The controller's candidate inventory is not an approved HF production schema. Even a green staging run does **not** permit remote storage of copyrighted scanlations.
