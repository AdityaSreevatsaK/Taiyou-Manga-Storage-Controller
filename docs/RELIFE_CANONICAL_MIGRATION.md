# ReLIFE canonical private Hugging Face migration

Owner explicitly authorised high-priority migration on 20 November 2026.

Source is the pinned private ReLIFE revision a055b54ee5bdc980f7641bd2beb09e30fca0fb19:
237 chapter manifests and 5,606 original image pages.

Destination is the Manga Library's existing canonical contract:
data/manifests/, data/manga/, and data/library.json. All original paths and
contents (root catalogue.json, manifests/, assets/manga/, identity records,
ingest checkpoints) remain untouched.

Process:
1. Verify the complete protected original recovery revision and audited hashes.
2. Copy 5,843 files in revision-guarded resumable batches into a private staging branch.
3. Compare content-addressed file IDs, LFS SHA-256 (if available) and byte sizes for all files.
4. Publish data/library.json last in staging and validate it.
5. Repeat additive copy to private main, verify all files, publish the canonical catalogue last.
6. Check all original 5,843 paths are still present.

The existing pinned Hugging Face recovery branch is not an independent
off-platform backup. This operation is non-destructive and does not rely
on removing original files. It does not enable live page delivery through
the Manga Library reader or automatically upload the other four manga.
