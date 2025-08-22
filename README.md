# Local System Dashboard (Windows & Ubuntu)

A tiny cross-platform dashboard you can run on your PC or a home server.
- Web UI at `http://localhost:5000` (or your chosen port)
- Shows CPU, memory, disk, network throughput, temps (if available), host pings, and simple HTTP checks
- Zero external services needed

## Quick Start

### 1) Install Python 3.10+
- **Windows**: Install from the Microsoft Store or python.org (check "Add Python to PATH").
- **Ubuntu**: `sudo apt update && sudo apt install -y python3 python3-pip`

### 2) Create a venv (recommended)
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Ubuntu
source .venv/bin/activate
```

### 3) Install deps
```bash
pip install -r requirements.txt
```

### 4) Configure (optional)
Edit `dashboard_config.json` to set hosts to ping and HTTP URLs to check. The app hot‑reloads the config on each refresh.

### 5) Run it
```bash
# default port 5000
python dashboard.py

# customizations
set DASHBOARD_PORT=8080                 # Windows (cmd)
$env:DASHBOARD_PORT=8080                # Windows (PowerShell)
export DASHBOARD_PORT=8080              # Ubuntu

set DASHBOARD_TITLE="Jason's Ops"       # Windows (cmd)
$env:DASHBOARD_TITLE="Jason's Ops"      # Windows (PowerShell)
export DASHBOARD_TITLE="Jason's Ops"    # Ubuntu

export DASHBOARD_CONFIG="/path/to/dashboard_config.json"
```

Open your browser to `http://localhost:5000`.
If you installed `waitress`, the app uses it automatically; otherwise it falls back to Flask's server.

## Notes
- **Temperatures** require sensors support; not all systems expose them (especially on Windows).
- Network throughput is computed between refreshes.
- Pings use ICMP via `pythonping`. If your OS/firewall blocks ICMP, pings may show as unreachable.
- For LAN dashboards, consider pinning the machine to a static IP so you can visit `http://<ip>:5000` from other devices on your network.
