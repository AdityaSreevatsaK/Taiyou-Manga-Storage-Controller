# Architecture

```text
Owner-provided authorised folders or ZIP/CBZ
   -> sources (path and archive preflight, bounded ZIP reads)
   -> images (magic/signature + full Pillow decode + size/dimension + SHA-256)
   -> builder (identity registry, candidate MangaEntry + ChapterManifest)
   -> private local bundle (catalogue, manifests, assets, local inventory, optional rights)
       -> verify (redecode bytes + exact manifest checksums)
       -> local mock (preview, immutable snapshots, optimistic revision)
       -> full-media backup (index of SHA-256 digests) -> verified non-destructive restore

Optional: HuggingFaceReadOnly.health() -> authenticated HF dataset_info (no writes)
```

The CLI orchestrates pure domain checks and separate storage classes. `StorageReader` is a small typed boundary. No browser UI, server, shared login or automatic metadata sync is implemented. `master` belongs only to this controller. The Manga Library retains ownership of its published contracts; this controller does not write to that repository.

## Current limitations

The source-folder parser infers a **candidate** series/volume/chapter layout from `<series>/<volume>/<chapter>/pages` or `<series>/<chapter>.cbz`; a standalone folder/CBZ is one series with one chapter. This is deliberately not a persisted HF layout. A local registry keyed by relative source path preserves IDs across title edits and repeat import; reorganising or replacing a source path needs a reviewed identity reconciliation tool before real use. The mock's snapshots are intended for offline integration tests and cannot model remote permissions or every network failure. ZIP decompression runs in the current process; for hostile inputs an isolated resource-limited worker is a further hardening step.
