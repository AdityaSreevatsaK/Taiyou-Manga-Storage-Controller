# Four-title intake, canonical storage migration (20 November 2026)

The user requested private upload of Kaichou wa Maid-sama!, Last Game,
Love So Life, and Onizuka-chan and Sawarida-kun. All 17 source ZIPs were
available on GitHub Actions on 20 November and expire 26-27 November.

This branch reuses verified archive validation and deterministic IDs from the
superseded PR #20. It does NOT reuse the obsolete root catalogue uploader.
Source candidates are local intermediate bundles ONLY.

## Upload contract
Final production paths MUST follow the live Manga Library contract:
- `data/library.json` envelope `{"schemaVersion":1,"mediaKind":"manga","entries":[...]}`
- `data/manga/<manga-id>/<chapter-id>/<page-id>.<original-extension>`
- `data/manifests/<chapter-id>.json`
- `data/covers/<manga-id>.webp` when available.

Preserve all IDs, chapter order, original bytes/checksums, and ReLIFE.
Every new title must be published last to a revision-guarded MERGE of the
canonical catalogue, never overwrite unrelated titles.

**No live HF writes until** the ReLIFE full-media independent off-platform
backup and private staging migration test are verified, including page
delivery through the reader. The pinned Hugging Face recovery branch is
not an independent backup. The source verification job does not use HF_TOKEN.
