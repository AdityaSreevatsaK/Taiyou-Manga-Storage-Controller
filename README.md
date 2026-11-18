# Taiyou Manga Storage Controller

Offline-first, **Windows-friendly** Python tools for inspecting authorised manga images, generating private candidate manifests, verifying local media, previewing uploads against a mock and creating recoverable backups. **No real manga source files, Hugging Face dataset or final storage layout are required.**

> **Privacy and rights:** This GitHub repository is public. Never commit manga images, private manifests, media backups, personal notes or credentials. Only import media you are authorised to store. The controller does not download or scrape manga. **Hugging Face writes are disabled.**

## Quick start on Windows (PowerShell)

Install Python 3.11 or 3.12, then:

```powershell
git clone https://github.com/AdityaSreevatsaK/Taiyou-Manga-Storage-Controller.git
cd Taiyou-Manga-Storage-Controller
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m taiyou_manga menu
```

If PowerShell activation is restricted, use `.\.venv\Scripts\python.exe -m taiyou_manga menu` directly. Alternatively, once installed with `py -3 -m pip install -e .`, double-click **`00_manga_storage_menu.cmd`**.

## Complete offline demonstration

```powershell
python -m taiyou_manga fixtures --output demo_manga
python -m taiyou_manga scan --source demo_manga
python -m taiyou_manga manifest --source demo_manga --output bundles/demo-1 --rights-json demo_manga-rights-example.json
python -m taiyou_manga inventory --bundle bundles/demo-1
python -m taiyou_manga export-csv --bundle bundles/demo-1 --output reports/demo-1.csv
python -m taiyou_manga verify --bundle bundles/demo-1
python -m taiyou_manga plan-upload --bundle bundles/demo-1 --mock-dir mock_remote
python -m taiyou_manga backup --bundle bundles/demo-1 --output backups/demo-1.zip
python -m taiyou_manga check-backup --backup backups/demo-1.zip
python -m taiyou_manga restore --backup backups/demo-1.zip --destination bundles/restore-preview
```

`restore` previews only by default. Add `--approve` to restore into a **new** local folder. `mock-upload` also requires `--approve` and the exact expected revision from `plan-upload`; it writes only to a disposable local mock directory. Neither command writes to Hugging Face.

The synthetic generator creates **two original fictional series, four chapters and 12 PNG pages**. The default candidate manifest uses the Manga Library's `ChapterManifest` v1 and `MangaEntry` field shapes. A `.manga-controller/ids.json` registry preserves opaque IDs across repeat imports; keep this private file backed up. Registry writes now use a cross-process exclusive lock and a secure atomic file replacement. If a prior process crashed, inspect any `ids.json.lock` before manually clearing it. Changing a displayed title does not change IDs. Changing the source paths without preserving the registry mapping is **not yet supported**.

## Current boundaries

| Area | Status |
| --- | --- |
| Folders, ZIP/CBZ, PNG/JPEG/WebP/AVIF content validation | Implemented; AVIF decode needs a Pillow build with AVIF support |
| Natural page ordering, SHA-256, image dimensions, duplicate pages, immutable IDs | Implemented locally |
| Local candidate manifests and original media bundle | Implemented (not an approved cloud layout) |
| JSON reports, local mock revisions, preview-only upload planning | Implemented |
| Verified full-media backups, read-only restore preview, new-folder restoration | Implemented |
| Read-only private HF dataset health | Optional; requires `pip install -e ".[huggingface]"` and an explicit repo ID |
| HF upload, private cloud reader, account creation, sync, destructive commands | **Disabled / awaiting owner approval** |

**CSV exports contain private series and chapter titles.** They use a new-file-only destination, spreadsheet formula escaping and a Git-ignore rule, but should never be committed or shared publicly. The Windows menu also offers CSV export.

Local backup archives include media **and** manifests. A catalogue export on its own is **not** a media backup. Mock preview now also reports `metadataConflicts` and refuses changed chapter order, catalogue records and rights evidence; it will not silently declare a metadata-only change a no-op. For contracts and decisions see [docs/DATA_CONTRACTS.md](docs/DATA_CONTRACTS.md), [docs/SAFETY_AND_RECOVERY.md](docs/SAFETY_AND_RECOVERY.md) and [docs/ROADMAP.md](docs/ROADMAP.md).

## Development

```powershell
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
python -m ruff check .
python -m ruff format --check .
python -m mypy src/taiyou_manga
```

GitHub Actions covers Python 3.11/3.12 on Windows and Linux with synthetic fixtures only. No Hugging Face authentication is required in CI.

Software is MIT-licensed; **this licence does not grant any rights to third-party manga artwork**.
