# Preserve manga identities after source-folder moves

**Local-only, opt-in.** When the same manga is moved or renamed, its relative source keys can change. Without an explicit migration, the next `manifest` build might generate different series/chapter IDs and break reading progress. This tool never modifies original image files, existing bundles, cloud storage or reading progress.

## 1. Inspect the private registry and source layout

The `--state-file` is the same private `ids.json` used with `manifest`. The source keys follow import-relative POSIX paths:

- `series:Signal Garden` for the directory directly under the selected source root;
- `chapter:Signal Garden/Volume 1/Chapter 1` for one of its chapter folders;
- a single source ZIP/CBZ uses `chapter:.`; its series key is the archive's filename stem.

Run `scan --source <root>` and compare its chapter paths with your locally stored registry **before** writing a mapping. Source paths, IDs and backup files are private and should never be committed to a public repository.

## 2. Prepare a complete private mapping

Save the following example in `.manga-controller/rename-plan.json` using your actual old/new relative paths:

```json
{
  "schemaVersion": 1,
  "moves": [
    {"kind": "series", "from": "Signal Garden", "to": "Signal Archive"},
    {"kind": "chapter", "from": "Signal Garden/Volume 1/Chapter 1", "to": "Signal Archive/Volume 1/Chapter 1"},
    {"kind": "chapter", "from": "Signal Garden/Volume 1/Chapter 2", "to": "Signal Archive/Volume 1/Chapter 2"}
  ]
}
```

A series-folder rename **must include every registered chapter underneath it** in the same transaction. Renaming only a chapter folder needs just its corresponding `chapter` entry. Moving an entire archive without changing its filename generally does not require an ID migration. The tool never infers that two folders contain identical content: **you** must check the mapping matches the intended media. It rejects missing originals, duplicate destinations, existing targets, unsafe paths and case-colliding identities.

## 3. Preview, then explicitly apply with a backup

```powershell
python -m taiyou_manga identity-migrate --state-file ".manga-controller/ids.json" --mapping-json ".manga-controller/rename-plan.json"
```

The command is **preview-only by default**. Review every `from`, `to` and `preservedId` and copy the returned `currentRevision` SHA-256. If satisfied, run the approval command below, substituting that exact value:

```powershell
python -m taiyou_manga identity-migrate --state-file ".manga-controller/ids.json" --mapping-json ".manga-controller/rename-plan.json" --backup ".manga-controller/ids-before-rename.json" --expected-revision "<paste exact 64-character SHA-256>" --approve
```

Approval uses the same exclusive lock as an import, refuses existing backup files, saves the **exact original registry bytes** to a new backup, and atomically installs the remapped registry. Any revision change requires a new preview. There is no overwrite mode or automatic cloud operation. On publication failure, the original registry remains unchanged; the backup may remain as an additional recovery copy.

## 4. Rebuild and recover

Rebuild the moved manga into a **new output folder** with the migrated `ids.json`, and verify the bundle. Its opaque series/chapter IDs should match the earlier bundle, and unchanged image bytes will preserve the derived page IDs.

For a deliberate rollback, prepare a *reverse mapping* with each `from` and `to` swapped, preview it against the current registry, and apply it with a **new** unused backup and a fresh exact revision. Do not roll back after subsequent unrelated imports without reviewing those changes first.

Keep `ids.json`, the mapping and both backups private. Backups are identity-registry backups, **not** full-media backups.
