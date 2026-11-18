# Contributing

Use Python 3.11 or 3.12 and run `python -m pip install -e ".[dev]"` then `python -m unittest discover -s tests -v`, `python -m ruff format --check .`, `python -m ruff check .` and `python -m mypy src/taiyou_manga`. Add synthetic malicious-input tests for importer changes. Do not add copyrighted manga, credentials or private reports. Keep pull requests focused and include security consequences, migration/rollback plans and actual test evidence. Never introduce real HF mutations without a separately approved storage ADR and write-safety review.
