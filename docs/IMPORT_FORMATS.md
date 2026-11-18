# Import formats and limits

Implemented: direct chapter folders, nested candidate folder hierarchies, ordinary ZIP and CBZ archives; PNG/JPEG/WebP/AVIF pages. AVIF decoding depends on Pillow build support. Example candidate layout: `Source/Series/Volume 1/Chapter 1/001.png`; archives can replace chapter folders. Filenames receive natural numeric ordering, e.g. 1, 2, 10. Repeated/missing terminal page numbers are reported as warnings; duplicate decoded file content *within a chapter* is rejected.

Defaults: 25 MB per page, 16,000 pixels per side, 70 million pixels total, 1,000 pages per chapter/archive, 500 MB uncompressed per archive, compression ratio <= 100. The `Limits` Python model supports overriding bounds for tests and future configuration. ZIP members cannot be traversals, encoded paths, symlinks, directories masquerading as pages, encrypted or invalid image types. Folder symlinks are rejected. Files are decoded and checked against their declared extension, not accepted based on suffix alone. No silent repair or OCR/transcoding is performed.

**Not implemented:** RAR/7z/CBR, PDF, manga downloads, DRM bypass, arbitrary external URLs, dynamic import recipes, ZIP nesting or a one-click remote import. Exact source packaging remains an owner decision.
