#!/usr/bin/env python3
"""
AquaView SCADA HMI - Cedar Ridge Regional Transmission System.

A Flask application that acts as the SCADA master for the control center:

  * A background poller reads the three field controllers over Modbus/TCP
    (reusing mbclient.ModbusClient) every ~2 s and caches scaled tag values.
  * A token-authenticated tag API (GET /api/v1/tags) feeds the process
    historian.
  * A session-authenticated operator web UI presents the plant mimic,
    per-site screens, a live alarm list and the shift log.

The poller NEVER crashes the application if a controller is down: the whole
site is simply flagged COMM_FAIL and the last cached values are retained.
"""

import datetime
import json
import logging
import os
import struct
import threading
import time
from collections import OrderedDict
from functools import wraps

from flask import (Flask, Response, abort, g, jsonify, redirect, render_template,
                   request, session, url_for)

from mbclient import ModbusClient, ModbusError, regs_to_text

log = logging.getLogger("aquaview")

# ---------------------------------------------------------------------------
#  Tag catalog
#
#  Each tag is (TABLE, ADDR, SCALE, UNITS, KIND, DESC) keyed by its DESIGN.md
#  name.  SITE labels map to a controller profile:
#     INTAKE  -> intake   (Modicon M340)
#     WTP     -> chemfeed  (Unitronics Vision V570; MI->HR, MB->coils)
#     BOOSTER -> booster   (SCADAPack 474)
#  TABLE is one of hr (holding reg / FC3), ir (input reg / FC4),
#  co (coil / FC1), di (discrete input / FC2).
#  KIND is num (value = raw*scale), bool (0.0/1.0) or text (ASCII buffer; the
#  SCALE field then carries the register count).
# ---------------------------------------------------------------------------


def _tag(table, addr, units, desc, scale=1.0, kind="num", count=0):
    return {"table": table, "addr": addr, "scale": scale, "units": units,
            "kind": kind, "desc": desc, "count": count}


def _num(table, addr, scale, units, desc):
    return _tag(table, addr, units, desc, scale=scale, kind="num")


def _bool(table, addr, desc):
    return _tag(table, addr, "bool", desc, scale=1.0, kind="bool")


def _text(table, addr, count, desc):
    return _tag(table, addr, "ASCII", desc, kind="text", count=count)


INTAKE_TAGS = OrderedDict([
    ("P101_HAND_RUN", _bool("co", 0, "Pump P-101 hand run command (effective only in HAND)")),
    ("P102_HAND_RUN", _bool("co", 1, "Pump P-102 hand run command (effective only in HAND)")),
    ("P103_HAND_RUN", _bool("co", 2, "Pump P-103 hand run command (effective only in HAND)")),
    ("LL_PROTECT_EN", _bool("co", 10, "Wet-well low-low pump protection enable (engineered: 1)")),
    ("ALARM_RESET", _bool("co", 11, "Alarm reset (momentary)")),
    ("P101_RUNNING", _bool("di", 0, "Pump P-101 running")),
    ("P102_RUNNING", _bool("di", 1, "Pump P-102 running")),
    ("P103_RUNNING", _bool("di", 2, "Pump P-103 running")),
    ("P101_FAULT", _bool("di", 3, "Pump P-101 fault (damaged / tripped)")),
    ("P102_FAULT", _bool("di", 4, "Pump P-102 fault (damaged / tripped)")),
    ("P103_FAULT", _bool("di", 5, "Pump P-103 fault (damaged / tripped)")),
    ("WW_LEVEL_HH", _bool("di", 8, "Wet-well level high-high alarm")),
    ("WW_LEVEL_LL", _bool("di", 9, "Wet-well level low-low alarm")),
    ("WW_LEVEL", _num("ir", 0, 0.01, "ft", "Wet-well level")),
    ("RIVER_INFLOW", _num("ir", 1, 0.01, "MGD", "Cedar River inflow")),
    ("PUMP_FLOW", _num("ir", 2, 0.01, "MGD", "Raw water pump station flow")),
    ("P101_AMPS", _num("ir", 3, 0.1, "A", "Pump P-101 motor current")),
    ("P102_AMPS", _num("ir", 4, 0.1, "A", "Pump P-102 motor current")),
    ("P103_AMPS", _num("ir", 5, 0.1, "A", "Pump P-103 motor current")),
    ("HEADER_PRESS", _num("ir", 6, 0.1, "psi", "Discharge header pressure")),
    ("RAW_TURBIDITY", _num("ir", 7, 0.01, "NTU", "Raw water turbidity")),
    ("P101_VIBRATION", _num("ir", 8, 0.1, "mm/s", "Pump P-101 vibration (>11.0 = cavitation)")),
    ("P102_VIBRATION", _num("ir", 9, 0.1, "mm/s", "Pump P-102 vibration (>11.0 = cavitation)")),
    ("P103_VIBRATION", _num("ir", 10, 0.1, "mm/s", "Pump P-103 vibration (>11.0 = cavitation)")),
    ("GATE_POS", _num("ir", 11, 0.1, "%", "Intake sluice gate position")),
    ("P101_MODE", _num("hr", 0, 1.0, "enum", "Pump P-101 mode: 0=OFF 1=HAND 2=AUTO")),
    ("P102_MODE", _num("hr", 1, 1.0, "enum", "Pump P-102 mode: 0=OFF 1=HAND 2=AUTO")),
    ("P103_MODE", _num("hr", 2, 1.0, "enum", "Pump P-103 mode: 0=OFF 1=HAND 2=AUTO")),
    ("LEAD_START", _num("hr", 10, 0.01, "ft", "Lead pump start level")),
    ("LAG_START", _num("hr", 11, 0.01, "ft", "Lag pump start level")),
    ("LEAD_STOP", _num("hr", 12, 0.01, "ft", "Lead pump stop level")),
    ("LAG_STOP", _num("hr", 13, 0.01, "ft", "Lag pump stop level")),
    ("LL_TRIP", _num("hr", 14, 0.01, "ft", "Wet-well low-low pump trip level")),
    ("GATE_SP", _num("hr", 15, 0.1, "%", "Intake gate position setpoint")),
    ("HEARTBEAT", _num("hr", 100, 1.0, "count", "PLC heartbeat counter")),
    ("EVENT_TEXT", _text("hr", 9000, 24, "Event message buffer (captured-impact text)")),
])

WTP_TAGS = OrderedDict([
    ("PLANT_FLOW", _num("hr", 0, 0.01, "MGD", "Plant flow")),
    ("NAOH_DOSE_SP", _num("hr", 1, 1.0, "ppm", "Sodium hydroxide dose setpoint")),
    ("NAOH_DOSE_PV", _num("hr", 2, 1.0, "ppm", "Sodium hydroxide dose (measured)")),
    ("FINISHED_PH", _num("hr", 3, 0.01, "pH", "Finished water pH")),
    ("NAOH_PUMP_SPEED", _num("hr", 4, 0.1, "%", "NaOH metering pump speed")),
    ("CL2_DOSE_SP", _num("hr", 5, 0.01, "mg/L", "Chlorine dose setpoint")),
    ("CL2_RESIDUAL", _num("hr", 6, 0.01, "mg/L", "Free chlorine residual")),
    ("CLEARWELL_LEVEL", _num("hr", 7, 0.01, "ft", "Clearwell level")),
    ("RAW_PH", _num("hr", 8, 0.01, "pH", "Raw water pH")),
    ("NAOH_TANK_LEVEL", _num("hr", 9, 0.1, "%", "NaOH bulk tank level")),
    ("PH_HI_SP", _num("hr", 10, 0.01, "pH", "Finished pH high alarm setpoint")),
    ("PH_HIHI_SP", _num("hr", 11, 0.01, "pH", "Finished pH high-high cutout setpoint")),
    ("DOSE_MODE", _num("hr", 12, 1.0, "enum", "NaOH dose mode: 0=OFF 1=MANUAL 2=AUTO")),
    ("HEARTBEAT", _num("hr", 20, 1.0, "count", "PLC heartbeat counter")),
    ("NAOH_PUMP_EN", _bool("co", 0, "NaOH metering pump enable")),
    ("CL2_FEED_EN", _bool("co", 1, "Chlorine feed enable")),
    ("PH_HIHI_CUTOUT_EN", _bool("co", 2, "pH high-high NaOH pump cutout enable (engineered: 1)")),
    ("ALARM_RESET", _bool("co", 3, "Alarm reset (momentary)")),
    ("NAOH_PUMP_RUNNING", _bool("di", 0, "NaOH metering pump running")),
    ("PH_HI_ALARM", _bool("di", 1, "Finished pH high alarm")),
    ("PH_HIHI_ALARM", _bool("di", 2, "Finished pH high-high alarm")),
    ("PLC_RUN", _bool("di", 3, "Controller mode: 1=RUN 0=STOP")),
    ("PANEL_MSG", _text("hr", 900, 24, "Operator panel banner message")),
    ("EVENT_A_TEXT", _text("hr", 930, 24, "Event buffer A (NaOH / pH event)")),
    ("EVENT_B_TEXT", _text("hr", 960, 24, "Event buffer B (panel defacement event)")),
])

BOOSTER_TAGS = OrderedDict([
    ("P301_HAND_RUN", _bool("co", 0, "Booster pump P-301 hand run command")),
    ("P302_HAND_RUN", _bool("co", 1, "Booster pump P-302 hand run command")),
    ("HP_TRIP_EN", _bool("co", 10, "[P] Pump high-discharge-pressure trip enable")),
    ("HL_CUTOFF_EN", _bool("co", 11, "[P] Summit Tank high-level pump cutoff enable")),
    ("SAV_ARMED", _bool("co", 12, "[P] Surge anticipator valve SAV-301 armed")),
    ("ALARM_RESET", _bool("co", 13, "Alarm reset (momentary)")),
    ("P301_RUNNING", _bool("di", 0, "Booster pump P-301 running")),
    ("P302_RUNNING", _bool("di", 1, "Booster pump P-302 running")),
    ("HP_TRIP_ACTIVE", _bool("di", 2, "High discharge pressure trip active")),
    ("TANK_HH", _bool("di", 3, "Summit Tank level high-high")),
    ("TANK_OVERFLOW", _bool("di", 4, "Summit Tank overflowing")),
    ("SAV_OPEN", _bool("di", 5, "Surge anticipator valve SAV-301 open")),
    ("MAINT_BYPASS_ACTIVE", _bool("di", 6, "Maintenance bypass active")),
    ("MAIN_BREAK", _bool("di", 7, "16in transmission main break (Miller Creek crossing)")),
    ("SUCTION_PRESS", _num("ir", 0, 0.1, "psi", "Station suction pressure")),
    ("DISCH_PRESS", _num("ir", 1, 0.1, "psi", "Station discharge pressure incl. transients")),
    ("FLOW", _num("ir", 2, 1.0, "gpm", "Station flow")),
    ("FCV301_POS", _num("ir", 3, 0.1, "%", "Flow control valve FCV-301 position")),
    ("TANK_LEVEL", _num("ir", 4, 0.01, "ft", "Summit Elevated Tank level (40 ft tank)")),
    ("TANK_DEMAND", _num("ir", 5, 1.0, "gpm", "Summit Tank outflow / member-town demand")),
    ("PEAK_TRANSIENT_60S", _num("ir", 6, 0.1, "psi", "Peak pressure transient, last 60 s")),
    ("MAINT_LOCKOUT_S", _num("ir", 7, 1.0, "s", "Maintenance key lockout time remaining")),
    ("P301_MODE", _num("hr", 0, 1.0, "enum", "Booster pump P-301 mode: 0=OFF 1=HAND 2=AUTO")),
    ("P302_MODE", _num("hr", 1, 1.0, "enum", "Booster pump P-302 mode: 0=OFF 1=HAND 2=AUTO")),
    ("FCV301_SP", _num("hr", 2, 0.1, "%", "FCV-301 position setpoint")),
    ("FCV301_SLEW", _num("hr", 3, 0.1, "%/s", "[P] FCV-301 slew rate limit")),
    ("LEAD_START", _num("hr", 10, 0.01, "ft", "Lead pump start tank level")),
    ("LEAD_STOP", _num("hr", 11, 0.01, "ft", "Lead pump stop tank level")),
    ("LAG_START", _num("hr", 12, 0.01, "ft", "Lag pump start tank level")),
    ("HL_CUTOFF_SP", _num("hr", 13, 0.01, "ft", "[P] Tank high-level pump cutoff")),
    ("HP_TRIP_SP", _num("hr", 14, 0.1, "psi", "[P] High discharge pressure trip setpoint")),
    ("MAINT_MODE", _num("hr", 21, 1.0, "bool", "Maintenance mode active (read only)")),
    ("MAINT_TIMER", _num("hr", 22, 1.0, "s", "Maintenance mode time remaining")),
    ("HEARTBEAT", _num("hr", 100, 1.0, "count", "RTU heartbeat counter")),
    ("EVENT_A_TEXT", _text("hr", 9000, 24, "Event buffer A (tank overflow)")),
    ("EVENT_B_TEXT", _text("hr", 9032, 24, "Event buffer B (main break)")),
])

# Block read plans per profile: (table, start, count).  Chosen to cover every
# tag with a handful of contiguous reads while respecting each profile's
# Modbus address limits (intake/booster co|di|ir<=64 hr<=10000; chemfeed has
# no input registers and hr/co<=1000).
CATALOG = OrderedDict([
    ("INTAKE", {
        "profile": "intake",
        "tags": INTAKE_TAGS,
        "blocks": [("co", 0, 12), ("di", 0, 10), ("ir", 0, 12),
                   ("hr", 0, 16), ("hr", 100, 1), ("hr", 9000, 24)],
    }),
    ("WTP", {
        "profile": "chemfeed",
        "tags": WTP_TAGS,
        "blocks": [("co", 0, 4), ("di", 0, 4), ("hr", 0, 13), ("hr", 20, 1),
                   ("hr", 900, 24), ("hr", 930, 24), ("hr", 960, 24)],
    }),
    ("BOOSTER", {
        "profile": "booster",
        "tags": BOOSTER_TAGS,
        "blocks": [("co", 0, 14), ("di", 0, 8), ("ir", 0, 8), ("hr", 0, 4),
                   ("hr", 10, 5), ("hr", 20, 3), ("hr", 100, 1),
                   ("hr", 9000, 24), ("hr", 9032, 24)],
    }),
])

_READERS = {
    "co": lambda c, a, n: c.read_coils(a, n),
    "di": lambda c, a, n: c.read_discrete_inputs(a, n),
    "hr": lambda c, a, n: c.read_holding_registers(a, n),
    "ir": lambda c, a, n: c.read_input_registers(a, n),
}


def tag_value(spec, raw):
    """Compute a tag's presentation value from a raw-register dict."""
    if spec["kind"] == "text":
        regs = [raw[(spec["table"], spec["addr"] + i)] for i in range(spec["count"])]
        return regs_to_text(regs)
    val = float(raw[(spec["table"], spec["addr"])])
    if spec["kind"] == "bool":
        return 1.0 if int(val) & 1 else 0.0
    scaled = val * spec["scale"]
    # keep integers tidy, round scaled values to a sane precision
    return round(scaled, 3)


# ---------------------------------------------------------------------------
#  Tag cache + poller
# ---------------------------------------------------------------------------
class TagCache:
    """Thread-safe snapshot of every tag's latest value / quality."""

    def __init__(self):
        self._lock = threading.Lock()
        self._tags = OrderedDict()
        for site, meta in CATALOG.items():
            for name, spec in meta["tags"].items():
                default = "" if spec["kind"] == "text" else 0.0
                self._tags["%s.%s" % (site, name)] = {
                    "value": default, "units": spec["units"],
                    "quality": "COMM_FAIL", "desc": spec["desc"],
                }

    def update_site(self, site, values):
        """values: {tagname: computed_value}; marks the site GOOD."""
        with self._lock:
            for name, val in values.items():
                key = "%s.%s" % (site, name)
                if key in self._tags:
                    self._tags[key]["value"] = val
                    self._tags[key]["quality"] = "GOOD"

    def fail_site(self, site):
        """Mark every tag of a site COMM_FAIL, retaining last values."""
        with self._lock:
            prefix = site + "."
            for key, entry in self._tags.items():
                if key.startswith(prefix):
                    entry["quality"] = "COMM_FAIL"

    def snapshot(self):
        with self._lock:
            return OrderedDict((k, dict(v)) for k, v in self._tags.items())


class Poller:
    """Background Modbus poller feeding a TagCache."""

    def __init__(self, cache, sites, interval=2.0):
        # sites: {SITE: {"host":.., "port":.., "unit":..}}
        self.cache = cache
        self.sites = sites
        self.interval = float(interval)
        self._stop = threading.Event()
        self._thread = None

    def poll_site(self, site):
        """Read one controller once. Raises on comms failure."""
        meta = CATALOG[site]
        cfg = self.sites[site]
        raw = {}
        with ModbusClient(cfg["host"], port=cfg.get("port", 502),
                          unit=cfg.get("unit", 1), timeout=cfg.get("timeout", 1.5)) as c:
            for table, start, count in meta["blocks"]:
                regs = _READERS[table](c, start, count)
                for i, v in enumerate(regs):
                    raw[(table, start + i)] = v
        values = {}
        for name, spec in meta["tags"].items():
            try:
                values[name] = tag_value(spec, raw)
            except (KeyError, IndexError):
                continue
        return values

    def poll_once(self):
        """Poll every site; update cache. Never raises."""
        for site in self.sites:
            try:
                values = self.poll_site(site)
                self.cache.update_site(site, values)
            except (OSError, ConnectionError, ModbusError, struct.error) as exc:
                log.warning("poll %s (%s) failed: %s", site, self.sites[site].get("host"), exc)
                self.cache.fail_site(site)
            except Exception as exc:  # a bad frame must never kill the poller
                log.warning("poll %s unexpected error: %s", site, exc)
                self.cache.fail_site(site)

    def run(self):
        log.info("AquaView poller started (interval %.1fs, sites: %s)",
                 self.interval, ", ".join(self.sites))
        while not self._stop.is_set():
            start = time.monotonic()
            self.poll_once()
            elapsed = time.monotonic() - start
            self._stop.wait(max(0.1, self.interval - elapsed))

    def start(self):
        self._thread = threading.Thread(target=self.run, name="aquaview-poller", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()


# ---------------------------------------------------------------------------
#  Alarm derivation
# ---------------------------------------------------------------------------
SEV_ORDER = {"ok": 0, "info": 1, "warn": 2, "alarm": 3, "critical": 4}


def _v(snap, key):
    e = snap.get(key)
    return e["value"] if e else None


def _q(snap, key):
    e = snap.get(key)
    return e["quality"] if e else "COMM_FAIL"


def site_comm_ok(snap, site):
    """A site is in comms if its heartbeat tag reads GOOD."""
    return _q(snap, "%s.HEARTBEAT" % site) == "GOOD"


def build_alarms(snap):
    """Return a list of active alarm dicts: {site, sev, text}."""
    alarms = []

    def add(site, sev, text):
        alarms.append({"site": site, "sev": sev, "text": text})

    # Captured-impact event text (surfaced verbatim) --------------------------
    event_tags = [
        ("INTAKE", "INTAKE.EVENT_TEXT", "Intake PS-1"),
        ("WTP", "WTP.EVENT_A_TEXT", "WTP chemical feed"),
        ("WTP", "WTP.EVENT_B_TEXT", "WTP operator panel"),
        ("BOOSTER", "BOOSTER.EVENT_A_TEXT", "Summit Tank"),
        ("BOOSTER", "BOOSTER.EVENT_B_TEXT", "Transmission main"),
    ]
    for site, key, where in event_tags:
        txt = _v(snap, key)
        if isinstance(txt, str) and txt.strip():
            add(site, "critical", "CAPTURED IMPACT [%s]: %s" % (where, txt.strip()))

    # Per-site process alarms -------------------------------------------------
    for site in CATALOG:
        if not site_comm_ok(snap, site):
            add(site, "warn", "%s controller COMM FAIL - values are stale" % site)

    if _v(snap, "INTAKE.WW_LEVEL_HH") == 1.0:
        add("INTAKE", "alarm", "Wet-well level HIGH-HIGH")
    if _v(snap, "INTAKE.WW_LEVEL_LL") == 1.0:
        add("INTAKE", "alarm", "Wet-well level LOW-LOW")
    for p in ("P101", "P102", "P103"):
        if _v(snap, "INTAKE.%s_FAULT" % p) == 1.0:
            add("INTAKE", "alarm", "Intake pump %s FAULT (damaged / tripped)" % p)

    if _v(snap, "WTP.PH_HIHI_ALARM") == 1.0:
        add("WTP", "alarm", "Finished pH HIGH-HIGH - caustic overdose risk")
    elif _v(snap, "WTP.PH_HI_ALARM") == 1.0:
        add("WTP", "warn", "Finished pH HIGH")
    if _v(snap, "WTP.PLC_RUN") == 0.0 and site_comm_ok(snap, "WTP"):
        add("WTP", "alarm", "Chemical feed controller in STOP")

    if _v(snap, "BOOSTER.MAIN_BREAK") == 1.0:
        add("BOOSTER", "alarm", "Transmission MAIN BREAK detected (Miller Creek crossing)")
    if _v(snap, "BOOSTER.TANK_OVERFLOW") == 1.0:
        add("BOOSTER", "alarm", "Summit Tank OVERFLOW")
    elif _v(snap, "BOOSTER.TANK_HH") == 1.0:
        add("BOOSTER", "warn", "Summit Tank level HIGH-HIGH")
    if _v(snap, "BOOSTER.HP_TRIP_ACTIVE") == 1.0:
        add("BOOSTER", "warn", "Booster high discharge pressure trip active")
    if _v(snap, "BOOSTER.MAINT_MODE") == 1.0:
        add("BOOSTER", "info", "Booster in MAINTENANCE MODE - protective interlocks bypassable")

    alarms.sort(key=lambda a: -SEV_ORDER.get(a["sev"], 0))
    return alarms


def site_status(snap, site):
    """Worst severity for a site, for mimic colouring."""
    worst = "ok"
    for a in build_alarms(snap):
        if a["site"] == site and SEV_ORDER.get(a["sev"], 0) > SEV_ORDER.get(worst, 0):
            worst = a["sev"]
    return worst


# ---------------------------------------------------------------------------
#  View model helpers for templates
# ---------------------------------------------------------------------------
def fmt_value(entry):
    """Render a tag entry for display."""
    val = entry["value"]
    if isinstance(val, str):
        return val if val else "-"
    if entry["units"] == "enum":
        return {0: "OFF", 1: "HAND/MANUAL", 2: "AUTO"}.get(int(val), str(int(val)))
    if entry["units"] == "bool":
        return "ON" if val else "OFF"
    if float(val).is_integer():
        return str(int(val))
    return "%.2f" % val


def site_view(snap, site):
    """Build an ordered list of display rows for a site's screen."""
    rows = []
    prefix = site + "."
    comm = site_comm_ok(snap, site)
    for key, entry in snap.items():
        if not key.startswith(prefix):
            continue
        tag = key[len(prefix):]
        rows.append({
            "tag": tag, "key": key, "value": fmt_value(entry),
            "units": entry["units"], "quality": entry["quality"],
            "desc": entry["desc"],
        })
    return {"rows": rows, "comm": comm, "status": site_status(snap, site)}


# ---------------------------------------------------------------------------
#  Flask application
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "secret_key": "aquaview-dev-secret-change-me",
    "api_token": "changeme",
    "org_name": "WaterWorks Pipeline Co.",
    "controlroom_password": "controlroom",
    "viewer_password": "viewer",
    "hmi_access_flag": "WTR{flag_not_configured}",
    "poll_interval": 2.0,
    "sites": {
        "INTAKE": {"host": "127.0.0.1", "port": 502, "unit": 1},
        "WTP": {"host": "127.0.0.1", "port": 502, "unit": 1},
        "BOOSTER": {"host": "127.0.0.1", "port": 502, "unit": 1},
    },
}

ACCOUNTS = {
    # username -> (config password key, role)
    "controlroom": ("controlroom_password", "operator"),
    "viewer": ("viewer_password", "viewer"),
}


def load_config(path=None):
    cfg = dict(DEFAULT_CONFIG)
    path = path or os.environ.get("AQUAVIEW_CONFIG", "/etc/aquaview/aquaview.json")
    try:
        with open(path) as fh:
            cfg.update(json.load(fh))
    except FileNotFoundError:
        log.warning("config %s not found, using defaults", path)
    except (ValueError, OSError) as exc:
        log.error("could not load config %s: %s", path, exc)
    return cfg


def create_app(config=None, cache=None):
    app = Flask(__name__)
    app.config["AQV"] = config or load_config()
    app.secret_key = app.config["AQV"]["secret_key"]
    app.config["TAG_CACHE"] = cache if cache is not None else TagCache()

    def cfg():
        return app.config["AQV"]

    def tagcache():
        return app.config["TAG_CACHE"]

    # -- auth helpers -------------------------------------------------------
    def login_required(view):
        @wraps(view)
        def wrapped(*a, **kw):
            if not session.get("user"):
                return redirect(url_for("login", next=request.path))
            return view(*a, **kw)
        return wrapped

    @app.context_processor
    def inject_common():
        return {
            "org_name": cfg()["org_name"],
            "user": session.get("user"),
            "role": session.get("role"),
            "hostname": "ww-hmi01",
        }

    # -- tag API (historian contract) --------------------------------------
    @app.route("/api/v1/tags")
    def api_tags():
        auth = request.headers.get("Authorization", "")
        expected = "Bearer " + cfg()["api_token"]
        if auth != expected:
            resp = jsonify({"error": "unauthorized"})
            resp.status_code = 401
            resp.headers["WWW-Authenticate"] = "Bearer"
            return resp
        snap = tagcache().snapshot()
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        tags = OrderedDict()
        for key, entry in snap.items():
            tags[key] = {
                "value": entry["value"],
                "units": entry["units"],
                "quality": entry["quality"],
                "desc": entry["desc"],
            }
        return app.response_class(
            json.dumps({"timestamp": ts, "tags": tags}),
            mimetype="application/json",
        )

    @app.route("/healthz")
    def healthz():
        return Response("ok\n", mimetype="text/plain")

    # -- auth routes --------------------------------------------------------
    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            u = (request.form.get("username") or "").strip()
            p = request.form.get("password") or ""
            acct = ACCOUNTS.get(u)
            if acct and p == cfg().get(acct[0]):
                session["user"] = u
                session["role"] = acct[1]
                nxt = request.args.get("next") or url_for("overview")
                if not nxt.startswith("/"):
                    nxt = url_for("overview")
                return redirect(nxt)
            error = "Invalid control-room credentials."
        return render_template("login.html", error=error)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # -- operator screens ---------------------------------------------------
    @app.route("/")
    @login_required
    def overview():
        snap = tagcache().snapshot()
        statuses = {s: site_status(snap, s) for s in CATALOG}
        mimic = {
            "intake_level": fmt_value(snap["INTAKE.WW_LEVEL"]),
            "intake_flow": fmt_value(snap["INTAKE.PUMP_FLOW"]),
            "wtp_ph": fmt_value(snap["WTP.FINISHED_PH"]),
            "wtp_cl2": fmt_value(snap["WTP.CL2_RESIDUAL"]),
            "main_press": fmt_value(snap["BOOSTER.DISCH_PRESS"]),
            "booster_flow": fmt_value(snap["BOOSTER.FLOW"]),
            "tank_level": fmt_value(snap["BOOSTER.TANK_LEVEL"]),
        }
        return render_template("overview.html", statuses=statuses, mimic=mimic,
                               alarms=build_alarms(snap))

    def _site_page(site, title, template="site.html"):
        snap = tagcache().snapshot()
        view = site_view(snap, site)
        alarms = [a for a in build_alarms(snap) if a["site"] == site]
        return render_template(template, site=site, title=title, view=view, alarms=alarms)

    @app.route("/intake")
    @login_required
    def intake():
        return _site_page("INTAKE", "Cedar River Intake PS-1")

    @app.route("/chemfeed")
    @login_required
    def chemfeed():
        return _site_page("WTP", "Cedar Ridge WTP - Chemical Feed")

    @app.route("/booster")
    @login_required
    def booster():
        return _site_page("BOOSTER", "Hilltop Booster PS-3 / Summit Tank")

    @app.route("/alarms")
    @login_required
    def alarms():
        snap = tagcache().snapshot()
        return render_template("alarms.html", alarms=build_alarms(snap))

    @app.route("/shift-log")
    @login_required
    def shift_log():
        return render_template("shift_log.html", flag=cfg()["hmi_access_flag"])

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("error.html", code=403, message="Forbidden"), 403

    @app.errorhandler(404)
    def notfound(e):
        return render_template("error.html", code=404, message="Not Found"), 404

    return app


def main():  # pragma: no cover - production entrypoint
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = load_config()
    cache = TagCache()
    poller = Poller(cache, cfg["sites"], interval=cfg.get("poll_interval", 2.0))
    poller.start()
    app = create_app(config=cfg, cache=cache)
    from waitress import serve
    host = os.environ.get("AQUAVIEW_BIND", "0.0.0.0")
    port = int(os.environ.get("AQUAVIEW_PORT", "80"))
    log.info("AquaView HMI serving on %s:%d", host, port)
    serve(app, host=host, port=port, threads=8, ident="AquaView-HMI")


if __name__ == "__main__":
    main()
