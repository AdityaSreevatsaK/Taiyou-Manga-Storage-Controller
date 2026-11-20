# Protected owner-approved four-manga Hugging Face upload (20 November 2026)

The owner expressly requested uploading the four previously validated English
manga after ReLIFE was migrated to the canonical private dataset.

The full ReLIFE copy to `data/` was independently checked in a private staging
branch before its successful production migration. All 5,606 canonical page
files, 237 chapter manifests and original legacy files were verified.

**No independent off-platform full-media backup has been made.** Do not set
`TAIYOU_INDEPENDENT_BACKUP_AND_STAGING_VERIFIED=yes` to pretend otherwise.

For this specific four-title, append-only operation the protected Actions
workflow uses the separate explicit approval
`TAIYOU_FOUR_TITLE_APPEND_ONLY_APPROVAL=approved-2026-11-20`. The workflow
first verifies the original ReLIFE recovery branch and staging branch, checks
the live 5,606-file media inventory, and pins a *private HF recovery branch*
at the verified canonical ReLIFE revision. This is a recovery reference in
the same Hugging Face account, not an independent backup.

The serial upload jobs then recheck the private canonical catalogue and use
immutable page and chapter IDs, expected-parent revision guards, audited
source batches, checkpointed append-only media commits and final catalogue
merges. Existing data is never deleted or overwritten, apart from the
versioned canonical library index after verified addition.

The workflow runs once on merging the workflow change to `master`; it can
also be rerun manually to resume incomplete checkpointed batches.

Four selected original-quality manga sources: Kaichou wa Maid-sama!,
Last Game, Love So Life and Onizuka-chan and Sawarida-kun. The 17 source
GitHub Actions ZIPs expire on 26-27 November 2026.

**Success criterion:** All four titles have completion markers, original
page and chapter files, and validated entries in the canonical private
`data/library.json`. An Actions workflow entering or completing source
validation alone does not count as a completed HF upload.
