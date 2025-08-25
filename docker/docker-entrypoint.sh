#!/usr/bin/env bash
set -euo pipefail

cd "${APP_DIR}"

echo ">>> Updating repo (${DASHBOARD_BRANCH:-dev} branch)..."
git fetch origin "${DASHBOARD_BRANCH:-dev}"
git reset --hard "origin/${DASHBOARD_BRANCH:-dev}"

# Ensure destination exists; adjust path if your repo layout differs
mkdir -p "${APP_DIR}/app"
rm -f "${APP_DIR}/app/dashboard_config.json"
ln -s "${CFG_DIR}/dashboard_config.json" "${APP_DIR}/app/dashboard_config.json"

echo ">>> Starting dashboard..."
cd "${APP_DIR}/app"
exec python dashboard.py
