# Decisions and open approvals

- 2026-11-18: Public controller source, **private media only**; avoid committing media or metadata.
- 2026-11-18: Python 3.11/3.12 + Pillow; no heavyweight frameworks; synthetic tests only in CI.
- 2026-11-18: Use the Manga Library's current ChapterManifest v1 and opaque IDs. Keep controller-only candidate inventory separated from any final persisted schema.
- 2026-11-18: ZIP/CBZ and folders supported as input candidates, not a promise of final source packaging.
- 2026-11-18: Local mock writes permitted only with approval and exact revision. HF live write operations intentionally unimplemented. No data deletion/reset.
- 2026-11-18: Full-media backup includes binaries, rights and metadata; catalogue backup must never be described as equivalent.
- 2026-11-18: Mock revision fingerprints cover every validated page, chapter manifest, catalogue, inventory and rights declaration. Metadata modifications and missing records fail closed; no automatic metadata merge or rewrite. Existing local mocks created with the old digest format require a fresh disposable mock directory (not a production data migration).

- 2026-11-18: Local identity registry updates are protected by an exclusive cross-process lock and an atomic temp-file replacement to avoid lost IDs and progress misalignment on concurrent imports. A failed publish may reserve unused IDs, which are safe to reuse on retry.

Awaiting owner: exact source archive arrangement, stable series identity after moving files, private HF dataset name and creation, owner auth, source rights and quotas, cloud commit protocol, reader adapter, backup retention, automatic sync, deletion policy and live mutation gate. Proposed Manga Library ADR-006 is **not an approved architecture**.

- 2026-11-20: The owner confirmed permission to host the specific ReLIFE English scans privately on Hugging Face and approved upload to `AdityaSreevatsaK/Taiyous-Manga`. This permits only the dedicated, append-only ReLIFE workflow with deterministic IDs, expected-parent commits, verified source pages and last-commit publication. No other original media upload or deletion is authorised by this approval. The permission is owner-attested, not independently checked.
