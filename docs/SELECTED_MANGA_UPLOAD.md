# Selected manga private Hugging Face imports

On 20 November 2026, the owner explicitly instructed the Controller to upload these four manga to the private Hugging Face dataset `AdityaSreevatsaK/Taiyous-Manga`. Permission to host them is user-attested rather than independently verified.

| Source title | Retriever run | Main numbered chapters | Reported pages | Expected outer ZIPs |
| --- | ---: | ---: | ---: | ---: |
| Kaichou wa Maid-sama! | 44587087000 | 85 | 3415 | 5 |
| Last Game | 44587087000 | 56 | 2022 | 3 |
| Love So Life | 44597036262 | 106 | 3326 | 6 |
| Onizuka-chan and Sawarida-kun | 44675324997 | 49 | 274 | 3 |

The first run failed overall **only because its Onizuka jobs failed**. Its Maid-sama and Last Game jobs succeeded with verified artefacts. Onizuka is taken instead from the successful later recovery run. The original GitHub artefacts expire on 26–27 November 2026.

## Source validation

The selected source importer downloads only its title's expected ZIPs, validates all archive names and metadata, independently checks every nested CBZ SHA-256, image SHA-256, image size and dimensions, and refuses missing numbered chapters. Genuine decimal bonus chapters and chapter-zero one-shots are retained. A repeated bonus archive may have different ZIP metadata while its page content hashes are identical, so duplicates are reconciled using ordered page fingerprints. Conflicting duplicates are rejected. Numbers and identities are stable and based on the source title slug and chapter number.

## Private dataset publication

The workflow `.github/workflows/selected-manga-private-hf-upload.yml` runs on `master` with the existing protected `hf-manga-upload` environment and serialises against the ReLIFE upload. It processes the four titles on separate runners, one at a time.

For each title, it creates a verified single-series reader-compatible candidate, creates an exact no-write preview, checks dataset privacy, rejects unexpected existing paths and then uploads new original page images in append-only batches of at most 150 files. Each batch has a digest checkpoint committed with an expected parent revision. A rerun safely skips completed matching batches.

**The private root `catalogue.json` is merged rather than replaced wholesale.** Existing entries, including ReLIFE, remain unchanged. The new series entry is added only in the final revision-guarded commit, after its image pages and manifests are ready. Individual title source IDs are deterministic and stored privately under `control/<slug>-identities.json`.

Temporary ZIPs, extracted CBZs, candidate assets and previews are deleted by the workflow. No scan images or HF credentials are put into the public repository or downloadable GitHub Actions artefacts. Metadata and private source attestations are stored under `ingest/<slug>-v1/`. Reader deployment is a separate step.

## Failure and retry

If a title fails, its uploaded page batches may remain privately checkpointed without adding an incomplete catalogue entry. Rerun the same workflow to resume; completed titles should report `already-complete`. Do not delete existing HF files or force-push the dataset. If ReLIFE's own upload is incomplete, finish that first to preserve its catalogue publication barrier.

Once the four title uploads have completed, independently check all five catalogue titles and reader manifests through the private HF API. The Manga Library's runtime private asset adapter will then need to be updated or verified before declaring the titles readable in the web application.
