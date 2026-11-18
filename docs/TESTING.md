# Tests and evidence

Offline tests cover valid and corrupt PNGs, MIME mismatch, decoded size limits, natural ordering, ZIP/CBZ traversal and case-insensitive duplicates, symlinks, suspicious compression, non-images, stable IDs after title updates, idempotent rebuilds, strict manifest validation, missing assets, duplicate pages, revision conflicts, no-op mock reruns, unapproved mock write rejection, full-media backup integrity and non-destructive restoration. `hf-health` validation has no live CI invocation. No credentials or private content are needed.

Run `python -m unittest discover -s tests -v` with Pillow installed. Then `python -m ruff format --check .`, `python -m ruff check .`, `python -m mypy src/taiyou_manga`, `python -m pip_audit`. CI matrix: Windows/Linux, Python 3.11/3.12. Do not claim that hosted CI passed until the actual PR workflows complete.

**Unverified pending work:** multi-process mock revision race, realistic interrupted remote uploads, private HF authorisation failures, AVIF portability on the four CI runners, full browser/reader compatibility and cloud restore. These require additional dedicated tests before any live writes.
