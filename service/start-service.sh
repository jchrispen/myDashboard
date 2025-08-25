#!/usr/bin/env bash
set -euo pipefail

echo ">>> Enabling dashboard services..."
sudo systemctl enable --now dashboard.service
sudo systemctl enable --now dashboard-restart.timer
