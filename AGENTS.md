# Repository Guidelines

## Project Structure & Module Organization
- `app/server`: FastAPI backend (`main.py`, services, utils) plus config helpers under `config/settings.py`.
- `configs`: JSON configs (`server.json`, `server.sample.json`) loaded via `SERVER_CONFIG_PATH` when present.
- `app/ui/DefectWebUi`: Qt/QML client; WASM build output served from `app/ui/DefectWebUi/build/...`.
- `link_project`: Git submodules for database helpers and Figma assets; keep in sync after clone with `git submodule update --init --recursive`.
- `logs`, `demo`, `work`: runtime artifacts and samples; avoid checking in large generated files.

## Build, Test, and Development Commands
- Install deps: `python -m venv .venv && .venv\\Scripts\\activate && pip install -r requirements.txt`.
- Run API (HTTP): `python app/server/main.py --config configs/server.json --reload --host 0.0.0.0 --port 8120`.
- Run API with TLS: add `--ssl-certfile path/to/cert.pem --ssl-keyfile path/to/key.pem` or set `DEFECT_SSL_CERT`/`DEFECT_SSL_KEY`.
- Serve UI: ensure Qt WASM build lands in `app/ui/DefectWebUi/build/WebAssembly_Qt_6_10_0_multi_threaded-MinSizeRel`; backend serves `/` and `/ui` automatically.
- Quick health check: `curl http://localhost:8120/health`.

## Coding Style & Naming Conventions
- Python: follow PEP 8, 4-space indent, type hints as in existing services; prefer `logging` over `print`.
- APIs: path params are snake_case (`seq_no`, `steel_id`); keep response models in `schemas.py`.
- Config: use uppercase env keys (`SERVER_CONFIG_PATH`, `DEFECT_UI_BUILD_DIR`, `CORS_ALLOW_ORIGINS`) and avoid hard-coding secrets in code.
- QML/Qt: mirror existing file layout; PascalCase component files, camelCase ids/properties, keep imports grouped.

## Testing Guidelines
- No formal test suite yet; when adding tests, use `pytest` with `fastapi.testclient` and place files under `app/server/tests`.
- For manual validation: hit `/health`, query `/api/steels?limit=5`, and fetch a defect sample via `/api/defects/{seq_no}`; watch logs for DB/IO errors.
- Keep sample configs sanitized; avoid committing real credentials or image paths.

## Commit & Pull Request Guidelines
- Commits: short, imperative summaries (e.g., `add wasm ui build mount`, `fix defect pagination`); group related changes.
- PRs: include what changed, how to run/verify (commands above), and note config or schema impacts. Attach screenshots/gifs for UI-visible work.
- Link issues or tasks when available and mention if submodules/config files need updating after merge.

## Security & Configuration Tips
- Prefer storing credentials in `configs/server.json` ignored from VCS; share sanitized `server.sample.json` updates when schema changes.
- Set `CORS_ALLOW_ORIGINS` for production hosts; enable TLS via envs above when exposing publicly.
- Image roots (`top_root`, `bottom_root`) should point to network shares with read permissions only; avoid embedding UNC paths in code.
