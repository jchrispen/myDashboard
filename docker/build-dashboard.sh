#!/usr/bin/env bash
set -euo pipefail

# usage: ./build-dashboard.sh /path/to/dashboard_config.json

if [ $# -ne 1 ]; then
  echo "Usage: $0 <config-file>"
  exit 1
fi

CFG_FILE="$1"

if [ ! -f "$CFG_FILE" ]; then
  echo "ERROR: Config file '$CFG_FILE' not found."
  exit 1
fi

# Get the filename relative to build context
CFG_BASENAME=$(basename "$CFG_FILE")

# Copy config file into build context (if not already there)
cp "$CFG_FILE" "./$CFG_BASENAME"

echo ">>> Building dashboard image with config '$CFG_BASENAME'..."
docker build \
  --build-arg LOCAL_CFG_FILE="$CFG_BASENAME" \
  -t mydashboard:dev .

echo ">>> Done. Image tagged as 'mydashboard:dev'."
docker images
