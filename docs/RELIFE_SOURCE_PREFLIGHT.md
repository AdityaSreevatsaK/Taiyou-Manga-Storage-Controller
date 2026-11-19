# ReLIFE GitHub Actions artefact preflight

This process **only reads and verifies source material**. It never writes to Hugging Face, publishes manga images as a new Actions artefact, alters the Retriever run or updates any reader catalogue.

Source: [ReLIFE run #44547390262](https://github.com/RichardDaffern/Manga-Retriever/actions/runs/44547390262), verified with GitHub metadata on 20 November 2026. The 12 original Actions ZIPs expire on **26 November 2026**.

## Automated source check

The Controller's workflow **ReLIFE source artefacts deep preflight (read-only)** runs once after its workflow file is merged to `master`, and can be rerun from the Actions tab. It:

1. Uses its short-lived `GITHUB_TOKEN` to request exactly the 12 `ReLIFE-Original-Quality-Ch*-*` source artefacts from run #44547390262.
2. Follows only validated GitHub-owned HTTPS signed download origins, without forwarding the GitHub token to storage.
3. Saves ZIPs temporarily on the isolated runner, never inside the repository or in new downloadable artefacts.
4. Runs `python -m taiyou_manga relife-preflight --artifact-dir "$RUNNER_TEMP/relife-archives"`. This verifies 222 integer chapter identities, the 15 expected decimal-numbered extras, the expected 5,606 pages, and every CBZ SHA-256/page hash/size/dimension.
5. Deletes temporary downloads regardless of success or failure.

**Important:** Results may still reveal that the source files are inconsistent. The Retriever jobs reported 237 CBZs and 5,606 pages, but those logs are not a substitute for the independent audit. The original source permission/rights statement does not confer upload permission.

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
