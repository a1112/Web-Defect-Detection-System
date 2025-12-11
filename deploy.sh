#!/usr/bin/env bash

set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
BRANCH="${DEPLOY_BRANCH:-main}"
SERVICE="${DEPLOY_SERVICE:-defect-api}"

echo "[deploy] using repo directory: ${REPO_DIR}"
cd "${REPO_DIR}"

echo "[deploy] fetching latest code..."
git fetch --all --prune
git checkout "${BRANCH}"
git pull --ff-only origin "${BRANCH}"
git submodule update --init --recursive

echo "[deploy] building docker image..."
docker compose build "${SERVICE}"

echo "[deploy] restarting service..."
docker compose up -d "${SERVICE}"

echo "[deploy] cleanup dangling artifacts..."
docker image prune -f >/dev/null 2>&1 || true

echo "[deploy] done."
