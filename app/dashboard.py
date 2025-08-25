#!/usr/bin/env python3
"""
Cross-platform local dashboard (Windows & Ubuntu)
Run:  python dashboard.py  (or)  python3 dashboard.py
Then open http://localhost:5000  (or the port you set)

Config file (JSON) supports:
{
  "server": { "port": 8080, "title": "My Ops Screen" },
  "hosts": ["8.8.8.8", "1.1.1.1"],
  "http_checks": [
    { "name": "Router UI", "url": "https://192.168.1.1", "verify": false }
  ]
}
"""
from __future__ import annotations

import os
import time
import json
import socket
import platform
from datetime import datetime
from threading import Lock
from pathlib import Path

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

# --------- Config & settings (cross-platform) ---------
# Default: dashboard_config.json next to this script; override with env var
CONFIG_PATH = os.getenv(
    "DASHBOARD_CONFIG",
    str(Path(__file__).with_name("dashboard_config.json"))
)

DEFAULT_CONFIG = {
    "server": {"port": 5000, "title": "Local System Dashboard"},
    "hosts": ["8.8.8.8", "1.1.1.1"],
    "http_checks": [
        {"name": "Router UI", "url": "http://192.168.1.1"}
    ]
}

def load_config() -> dict:
    """Load JSON config; create a default file if missing/invalid."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            if not isinstance(cfg, dict):
                raise ValueError("Config must be a JSON object")
            return cfg
    except Exception:
        # Best-effort write default to the intended location
        try:
            Path(CONFIG_PATH).parent.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, indent=2)
        except Exception:
            pass
        return DEFAULT_CONFIG.copy()

def effective_settings(cfg: dict) -> dict:
    """Resolve title/port with precedence: config > env > defaults."""
    server_cfg = (cfg or {}).get("server", {}) if isinstance(cfg, dict) else {}
    title = server_cfg.get("title") or DEFAULT_CONFIG["server"]["title"]
    port = int(server_cfg.get("port"), DEFAULT_CONFIG["server"]["port"])
    return {"title": title, "port": port}

# --------- External IP (cached) ---------
_ext_cache = {"ts": 0.0, "data": None}

def external_ip_info(ttl_seconds: int = 300):
    """
    Try several providers, return {'ip': 'x.x.x.x', 'source': 'url', 'latency_ms': float}
    Cache result for ttl_seconds. Returns None on failure.
    """
    if requests is None:
        return None

    now = time.time()
    if _ext_cache["data"] and (now - _ext_cache["ts"] < ttl_seconds):
        return _ext_cache["data"]

    providers = [
        ("https://api.ipify.org", {}),
        ("https://ifconfig.me/ip", {}),
        ("https://checkip.amazonaws.com", {}),
    ]

    for url, kwargs in providers:
        try:
            t0 = time.perf_counter()
            r = requests.get(url, timeout=2, **kwargs)
            dt = (time.perf_counter() - t0) * 1000.0
            if r.ok and r.text:
                ip = r.text.strip()
                # very light sanity check (IPv4/IPv6 chars)
                if all(c.isdigit() or c in ".:abcdefABCDEF" for c in ip):
                    data = {"ip": ip, "source": url, "latency_ms": dt}
                    _ext_cache["ts"] = now
                    _ext_cache["data"] = data
                    return data
        except Exception:
            continue

    # give up for now
    _ext_cache["ts"] = now
    _ext_cache["data"] = None
    return None

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
    .metric { font-size: 1.4rem; font-weight: 600; color: #38bdf8; /* sky-400 */ }
    .muted { color: #9ca3af; }
    .ok { color: #22c55e; }
    .warn { color: #eab308; }
    .bad { color: #ef4444; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
    .external-ip { color: #ffffff; font-weight: 600; font-size: 1.05rem; }
    a { color: #93c5fd; }
    .small { font-size: 0.9rem; }
    .host-label { color: #ffffff;   /* bright white for good contrast */ font-weight: 500; /* medium bold so they stand out */ }
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
            <div class="external-ip">${data.system.hostname}</div>
          </div>
          <div class="text-end small muted">
            Python ${data.system.python} <br/>
            Uptime ${fmtUptime(data.system.uptime_s)}
          </div>
        </div>
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

    // External IP
    if (data.external_ip) {
      const src = data.external_ip.source ? new URL(data.external_ip.source).hostname : "";
      const latency = data.external_ip.latency_ms ? ` • ${data.external_ip.latency_ms.toFixed(0)} ms` : "";
      items.push(`
        <div class="card p-3">
          <div class="metric">External IP</div>
          <div class="external-ip">${data.external_ip.ip}</div>
          <div class="small muted">via ${src}${latency}</div>
        </div>
      `);
    } else {
      items.push(`
        <div class="card p-3">
          <div class="metric">External IP</div>
          <div class="small muted">unavailable</div>
        </div>
      `);
    }

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

    // Temps (if any)
    if (data.temps && data.temps.length) {
      const lines = data.temps.map(t => `<div class="small muted">${t.label}: ${t.current}°C</div>`).join("");
      items.push(`<div class="card p-3"><div class="metric">Temperatures</div>${lines}</div>`);
    }

    // Pings
    if (data.pings && data.pings.length) {
      const rows = data.pings.map(p => `
        <div class="d-flex justify-content-between small">
          <div class="host-label">${p.host}</div>
          <div class="${badge(p.ok)}">${p.ok ? (p.avg_ms.toFixed(1) + " ms") : "unreachable"}</div>
        </div>`).join("");
      items.push(`<div class="card p-3"><div class="metric">Pings</div>${rows}</div>`);
    }

    // HTTP checks
    if (data.http_checks && data.http_checks.length) {
      const rows = data.http_checks.map(o => `
        <div class="d-flex justify-content-between small">
          <div class="host-label">${o.name || o.url}</div>
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

# --------- System probes ---------
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
    root = "C:\\" if os.name == "nt" else "/"
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
    for host in (hosts or [])[:10]:  # cap to 10
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

def http_checks_with_verify(items):
    out = []
    for it in (items or [])[:10]:
        name = it.get("name") or ""
        url = it.get("url")
        if not url:
            continue
        verify = it.get("verify", True)  # set false for self-signed HTTPS
        try:
            if requests is None:
                raise RuntimeError("requests not installed")
            t0 = time.perf_counter()
            resp = requests.get(url, timeout=2, verify=verify)
            dt = (time.perf_counter() - t0) * 1000.0
            out.append({"name": name, "url": url, "ok": True, "status": resp.status_code, "latency_ms": dt})
        except Exception:
            out.append({"name": name, "url": url, "ok": False, "status": None, "latency_ms": None})
    return out

# --------- Routes ---------
@app.get("/")
def index():
    cfg = load_config()
    settings = effective_settings(cfg)
    return render_template_string(TEMPLATE, title=settings["title"])

@app.get("/api/stats")
def api_stats():
    cfg = load_config()  # hot reload on each request
    settings = effective_settings(cfg)
    data = {
        "now": datetime.utcnow().isoformat() + "Z",
        "system": system_info(),
        "cpu": cpu_info(),
        "memory": mem_info(),
        "disk": disk_info(),
        "net": net_info(),
        "temps": temps_info(),
        "pings": do_pings(cfg.get("hosts", [])),
        "http_checks": http_checks_with_verify(cfg.get("http_checks", [])),
        "external_ip": external_ip_info(),
        "settings": settings,
        "config_path": CONFIG_PATH,
    }
    return jsonify(data)

# --------- Entrypoint ---------
def main():
    _sample_net()  # prime net sampler
    cfg = load_config()
    settings = effective_settings(cfg)
    host = settings["host"]
    port = settings["port"]

    try:
        from waitress import serve as waitress_serve  # lightweight prod server
        print(f"Starting dashboard on port {port} (config: {CONFIG_PATH}) ...")
        waitress_serve(app, host=host, port=port)
    except Exception as e:
        # Fallback to Flask dev server if waitress not available
        print("Waitress not available, using Flask dev server:", e)
        app.run(host=host, port=port, debug=False)

if __name__ == "__main__":
    main()
