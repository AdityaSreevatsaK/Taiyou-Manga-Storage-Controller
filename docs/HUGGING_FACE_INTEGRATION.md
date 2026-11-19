# Hugging Face dataset integration (manual read-only readiness gate)

Owner-designated dataset: `AdityaSreevatsaK/Taiyous-Manga`. **Private status and token access remain to be verified**, and **no media upload or other remote mutation is enabled** by this change.

## Your GitHub setup

In the public `AdityaSreevatsaK/Taiyou-Manga-Storage-Controller` repository:

1. Go to **Settings → Environments → New environment** and create `hf-manga-upload`.
2. Restrict deployment branches to `master`. Configure required reviewers if practicable; do not enable *Prevent self-review* when you are the only eligible reviewer.
3. Inside that environment, add the **environment secret** `HF_TOKEN` whose value is the privately created Hugging Face token. Do not put it in a repo file, commit, Actions input, issue or chat. A **fine-grained token scoped to this dataset** is preferable to an unrestricted write token.
4. The read-only health workflow runs automatically on its first merge to `master` (and only on subsequent changes to its own workflow file). You can also open **Actions → Verify private Manga Hugging Face dataset (read-only) → Run workflow** on `master`. Approve the environment job if requested.

The workflow runs `hf-health --repo-id AdityaSreevatsaK/Taiyous-Manga` with no write code. It only checks that credentials can **read** the target and that the dataset is **private**. It does not prove the token can write, verify quota, validate media rights or create any HF commit. The secret is not printed. The workflow cannot execute on PRs. It also runs on a `master` push changing this workflow file, then remains available for manual re-checks.

## Next import design and blockers

The source run [Manga-Retriever #44547390262](https://github.com/RichardDaffern/Manga-Retriever/actions/runs/44547390262) contains **12 seven-day artefacts**, approximately **1.35 GB combined**, with **237 audited CBZ archives and 5,606 audited pages** in 12 batches nominally covering 222 numbered chapters. Extra or duplicate releases must be resolved by source chapter identity; passing per-batch CBZ counts is not proof of a complete unique series. The source artefacts expire on **26 November 2026**. Source CBZs can contain `ComicInfo.xml`, now safely accepted in the candidate importer without treating its metadata as rights evidence. Use `relife-preflight` to reject missing/duplicate chapters and independently validate the source CBZ and page checksums before considering an upload. An import must validate those XML metadata entries safely and map the CBZs into one series.

The Controller candidate v1 bundle is **not yet an approved persisted HF dataset schema**. Before real writes, confirm (a) the right to store the particular English scans remotely, (b) a verified complete chapter map and original-byte digests, (c) a private, revision-guarded dataset commit and explicit metadata/rights schema, (d) backup/recovery and safe retries, and (e) that the downstream Manga Library private reader and stable IDs can consume the persisted layout.

A GitHub Actions upload running in this Controller repository cannot assume its default `GITHUB_TOKEN` can download **another repository's** workflow artefacts. It may need a **separate fine-grained GitHub token restricted to `RichardDaffern/Manga-Retriever` with Actions:read**, held as a protected environment secret, or a separately authorised transfer strategy. No such additional secret is required for the read-only dataset health check. Do not place the Hugging Face write token in the public Retriever repository.

Remote writes must use authenticated HF commits with expected-parent revision checks, reject conflicting overwrites/deletes and be staged for recovery. The user-approved destination and secret setup are *configuration approvals*, not verification of rights to copy third-party scanlations to another platform.

## Local read-only alternative

Install `pip install -e ".[huggingface]"`, authenticate locally with `hf auth login` if appropriate, then run:

```powershell
python -m taiyou_manga hf-health --repo-id AdityaSreevatsaK/Taiyous-Manga
```

The output includes only the dataset revision and private/read-only status, not source titles or credentials.

## Read-only artefact validation

See [ReLIFE source preflight](RELIFE_SOURCE_PREFLIGHT.md). The Controller can temporarily download and independently audit the source run in a separate GitHub Actions workflow using its ephemeral token, if cross-repo read access permits. That workflow never reads `HF_TOKEN` or uploads original content. Real remote write operations still require separate rights, backup, layout and revision-gate approval.
