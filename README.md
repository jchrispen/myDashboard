# Local System Dashboard (Windows, Ubuntu & Docker)

A tiny cross-platform dashboard you can run on your PC, a home server, or in a container.
- Web UI served at the port you choose (`http://localhost:5000` by default, or as set in `dashboard_config.json`)
- Shows CPU, memory, disk, network throughput, temps (if available), host pings, and simple HTTP checks
- Zero external services needed
- Can be run natively (Python) or containerized (Docker, with systemd/compose support)

---

## Quick Start (Native)

### 1) Install Python 3.10+
- **Windows**: Install from the Microsoft Store or python.org (check "Add Python to PATH").
- **Ubuntu**:
  ```bash
  sudo apt update && sudo apt install -y python3 python3-pip
````

### 2) Create a venv (recommended)

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Ubuntu
source .venv/bin/activate
```

### 3) Install dependencies

```bash
pip install -r requirements.txt
```

### 4) Configure

Edit `dashboard_config.json` to set:

* Port/host binding (e.g. `0.0.0.0` for LAN access)
* Hosts to ping
* HTTP URLs to check

The app hot-reloads the config on each refresh.

### 5) Run it

```bash
python dashboard.py
```

Then open your browser to `http://localhost:5000` (or the configured port).
If you installed `waitress`, the app uses it automatically; otherwise it falls back to Flask's server.

---

## Quick Start (Docker)

### Build

```bash
docker build \
  --build-arg LOCAL_CFG_FILE=dashboard_config.json \
  -t mydashboard:dev .
```

### Run (host network mode, uses port from `dashboard_config.json`)

```bash
docker run -d --name dashboard \
  --network host \
  -e DASHBOARD_BRANCH=dev \
  -v /path/to/dashboard_config.json:/config/dashboard_config.json:ro \
  mydashboard:dev
```

Or with **docker-compose** (`/opt/dashboard/docker-compose.yml`):

```yaml
services:
  dashboard:
    image: mydashboard:dev
    container_name: dashboard
    network_mode: host
    environment:
      - DASHBOARD_BRANCH=dev
    volumes:
      - /path/to/dashboard_config.json:/config/dashboard_config.json:ro
    restart: unless-stopped
```

```bash
docker compose up -d
```

### systemd integration (optional)

Unit files are provided under `/opt/dashboard/service/`:

* `dashboard.service` → runs the container at boot
* `dashboard-restart.timer` + `dashboard-restart.service` → daily restart (auto `git pull` from `dev` branch)

Symlink them into `/etc/systemd/system/` and enable as needed:

```bash
sudo systemctl enable dashboard.service
sudo systemctl enable dashboard-restart.timer
```

---

## Notes

* **Temperatures** require sensors support; not all systems expose them (especially on Windows).
* Network throughput is computed between refreshes.
* Pings use ICMP via `pythonping`. If your OS/firewall blocks ICMP, pings may show as unreachable.
* For LAN dashboards, bind to `0.0.0.0` and consider giving the machine a static IP.
* With Docker host networking, make sure your `dashboard_config.json` specifies a reachable host (not `127.0.0.1`).

