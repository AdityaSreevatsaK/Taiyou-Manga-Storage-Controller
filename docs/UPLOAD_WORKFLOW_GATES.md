## Protected upload workflow

The four-title uploader is deliberately manual via GitHub Actions and
cannot write anything without the environment variable
`TAIYOU_INDEPENDENT_BACKUP_AND_STAGING_VERIFIED=yes` in the protected
`hf-manga-upload` environment. Set that value only after an independent
full-media off-platform backup has been checked and an isolated private
staging migration has passed.

The uploader then refuses to proceed unless the private dataset already
contains a valid `data/library.json` envelope with ReLIFE and all its
canonical chapter manifests. The existing ReLIFE legacy paths are left
untouched. Each of the four titles uses exact source artefact batch IDs,
revision-guarded resumption, and publishes its own manga entry to the
canonical catalogue last.

**Do not dispatch while the dataset remains in the legacy layout.**
Source artefacts expire 26-27 November 2026. No public manga archives are
created by this workflow.
