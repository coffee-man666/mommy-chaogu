# v1.2.0 release checklist

## Required gates

- [x] `uv sync --frozen --extra dev`
- [x] `./scripts/quality.sh`
- [x] `uv run pytest tests/test_db_lifecycle.py -W error::ResourceWarning`
- [x] `uv run python scripts/smoke_migration.py`
- [x] `npm audit --audit-level=high` in `web/`
- [x] Docker build + health/permissions smoke（GitHub CI；当前机器未安装 Docker）
- [x] GitHub CI release gate is green on Python 3.12 and 3.13（merge run `30420741759`）
- [x] Scheduled network probe status reviewed separately; current branch 13 probes also pass

## Release hygiene

- [x] Package metadata and FastAPI report `1.2.0`
- [x] `CHANGELOG.md` includes the `1.2.0` release notes
- [x] `.env` and runtime databases are absent from the commit
- [ ] Remote deployments set `MOMMY_API_TOKEN` and explicit CORS origins
- [ ] SQLite deployments mount persistent storage at `/app/data`
- [ ] Railway volume deployments set `RAILWAY_RUN_UID=0` and verify the app drops to UID 1000
- [ ] Database layout migration is checked before upgrading an existing installation
