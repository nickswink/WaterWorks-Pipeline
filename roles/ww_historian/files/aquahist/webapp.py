"""AquaHistorian 4.2 - web trend viewer."""

import csv
import functools
import hashlib
import hmac
import io
import os
import re
import socket
import sqlite3
import sys
import time
from datetime import timedelta

from flask import (Flask, Response, g, redirect, render_template, request,
                   session, url_for)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import connect, load_config, system_config  # noqa: E402

SITES = ("INTAKE", "WTP", "BOOSTER")
SITE_NAMES = {
    "INTAKE": "Cedar River Intake PS-1",
    "WTP": "Cedar Ridge WTP - Chemical Feed",
    "BOOSTER": "Hilltop Booster PS-3 / Summit Tank",
}
MAX_HOURS = 24
TABLE_ROWS = 500


def fmt_ts(ts):
    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    return "NULL" if ts is None else str(ts)


def fmt_value(v, units=None):
    if v is None:
        return "NULL"
    if isinstance(v, float):
        if units == "bool" and v in (0.0, 1.0):
            return "TRUE" if v else "FALSE"
        if v.is_integer() and abs(v) < 1e12:
            return "%d" % v
        return ("%.3f" % v).rstrip("0").rstrip(".")
    return str(v)


def engine_error(exc):
    return "AquaHistorian query engine error: %s.%s: %s" % (type(exc).__module__, type(exc).__name__, exc)


def fmt_age(seconds):
    if seconds is None:
        return "never"
    seconds = int(seconds)
    if seconds < 120:
        return "%ds ago" % seconds
    if seconds < 7200:
        return "%dm ago" % (seconds // 60)
    if seconds < 172800:
        return "%dh ago" % (seconds // 3600)
    return "%dd ago" % (seconds // 86400)


def create_app(conf_path=None):
    cfg = load_config(conf_path)
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config["DB_PATH"] = cfg.get("database", "path")
    app.config["VERSION"] = cfg.get("product", "version")
    app.config["BUILD"] = cfg.get("product", "build")
    app.config["SESSION_COOKIE_NAME"] = "AQHSESSID"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)

    key_file = cfg.get("server", "secret_key_file")
    try:
        with open(key_file, encoding="utf-8") as fh:
            app.secret_key = fh.read().strip()
    except OSError:
        app.secret_key = os.urandom(32).hex()
    app.jinja_env.filters["ts"] = fmt_ts
    app.jinja_env.filters["val"] = fmt_value
    app.jinja_env.filters["age"] = fmt_age

    def db():
        if "db" not in g:
            g.db = connect(app.config["DB_PATH"])
        return g.db

    def db_ro():
        if "db_ro" not in g:
            g.db_ro = connect(app.config["DB_PATH"], readonly=True)
        return g.db_ro

    @app.teardown_appcontext
    def close_db(exc):
        for k in ("db", "db_ro"):
            conn = g.pop(k, None)
            if conn is not None:
                conn.close()

    def cfgval(key, default=""):
        if "syscfg" not in g:
            try:
                g.syscfg = system_config(db())
            except sqlite3.Error:
                g.syscfg = {}
        return g.syscfg.get(key, default)

    @app.context_processor
    def inject():
        return {
            "site_name": cfgval("site_name", "WaterWorks Pipeline Co."),
            "version": app.config["VERSION"],
            "major_minor": ".".join(app.config["VERSION"].split(".")[:2]),
            "user": session.get("user"),
            "role": session.get("role"),
            "now": time.time(),
        }

    @app.after_request
    def headers(resp):
        resp.headers["X-Powered-By"] = "AquaHistorian/%s" % app.config["VERSION"]
        resp.headers["Cache-Control"] = "no-store"
        return resp

    def login_required(view):
        @functools.wraps(view)
        def wrapped(*a, **kw):
            if not session.get("user"):
                return redirect(url_for("login", next=request.full_path.rstrip("?")))
            return view(*a, **kw)
        return wrapped

    # ------------------------------------------------------------------ auth
    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            row = db().execute("SELECT username, password_md5, role FROM users WHERE username = ?",
                               (username,)).fetchone()
            digest = hashlib.md5(password.encode("utf-8")).hexdigest()
            if row and hmac.compare_digest(row[1], digest):
                session.clear()
                session.permanent = True
                session["user"], session["role"] = row[0], row[2]
                with db():
                    db().execute("UPDATE users SET last_login = ? WHERE username = ?",
                                 (time.strftime("%Y-%m-%d %H:%M:%S"), row[0]))
                nxt = request.args.get("next", "")
                if not nxt.startswith("/") or nxt.startswith("//"):
                    nxt = url_for("dashboard")
                return redirect(nxt)
            error = "Invalid username or password."
        return render_template("login.html", error=error)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ------------------------------------------------------------- dashboard
    @app.route("/")
    @login_required
    def dashboard():
        now = time.time()
        stale_after = float(cfgval("stale_after_s", "20") or 20)
        rows = db().execute(
            "SELECT c.tag, c.ts, c.value, c.quality, COALESCE(t.units, c.units), "
            "COALESCE(t.description, c.description), t.rowid "
            "FROM current_values c LEFT JOIN tags t ON t.name = c.tag "
            "ORDER BY COALESCE(t.rowid, 1000000), c.tag").fetchall()
        groups = {s: [] for s in SITES}
        for tag, ts, value, quality, units, desc, _ in rows:
            site = tag.split(".", 1)[0] if "." in tag else "OTHER"
            age = (now - ts) if ts else None
            quality = quality or "GOOD"
            if quality != "GOOD":
                state = "bad"
            elif age is None or age > stale_after:
                state = "stale"
            else:
                state = "good"
            groups.setdefault(site, []).append({
                "tag": tag, "short": tag.split(".", 1)[-1], "ts": ts, "age": age,
                "value": fmt_value(value, units), "units": "" if units in (None, "bool", "enum", "ASCII") else units,
                "quality": quality if state != "stale" else "STALE", "state": state, "desc": desc or "",
            })
        status = db().execute("SELECT last_attempt, last_success, consecutive_failures, last_error, "
                              "tags_last_poll FROM collector_status WHERE id = 1").fetchone()
        status = dict(zip(("last_attempt", "last_success", "failures", "last_error", "tags"),
                          status or (None, None, 0, None, 0)))
        n_tags = db().execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        return render_template("dashboard.html", groups=groups, site_names=SITE_NAMES,
                               status=status, n_tags=n_tags, stale_after=stale_after,
                               api_url=cfgval("scada_api_url"))

    # ------------------------------------------------------------------ tags
    @app.route("/tags")
    @login_required
    def tags():
        site = request.args.get("site", "")
        q = request.args.get("q", "").strip()
        sql = "SELECT name, site, source, address, units, description FROM tags WHERE 1=1"
        params = []
        if site:
            sql += " AND site = ?"
            params.append(site)
        if q:
            sql += " AND (name LIKE ? OR description LIKE ? OR address LIKE ?)"
            params += ["%" + q + "%"] * 3
        sql += " ORDER BY rowid"
        rows = db().execute(sql, params).fetchall()
        return render_template("tags.html", rows=rows, site=site, q=q, sites=SITES)

    # ----------------------------------------------------------------- trend
    def trend_query(tag, hours):
        since = int(time.time()) - hours * 3600
        limit = hours * 720
        # NOTE: legacy query builder from AquaHistorian 3.x trend module
        return ("SELECT ts, value FROM samples WHERE ts >= %d AND tag = '%s' "
                "ORDER BY ts DESC LIMIT %d" % (since, tag, limit))

    def parse_hours():
        try:
            hours = int(request.args.get("hours", "1"))
        except ValueError:
            hours = 1
        return min(max(hours, 1), MAX_HOURS)

    @app.route("/trend")
    @login_required
    def trend():
        tag = request.args.get("tag", "")
        hours = parse_hours()
        rows, error, sql = [], None, None
        if tag:
            sql = trend_query(tag, hours)
            try:
                rows = db_ro().execute(sql).fetchall()
            except (sqlite3.Error, sqlite3.Warning, ValueError) as exc:
                error = engine_error(exc)
        points = [[r[0], r[1]] for r in rows
                  if len(r) >= 2 and isinstance(r[0], (int, float)) and isinstance(r[1], (int, float))]
        points.sort(key=lambda p: p[0])
        nums = [p[1] for p in points]
        stats = None
        if nums:
            stats = {"min": min(nums), "max": max(nums), "avg": sum(nums) / len(nums), "last": nums[-1]}
        meta = db().execute("SELECT name, site, source, address, units, description FROM tags WHERE name = ?",
                            (tag,)).fetchone() if tag else None
        tag_list = [r[0] for r in db().execute(
            "SELECT name FROM tags WHERE units NOT IN ('ASCII') ORDER BY rowid").fetchall()]
        return render_template("trend.html", tag=tag, hours=hours, rows=rows[:TABLE_ROWS],
                               total=len(rows), points=points, stats=stats, error=error, sql=sql,
                               meta=meta, tag_list=tag_list, max_rows=TABLE_ROWS,
                               hour_choices=(1, 2, 4, 8, 12, 24))

    @app.route("/export.csv")
    @login_required
    def export_csv():
        tag = request.args.get("tag", "")
        hours = parse_hours()
        try:
            rows = db_ro().execute(trend_query(tag, hours)).fetchall()
        except (sqlite3.Error, sqlite3.Warning, ValueError) as exc:
            return Response(engine_error(exc) + "\n", status=500,
                            mimetype="text/plain")
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["timestamp", "tag", "value"])
        for r in rows:
            w.writerow([fmt_ts(r[0]), tag, "" if len(r) < 2 or r[1] is None else r[1]])
        fname = re.sub(r"[^A-Za-z0-9_.-]", "_", tag)[:64] or "export"
        return Response(buf.getvalue(), mimetype="text/csv", headers={
            "Content-Disposition": "attachment; filename=%s_%dh.csv" % (fname, hours)})

    # ----------------------------------------------------------------- about
    @app.route("/about")
    @login_required
    def about():
        status = db().execute("SELECT last_success, consecutive_failures FROM collector_status "
                              "WHERE id = 1").fetchone() or (None, 0)
        info = {
            "samples": db().execute("SELECT COUNT(*) FROM samples").fetchone()[0],
            "tags": db().execute("SELECT COUNT(*) FROM tags").fetchone()[0],
            "last_success": status[0],
            "failures": status[1],
        }
        return render_template("about.html", build=app.config["BUILD"], info=info,
                               hostname=socket.gethostname(), sqlite_version=sqlite3.sqlite_version,
                               api_url=cfgval("scada_api_url"), interval=cfgval("collector_interval", "5"),
                               retention=cfgval("retention_hours", "24"), license=cfgval("license"))

    @app.errorhandler(404)
    def not_found(exc):
        return render_template("error.html", code=404, message="The requested page was not found."), 404

    @app.errorhandler(500)
    def server_error(exc):
        return render_template("error.html", code=500, message="Internal server error."), 500

    return app
