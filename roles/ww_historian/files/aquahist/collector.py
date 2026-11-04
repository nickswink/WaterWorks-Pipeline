#!/usr/bin/env python3
"""AquaHistorian 4.2 - SCADA collector.

Polls the AquaView SCADA tag API and historises numeric tag values:

    GET <scada_api_url>            (system_config.scada_api_url)
    Authorization: Bearer <token>  (system_config.scada_api_token)

    {"timestamp": "...", "tags": {"WTP.FINISHED_PH": {"value": 8.02,
      "units": "pH", "quality": "GOOD", "desc": "..."}, ...}}

Connection or protocol failures are logged and retried on the next cycle;
the collector never exits on its own.
"""

import json
import logging
import math
import os
import signal
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import connect, init_schema, load_config, system_config  # noqa: E402

log = logging.getLogger("aquahist.collector")
USER_AGENT = "AquaHistorian-Collector/4.2.1"
_running = True


def fetch_tags(url, token, timeout=4.0):
    """Fetch and decode the tag snapshot. Raises on any failure."""
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer %s" % token,
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("tags"), dict):
        raise ValueError("unexpected response: no 'tags' object")
    return payload


def to_number(value):
    """bool -> 0/1, int/float/numeric string -> float, anything else -> None."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        v = float(value)
        return v if math.isfinite(v) else None
    if isinstance(value, str):
        try:
            v = float(value.strip())
            return v if math.isfinite(v) else None
        except ValueError:
            return None
    return None


def store_snapshot(conn, payload, now=None):
    """Write one tag snapshot. Returns number of numeric samples stored."""
    now = int(now if now is not None else time.time())
    samples, current = [], []
    for name, entry in payload["tags"].items():
        if not isinstance(name, str) or not name:
            continue
        if isinstance(entry, dict):
            raw = entry.get("value")
            quality = str(entry.get("quality") or "GOOD").upper()
            units = entry.get("units")
            desc = entry.get("desc")
        else:  # tolerate {"TAG": value}
            raw, quality, units, desc = entry, "GOOD", None, None
        num = to_number(raw)
        if num is not None:
            samples.append((now, name, num, quality))
            shown = num
        elif raw is None:
            shown = None
        else:
            shown = str(raw)[:256]  # text tags (ASCII buffers) shown on dashboard only
        current.append((name, now, shown, quality,
                        None if units is None else str(units)[:32],
                        None if desc is None else str(desc)[:256]))
    with conn:
        conn.executemany("INSERT INTO samples (ts, tag, value, quality) VALUES (?, ?, ?, ?)", samples)
        conn.executemany("INSERT OR REPLACE INTO current_values (tag, ts, value, quality, units, description) "
                         "VALUES (?, ?, ?, ?, ?, ?)", current)
        conn.execute("UPDATE collector_status SET last_attempt = ?, last_success = ?, "
                     "consecutive_failures = 0, last_error = NULL, tags_last_poll = ? WHERE id = 1",
                     (now, now, len(current)))
    return len(samples)


def record_failure(conn, err, now=None):
    now = int(now if now is not None else time.time())
    with conn:
        conn.execute("UPDATE collector_status SET last_attempt = ?, "
                     "consecutive_failures = COALESCE(consecutive_failures, 0) + 1, last_error = ? WHERE id = 1",
                     (now, str(err)[:500]))
        conn.execute("UPDATE current_values SET quality = 'COMM_FAIL'")


def prune(conn, hours, now=None):
    now = int(now if now is not None else time.time())
    with conn:
        cur = conn.execute("DELETE FROM samples WHERE ts < ?", (now - int(hours * 3600),))
    return cur.rowcount


def describe_error(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return "HTTP %s %s" % (exc.code, exc.reason)
    if isinstance(exc, urllib.error.URLError):
        return "connection failed: %s" % (exc.reason,)
    return "%s: %s" % (type(exc).__name__, exc)


def poll_once(conn, url, token, timeout=4.0):
    """One collection cycle. Returns (ok, samples_stored, error_text)."""
    try:
        payload = fetch_tags(url, token, timeout=timeout)
        n = store_snapshot(conn, payload)
        return True, n, None
    except Exception as exc:  # never let a bad poll kill the collector
        err = describe_error(exc)
        try:
            record_failure(conn, err)
        except Exception as db_exc:
            log.error("could not record failure: %s", db_exc)
        return False, 0, err


def _stop(signum, frame):
    global _running
    _running = False


def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    cfg = load_config()
    db_path = cfg.get("database", "path")
    conn = None
    last_prune = 0
    failures = 0
    log.info("AquaHistorian collector starting (db=%s)", db_path)

    while _running:
        interval = 5.0
        started = time.time()
        try:
            if conn is None:
                conn = connect(db_path)
                init_schema(conn)
            sc = system_config(conn)
            interval = max(1.0, float(sc.get("collector_interval") or 5))
            url = sc.get("scada_api_url")
            token = sc.get("scada_api_token", "")
            if not url:
                raise RuntimeError("scada_api_url not configured")
            ok, n, err = poll_once(conn, url, token, timeout=min(4.0, interval))
            if ok:
                if failures:
                    log.info("SCADA API connection restored after %d failed polls", failures)
                failures = 0
                log.debug("stored %d samples", n)
            else:
                failures += 1
                # log first failures, then once a minute to keep the journal readable
                if failures <= 3 or failures % max(1, int(60 / interval)) == 0:
                    log.warning("poll %s failed (%d consecutive): %s", url, failures, err)
            if started - last_prune > 300:
                hours = float(sc.get("retention_hours") or 24)
                removed = prune(conn, hours)
                last_prune = started
                if removed:
                    log.info("pruned %d samples older than %.0fh", removed, hours)
        except Exception as exc:
            log.error("collector cycle error: %s", describe_error(exc))
            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass
            conn = None
        sleep_for = interval - (time.time() - started)
        while _running and sleep_for > 0:
            time.sleep(min(0.5, sleep_for))
            sleep_for -= 0.5

    log.info("AquaHistorian collector stopped")


if __name__ == "__main__":
    main()
