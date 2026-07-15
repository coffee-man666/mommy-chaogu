# v0.2.0 release checklist

## Required gates

- [ ] `uv sync --frozen --extra dev`
- [ ] `./scripts/quality.sh`
- [ ] `uv run pytest tests/test_db_lifecycle.py -W error::ResourceWarning`
- [ ] `uv run python scripts/smoke_migration.py`
- [ ] `npm audit --audit-level=high` in `web/`
- [ ] `./scripts/smoke_docker.sh` on a Docker-capable host
- [ ] GitHub CI release gate is green on Python 3.12 and 3.13
- [ ] Scheduled network probe status is reviewed separately from deterministic CI

## Release hygiene

- [ ] Package metadata and FastAPI report `0.2.0`
- [ ] `CHANGELOG.md` matches the release tag
- [ ] `.env` and runtime databases are absent from the commit
- [ ] Remote deployments set `MOMMY_API_TOKEN` and explicit CORS origins
- [ ] Database layout migration is checked before upgrading an existing installation
