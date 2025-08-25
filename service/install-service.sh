#!/usr/bin/env bash
set -euo pipefail

# This shold be run on the host that will run the dashboard container

# Source dir for your custom units
APP_DIR="/opt/dashboard"
SRC_DIR="${APP_DIR}/service"
# Target systemd unit dir
DST_DIR="/etc/systemd/system"

# List of unit files to link
UNITS=(
  "dashboard.service"
  "dashboard-restart.service"
  "dashboard-restart.timer"
)

# Create config dir
mkdir -p "${APP_DIR}/config"

echo ">>> Creating symlinks for dashboard units..."
for unit in "${UNITS[@]}"; do
  src="${SRC_DIR}/${unit}"
  dst="${DST_DIR}/${unit}"

  if [ ! -f "$src" ]; then
    echo "WARNING: $src does not exist, skipping"
    continue
  fi

  # Remove existing file/link if present
  if [ -e "$dst" ] || [ -L "$dst" ]; then
    echo "Removing old $dst"
    sudo rm -f "$dst"
  fi

  echo "Linking $src -> $dst"
  sudo ln -s "$src" "$dst"
done

# Enable the dashboard
echo ">>> Reloading systemd units..."
sudo systemctl daemon-reload
