#!/usr/bin/env python3
"""
Cross-platform local dashboard (Windows & Ubuntu)
Run:  python dashboard.py  (or)  python3 dashboard.py
Then open http://localhost:5000
Optional env:
  DASHBOARD_PORT=8080
  DASHBOARD_TITLE="My Ops Screen"
  DASHBOARD_CONFIG="path/to/dashboard_config.json"
"""
from __future__ import annotations

import os
import time
import json
import math
import socket
import platform
from datetime import datetime
from threading import Lock

from flask import Flask, jsonify, render_template_string
import psutil

try:
    from pythonping import ping as ping_host
except Exception:
    ping_host = None

try:
    import requests
except Exception:
    requests = None

APP_TITLE = os.getenv("DASHBOARD_TITLE", "Local System Dashboard")
CONFIG_PATH = os.getenv("DASHBOARD_CONFIG", "dashboard_config.json")
PORT = int(os.getenv("DASHBOARD_PORT", "5000"))

# --------- Config loading ---------
DEFAULT_CONFIG = {
    "hosts": ["8.8.8.8", "1.1.1.1"],
    "http_checks": [
        {"name":"Router UI","url":"http://192.168.1.1"}
    ]
}

def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            if not isinstance(cfg, dict):
                raise ValueError("Config must be a JSON object")
            return cfg
    except Exception:
        # If missing or invalid, write default next to script for convenience
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, indent=2)
        except Exception:
            pass
        return DEFAULT_CONFIG.copy()

CONFIG = load_config()

# --------- Net throughput sampling (bytes/sec) ---------
_net_lock = Lock()
_last_net = {"ts": None, "bytes_sent": 0, "bytes_recv": 0, "tx_rate": 0.0, "rx_rate": 0.0}

def _sample_net():
    with _net_lock:
        now = time.time()
        counters = psutil.net_io_counters()
        bs, br = counters.bytes_sent, counters.bytes_recv
        if _last_net["ts"] is not None:
            dt = max(1e-6, now - _last_net["ts"])
            _last_net["tx_rate"] = (bs - _last_net["bytes_sent"]) / dt
            _last_net["rx_rate"] = (br - _last_net["bytes_recv"]) / dt
        _last_net["ts"] = now
        _last_net["bytes_sent"] = bs
        _last_net["bytes_recv"] = br

def get_net_rates():
    _sample_net()
    with _net_lock:
        return _last_net["tx_rate"], _last_net["rx_rate"]

# --------- Helpers ---------
def bytes2human(n: float) -> str:
    symbols = ("B", "KB", "MB", "GB", "TB", "PB")
    i = 0
    while n >= 1024.0 and i < len(symbols) - 1:
        n /= 1024.0
        i += 1
    return f"{n:.1f} {symbols[i]}"

def seconds2human(s: float) -> str:
    s = int(s)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)

# --------- Flask app ---------
app = Flask(__name__)

TEMPLATE = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { background: #0f172a; color: #e5e7eb; }
    .card { background: #111827; border: 1px solid #1f2937; border-radius: 14px; }
    .metric { font-size: 1.4rem; font-weight: 600; }
    .muted { color: #9ca3af; }
    .ok { color: #22c55e; }
    .warn { color: #eab308; }
    .bad { color: #ef4444; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
    a { color: #93c5fd; }
    .small { font-size: 0.9rem; }
  </style>
</head>
<body class="container py-4">
  <div class="d-flex justify-content-between align-items-center mb-3">
    <h1 class="h3 m-0">{{ title }}</h1>
    <div class="small muted" id="now"></div>
  </div>

  <div class="grid" id="cards">
    <!-- Cards are injected by JS -->
  </div>

<script>
function h(bytes) {
  if (bytes === null || bytes === undefined) return "-";
  const units = ["B","KB","MB","GB","TB","PB"];
  let i = 0;
  let n = Number(bytes);
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return n.toFixed(1) + " " + units[i];
}
function pct(p) { return (p ?? 0).toFixed(0) + "%"; }
function fmtUptime(secs) {
  let s = Math.floor(secs);
  const d = Math.floor(s / 86400); s -= d*86400;
  const h = Math.floor(s / 3600); s -= h*3600;
  const m = Math.floor(s / 60); s -= m*60;
  const parts = [];
  if (d) parts.push(d + "d");
  if (h) parts.push(h + "h");
  if (m) parts.push(m + "m");
  parts.push(s + "s");
  return parts.join(" ");
}
function badge(ok, warn=false) {
  if (ok) return "ok";
  if (warn) return "warn";
  return "bad";
}

async function refresh() {
  try {
    const r = await fetch("/api/stats");
    const data = await r.json();
    const grid = document.getElementById("cards");
    document.getElementById("now").innerText = new Date(data.now).toLocaleString();

    const items = [];

    // System
    items.push(`
      <div class="card p-3">
        <div class="d-flex justify-content-between">
          <div>
            <div class="muted small">${data.system.platform} • ${data.system.machine}</div>
            <div class="metric mt-1">${data.system.hostname}</div>
          </div>
          <div class="text-end small muted">
            Python ${data.system.python} <br/>
            Uptime ${fmtUptime(data.system.uptime_s)}
          </div>
        </div>
      </div>
    `);

    // CPU / Load
    const load = data.cpu.load ? data.cpu.load.map(x => x.toFixed(2)).join(" | ") : "-";
    items.push(`
      <div class="card p-3">
        <div class="metric">CPU ${pct(data.cpu.total)}</div>
        <div class="small muted">Cores: ${data.cpu.cores} • Load: ${load}</div>
      </div>
    `);

    // Memory
    items.push(`
      <div class="card p-3">
        <div class="metric">Memory ${pct(data.memory.percent)}</div>
        <div class="small muted">${h(data.memory.used)} / ${h(data.memory.total)}</div>
      </div>
    `);

    // Disk (root)
    items.push(`
      <div class="card p-3">
        <div class="metric">Disk ${pct(data.disk.percent)}</div>
        <div class="small muted">${h(data.disk.used)} / ${h(data.disk.total)} (${data.disk.mount})</div>
      </div>
    `);

    // Network
    items.push(`
      <div class="card p-3">
        <div class="metric">Network</div>
        <div class="small muted">Up: ${h(data.net.tx_rate)}/s • Down: ${h(data.net.rx_rate)}/s</div>
        <div class="small muted">Sent: ${h(data.net.bytes_sent)} • Recv: ${h(data.net.bytes_recv)}</div>
      </div>
    `);

    // Temps (if any)
    if (data.temps && data.temps.length) {
      const lines = data.temps.map(t => `<div class="small muted">${t.label}: ${t.current}°C</div>`).join("");
      items.push(`<div class="card p-3"><div class="metric">Temperatures</div>${lines}</div>`);
    }

    // Pings
    if (data.pings && data.pings.length) {
      const rows = data.pings.map(p => `
        <div class="d-flex justify-content-between small">
          <div>${p.host}</div>
          <div class="${badge(p.ok)}">${p.ok ? (p.avg_ms.toFixed(1) + " ms") : "unreachable"}</div>
        </div>`).join("");
      items.push(`<div class="card p-3"><div class="metric">Pings</div>${rows}</div>`);
    }

    // HTTP checks
    if (data.http_checks && data.http_checks.length) {
      const rows = data.http_checks.map(o => `
        <div class="d-flex justify-content-between small">
          <div>${o.name || o.url}</div>
          <div class="${badge(o.ok, o.status>=400 && o.status<500)}">
            ${o.ok ? (o.status + " • " + o.latency_ms.toFixed(0) + " ms") : "down"}
          </div>
        </div>`).join("");
      items.push(`<div class="card p-3"><div class="metric">HTTP</div>${rows}</div>`);
    }

    grid.innerHTML = items.join("");
  } catch (e) {
    console.error(e);
  }
}

setInterval(refresh, 2000);
refresh();
</script>
</body>
</html>
"""

def system_info():
    boot_ts = psutil.boot_time()
    info = {
        "hostname": socket.gethostname(),
        "platform": f"{platform.system()} {platform.release()}",
        "machine": platform.machine(),
        "python": platform.python_version(),
        "uptime_s": max(0, time.time() - boot_ts),
    }
    return info

def cpu_info():
    total = psutil.cpu_percent(interval=0.2)
    cores = psutil.cpu_count(logical=True)
    # Load average not available on Windows
    try:
        load = list(os.getloadavg())
    except (AttributeError, OSError):
        load = None
    return {"total": total, "cores": cores, "load": load}

def mem_info():
    vm = psutil.virtual_memory()
    return {"total": vm.total, "used": vm.used, "percent": vm.percent}

def disk_info():
    # Choose root mount sensibly per OS
    root = "C:\\" if platform.system() == "Windows" else "/"
    du = psutil.disk_usage(root)
    return {"total": du.total, "used": du.used, "percent": du.percent, "mount": root}

def net_info():
    tx_rate, rx_rate = get_net_rates()
    io = psutil.net_io_counters()
    return {
        "tx_rate": tx_rate,
        "rx_rate": rx_rate,
        "bytes_sent": io.bytes_sent,
        "bytes_recv": io.bytes_recv,
    }

def temps_info():
    out = []
    try:
        temps = psutil.sensors_temperatures(fahrenheit=False) or {}
        for name, entries in temps.items():
            for e in entries:
                label = e.label or name
                current = None if e.current is None else round(float(e.current), 1)
                if current is not None:
                    out.append({"label": label, "current": current})
    except Exception:
        pass
    return out

def do_pings(hosts):
    results = []
    for host in hosts[:10]:  # cap to 10
        try:
            if ping_host is None:
                raise RuntimeError("pythonping not installed")
            r = ping_host(host, size=16, count=2, timeout=1)
            ok = r.success()
            avg_ms = r.rtt_avg_ms if hasattr(r, "rtt_avg_ms") else None
            results.append({"host": host, "ok": bool(ok), "avg_ms": float(avg_ms) if avg_ms is not None else None})
        except Exception:
            results.append({"host": host, "ok": False, "avg_ms": None})
    return results

def do_http_checks(items):
    out = []
    for it in items[:10]:
        name = it.get("name") or ""
        url = it.get("url")
        if not url:
            continue
        try:
            if requests is None:
                raise RuntimeError("requests not installed")
            t0 = time.perf_counter()
            resp = requests.get(url, timeout=2)
            dt = (time.perf_counter() - t0) * 1000.0
            out.append({"name": name, "url": url, "ok": True, "status": resp.status_code, "latency_ms": dt})
        except Exception:
            out.append({"name": name, "url": url, "ok": False, "status": None, "latency_ms": None})
    return out

@app.get("/")
def index():
    return render_template_string(TEMPLATE, title=APP_TITLE)

@app.get("/api/stats")
def api_stats():
    cfg = load_config()  # hot-reload config each request
    data = {
        "now": datetime.utcnow().isoformat() + "Z",
        "system": system_info(),
        "cpu": cpu_info(),
        "memory": mem_info(),
        "disk": disk_info(),
        "net": net_info(),
        "temps": temps_info(),
        "pings": do_pings(cfg.get("hosts", [])),
        "http_checks": do_http_checks(cfg.get("http_checks", [])),
        "config": cfg,
    }
    return jsonify(data)

def main():
    # Prime the net sampler
    _sample_net()
    from waitress import serve as waitress_serve  # lightweight prod server, cross-platform
    print(f"Starting dashboard on port {PORT} ...")
    try:
        waitress_serve(app, host="0.0.0.0", port=PORT)
    except Exception as e:
        # Fallback to Flask dev server if waitress missing
        print("Waitress not available, using Flask dev server:", e)
        app.run(host="0.0.0.0", port=PORT, debug=False)

if __name__ == "__main__":
    main()
