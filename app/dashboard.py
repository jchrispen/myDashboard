#!/usr/bin/env python3
import re
import os
import time
import json
import socket
import platform
import logging
from datetime import datetime, UTC
from threading import Lock, Thread
from pathlib import Path

from flask import Flask, jsonify, render_template, request
import psutil

# Optional imports
try:
    from pythonping import ping as ping_host
except Exception:
    ping_host = None

try:
    import requests
except Exception:
    requests = None

try:
    import speedtest as speedtest_lib  # pip install speedtest-cli
except Exception:
    speedtest_lib = None

# --------- Logging setup ---------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# --------- Config & settings ---------
CONFIG_PATH = os.getenv(
    "DASHBOARD_CONFIG",
    str(Path(__file__).with_name("dashboard_config.json"))
)

DEFAULT_CONFIG = {
    "server": {"port": 5000, "title": "Local System Dashboard", "host": "0.0.0.0"},
    "hosts": ["8.8.8.8", "1.1.1.1"],
    "http_checks": [
        {"name": "Router UI", "url": "http://192.168.1.1"}
    ]
}

DEFAULT_CONFIG.update({
    "speedtest": {
        "enabled": True,               # turn background runs on/off
        "interval_minutes": 30,        # how often to run when healthy
        "run_at_startup": True,        # kick off one soon after boot
        "start_delay_sec": 5,          # wait this many seconds after boot
        "backoff_minutes_on_error": 10 # if a run fails, try again later
    }
})

def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            if not isinstance(cfg, dict):
                raise ValueError("Config must be a JSON object")
            return cfg
    except Exception as e:
        logging.warning(f"Failed to load config: {e}")
        try:
            Path(CONFIG_PATH).parent.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, indent=2)
        except Exception as e:
            logging.error(f"Failed to write default config: {e}")
        return DEFAULT_CONFIG.copy()

def effective_settings(cfg: dict) -> dict:
    server_cfg = (cfg or {}).get("server", {}) if isinstance(cfg, dict) else {}
    title = server_cfg.get("title") or DEFAULT_CONFIG["server"]["title"]
    port_val = server_cfg.get("port", DEFAULT_CONFIG["server"]["port"])
    try:
        port = int(port_val)
    except (TypeError, ValueError):
        port = DEFAULT_CONFIG["server"]["port"]
    host = server_cfg.get("host", "0.0.0.0")
    return {"title": title, "port": port, "host": host}

# --------- Caching & Networking ---------
_ext_cache = {"ts": 0.0, "data": None}
_net_lock = Lock()
_last_net = {"ts": None, "bytes_sent": 0, "bytes_recv": 0, "tx_rate": 0.0, "rx_rate": 0.0}

def external_ip_info(ttl_seconds: int = 300):
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
                if all(c.isdigit() or c in ".:abcdefABCDEF" for c in ip):
                    data = {"ip": ip, "source": url, "latency_ms": dt}
                    _ext_cache["ts"] = now
                    _ext_cache["data"] = data
                    return data
        except Exception:
            continue
    _ext_cache["ts"] = now
    _ext_cache["data"] = None
    return None

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

# --------- System Info ---------
def system_info():
    boot_ts = psutil.boot_time()
    return {
        "hostname": socket.gethostname(),
        "platform": f"{platform.system()} {platform.release()}",
        "machine": platform.machine(),
        "python": platform.python_version(),
        "uptime_s": max(0, time.time() - boot_ts),
    }

def cpu_info():
    total = psutil.cpu_percent(interval=0.2)
    cores = psutil.cpu_count(logical=True)
    try:
        load = list(os.getloadavg())
    except (AttributeError, OSError):
        load = None
    return {"total": total, "cores": cores, "load": load}

def mem_info():
    vm = psutil.virtual_memory()
    return {"total": vm.total, "used": vm.used, "percent": vm.percent}

def disk_info():
    root = "C:\\" if os.name == "nt" else "/"
    du = psutil.disk_usage(root)
    return {"total": du.total, "used": du.used, "percent": du.percent, "mount": root}

def simplify_iface_name(name: str) -> str:
    if "Loopback" in name:
        return "Loopback"
    elif name.startswith("Wi-Fi"):
        return "WiFi"
    elif name.startswith("Ethernet"):
        return name
    elif name.startswith("Local Area Connection"):
        match = re.search(r'\d+', name)
        return f"LAC {match.group()}" if match else "LAC"
    elif name.startswith("vEthernet (Default Switch)"):
        return "vSwitch: Default"
    elif "WSL" in name:
        return "vSwitch: WSL"
    else:
        return name

def net_info():
    tx_rate, rx_rate = get_net_rates()
    io = psutil.net_io_counters()

    interfaces = {}
    try:
        for name, addrs in psutil.net_if_addrs().items():
            ipv4_list = []
            for a in addrs:
                if a.family == socket.AF_INET and not a.address.startswith("169.254."):
                    ipv4_list.append(a.address)
            if ipv4_list:
                friendly = simplify_iface_name(name)
                interfaces[friendly] = ipv4_list
    except Exception as e:
        logging.warning("Failed to retrieve interface IPs: %s", e)

    return {
        "tx_rate": tx_rate,
        "rx_rate": rx_rate,
        "bytes_sent": io.bytes_sent,
        "bytes_recv": io.bytes_recv,
        "interfaces": interfaces
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
    for host in (hosts or [])[:10]:
        try:
            if ping_host is None:
                raise RuntimeError("pythonping not installed")
            r = ping_host(host, size=16, count=2, timeout=1)
            ok = r.success()
            avg_ms = r.rtt_avg_ms if hasattr(r, "rtt_avg_ms") else None
            try:
                resolved = socket.gethostbyaddr(host)[0]
            except Exception:
                resolved = host
            results.append({
                "host": host, "resolved": resolved, "ok": bool(ok),
                "avg_ms": float(avg_ms) if avg_ms is not None else None
            })
        except Exception:
            results.append({"host": host, "resolved": host, "ok": False, "avg_ms": None})
    return results

def http_checks_with_verify(items):
    out = []
    for it in (items or [])[:10]:
        name = it.get("name") or ""
        url = it.get("url")
        if not url:
            continue
        verify = it.get("verify", True)
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

# --------- Speedtest state & worker ---------
_speed_lock = Lock()
_speed_state = {
    "running": False,
    "started_ts": None,
    "result": None,     # dict with download_bps, upload_bps, ping_ms, server
    "error": None
}

_sched_lock = Lock()
_sched_state = {
    "enabled": False,
    "interval_s": 1800,
    "last_run_ts": None,   # epoch seconds
    "next_run_ts": None,   # epoch seconds
    "run_count": 0,
    "last_error": None,
}

def _speedtest_cfg_from(cfg: dict):
    st = (cfg or {}).get("speedtest", {}) or {}
    enabled = bool(st.get("enabled", True))
    interval_minutes = int(st.get("interval_minutes", 30))
    interval_s = max(60, interval_minutes * 60)
    run_at_startup = bool(st.get("run_at_startup", True))
    start_delay_sec = int(st.get("start_delay_sec", 5))
    backoff_minutes = int(st.get("backoff_minutes_on_error", 10))
    backoff_s = max(60, backoff_minutes * 60)
    return enabled, interval_s, run_at_startup, start_delay_sec, backoff_s

def _speedtest_scheduler():
    """Background loop that runs speed tests on a schedule."""
    # Defer a moment so waitress/flask can initialize cleanly
    time.sleep(0.5)

    # Seed next_run based on config
    while True:
        try:
            cfg = load_config()
            enabled, interval_s, run_at_startup, start_delay, backoff_s = _speedtest_cfg_from(cfg)
            now = time.time()

            with _sched_lock:
                _sched_state["enabled"] = enabled
                _sched_state["interval_s"] = interval_s

            if not enabled:
                with _sched_lock:
                    _sched_state["next_run_ts"] = None
                time.sleep(2)
                continue

            # Figure out last and next timestamps
            with _speed_lock:
                running = _speed_state["running"]
                last_res = _speed_state.get("result") or {}
                last_err = _speed_state.get("error")

            last_ts = last_res.get("finished_ts") or _sched_state.get("last_run_ts")

            if running:
                # Conservative next-run estimate while one is in-flight
                with _sched_lock:
                    if last_ts:
                        _sched_state["next_run_ts"] = last_ts + interval_s
                time.sleep(2)
                continue

            # Decide if we're due
            if last_ts is None:
                # First run since boot
                due_ts = now + max(0, start_delay) if run_at_startup else now + interval_s
            else:
                due_ts = last_ts + interval_s

            with _sched_lock:
                _sched_state["next_run_ts"] = due_ts

            if now < due_ts:
                # Sleep until (roughly) due
                time.sleep(min(2, max(0.2, due_ts - now)))
                continue

            # Run a test (synchronously in this thread to keep logic simple)
            with _speed_lock:
                if _speed_state["running"]:
                    time.sleep(2)
                    continue

            _run_speedtest()

            # Inspect outcome and set next run
            with _speed_lock:
                err = _speed_state.get("error")

            now = time.time()
            with _sched_lock:
                _sched_state["last_run_ts"] = now
                _sched_state["run_count"] += 1
                _sched_state["last_error"] = err
                _sched_state["next_run_ts"] = now + (backoff_s if err else interval_s)

            time.sleep(1)

        except Exception as e:
            logging.exception("Speedtest scheduler error: %s", e)
            time.sleep(5)

def _run_speedtest():
    with _speed_lock:
        _speed_state.update(running=True, started_ts=time.time(), result=None, error=None)
    try:
        if speedtest_lib is None:
            raise RuntimeError("speedtest-cli not installed. Run: pip install speedtest-cli")
        st = speedtest_lib.Speedtest(secure=True)
        st.get_servers([])
        best = st.get_best_server()
        # Download/Upload return bits per second
        download_bps = st.download(threads=None)
        upload_bps = st.upload(threads=None)
        ping_ms = st.results.ping
        server = {
            "sponsor": best.get("sponsor"),
            "name": best.get("name"),
            "country": best.get("country")
        }
        result = {
            "download_bps": float(download_bps),
            "upload_bps": float(upload_bps),
            "ping_ms": float(ping_ms) if ping_ms is not None else None,
            "server": server,
            "finished_ts": time.time()
        }
        with _speed_lock:
            _speed_state.update(running=False, result=result, error=None)
    except Exception as e:
        logging.warning("Speedtest failed: %s", e)
        with _speed_lock:
            _speed_state.update(running=False, error=str(e), result=None)

# --------- Flask App ---------
app = Flask(__name__)

@app.get("/")
def index():
    cfg = load_config()
    settings = effective_settings(cfg)
    return render_template("dashboard.html", title=settings["title"])

@app.get("/api/stats")
def api_stats():
    cfg = load_config()
    settings = effective_settings(cfg)
    data = {
        "now": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
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

@app.post("/api/reload")
def reload_config():
    global _ext_cache
    _ext_cache = {"ts": 0.0, "data": None}
    logging.info("Configuration reloaded via API.")
    return jsonify({"status": "ok", "message": "Configuration reloaded."})

# ---- Speedtest endpoints ----
@app.post("/api/speedtest/start")
def speedtest_start():
    with _speed_lock:
        if _speed_state["running"]:
            return jsonify({"status": "already-running"}), 200
        _speed_state.update(running=True, started_ts=time.time(), result=None, error=None)
    t = Thread(target=_run_speedtest, daemon=True)
    t.start()
    return jsonify({"status": "started"}), 202

@app.get("/api/speedtest/status")
def speedtest_status():
    with _speed_lock:
        payload = dict(_speed_state)
    with _sched_lock:
        payload["schedule"] = {
            "enabled": _sched_state["enabled"],
            "interval_minutes": int(round(_sched_state["interval_s"] / 60)),
            "last_run_ts": _sched_state["last_run_ts"],
            "next_run_ts": _sched_state["next_run_ts"],
            "run_count": _sched_state["run_count"],
            "last_error": _sched_state["last_error"],
        }
    return jsonify(payload)

# --------- Entrypoint ---------
def main():
    _sample_net()
    cfg = load_config()
    settings = effective_settings(cfg)
    host = settings["host"]
    port = settings["port"]

    # 🔸 start the background speedtest scheduler
    Thread(target=_speedtest_scheduler, daemon=True).start()

    try:
        from waitress import serve as waitress_serve
        logging.info(f"Starting dashboard on port {port} (config: {CONFIG_PATH}) ...")
        waitress_serve(app, host=host, port=port)
    except Exception as e:
        logging.warning("Waitress not available, using Flask dev server: %s", e)
        app.run(host=host, port=port, debug=False)

if __name__ == "__main__":
    main()
