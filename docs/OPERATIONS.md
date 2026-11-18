# Windows operation guide

Use PowerShell from the repository directory, with your activated virtual environment:

```powershell
python -m taiyou_manga menu
python -m taiyou_manga scan --source "C:\Manga\AuthorisedSource"
python -m taiyou_manga manifest --source "C:\Manga\AuthorisedSource" --output "bundles\first" --state-file ".manga-controller\ids.json"
python -m taiyou_manga verify --bundle "bundles\first"
python -m taiyou_manga plan-upload --bundle "bundles\first" --mock-dir "mock_remote"
python -m taiyou_manga backup --bundle "bundles\first" --output "backups\first.zip"
python -m taiyou_manga restore --backup "backups\first.zip" --destination "bundles\recovered"
```

The interactive menu supports fixtures, scanning, manifests, verification, inventory, mock preview and backups. The non-interactive CLI also supports local mock commit and approved local restore. Exit status 0 means success; 2 means blocked or invalid input. Do not move your controller `ids.json` into a public repository. The default CLI output prints opaque IDs and safe aggregate counts, not source titles. Do not share it without reviewing privacy implications.
