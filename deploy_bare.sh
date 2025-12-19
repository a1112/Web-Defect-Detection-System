#!/usr/bin/env bash

set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
BRANCH="${DEPLOY_BRANCH:-main}"
VENV_DIR="${DEPLOY_VENV_DIR:-${REPO_DIR}/.venv}"
PYTHON_BIN="${DEPLOY_PYTHON_BIN:-python3}"
SERVICES="${DEPLOY_SYSTEMD_SERVICES:-}"
USE_SUDO="${DEPLOY_USE_SUDO:-false}"

echo "[deploy] (bare) repo directory: ${REPO_DIR}"
cd "${REPO_DIR}"

echo "[deploy] fetching latest code..."
git fetch --all --prune
git checkout "${BRANCH}"
git pull --ff-only origin "${BRANCH}"
git submodule update --init --recursive

echo "[deploy] ensuring venv: ${VENV_DIR}"
if [ ! -d "${VENV_DIR}" ]; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

echo "[deploy] installing dependencies..."
"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/pip" install -r requirements.txt

if [ -z "${SERVICES}" ]; then
  echo "[error] DEPLOY_SYSTEMD_SERVICES is not set (e.g. 'defect-api-2d defect-api-small')"
  exit 1
fi

echo "[deploy] restarting systemd services: ${SERVICES}"
systemctl_cmd="systemctl"
if [ "${USE_SUDO}" = "true" ] || [ "${USE_SUDO}" = "1" ]; then
  systemctl_cmd="sudo systemctl"
fi

for service in ${SERVICES}; do
  ${systemctl_cmd} restart "${service}"
done

echo "[deploy] done."

