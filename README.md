# Web-Defect-Detection-System

FastAPI backend plus Qt WASM web client for defect detection workflows. Follow `AGENTS.md` for coding rules; this README documents Docker-based deployment for Windows dev + Linux prod.

## Submodules

```bash
git submodule update --init --recursive
```

## Local development (Windows)

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python app/server/main.py --config configs/server.json --reload --host 0.0.0.0 --port 8120
```

## Docker workflow

1. Prepare `configs/server.json` with DB + image paths.
2. Build Qt WASM output to `app/ui/DefectWebUi/build/WebAssembly_Qt_6_10_0_multi_threaded-MinSizeRel`.
3. Build the container: `docker build -t defect-api .`
4. Run locally: `docker run -d --name defect-api -p 8120:8120 -v %CD%\configs\server.json:/config/server.json -e SERVER_CONFIG_PATH=/config/server.json defect-api`

## docker-compose

`docker-compose.yml` wires config/UI volumes plus env vars. Example:

```bash
DEFECT_API_PORT=8120 \
CORS_ALLOW_ORIGINS=http://localhost:3000 \
docker compose up -d --build
```

Mount your real config + image shares by editing the compose volumes section. Set `DEFECT_SSL_CERT`/`DEFECT_SSL_KEY` when HTTPS is required.

## deploy.sh

`deploy.sh` automates pull/build/restart on Linux hosts:

```bash
ssh user@server 'DEPLOY_BRANCH=main REPO_DIR=/opt/defect-api bash /opt/defect-api/deploy.sh'
```

The script runs `git fetch`, keeps submodules in sync, rebuilds the container, and restarts the compose service.
