#!/usr/bin/env python3
"""WaterWorks Pipeline - Red Team Operations Scoreboard.

Usage:
    app.py serve   # init DB, seed challenges, serve with waitress
    app.py seed    # init DB and upsert challenges from the seed file
"""
import csv
import hashlib
import hmac
import io
import json
import os
import secrets
import sqlite3
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import datetime
from functools import wraps

from flask import (Flask, Response, abort, flash, g, jsonify, redirect,
                   render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


DATA_DIR = os.environ.get("WW_SCORE_DATA_DIR", "/var/lib/ww-scoreboard")
SEED_FILE = os.environ.get("WW_SCORE_SEED_FILE", "/etc/ww-scoreboard/challenges.json")
DB_PATH = os.path.join(DATA_DIR, "scoreboard.db")
ADMIN_SHA256 = os.environ.get("WW_SCORE_ADMIN_SHA256", "").strip().lower()
REGISTRATION_OPEN = os.environ.get("WW_SCORE_REGISTRATION", "1") == "1"
HINT_PCT = _env_int("WW_SCORE_HINT_PCT", 10)
RATE_WRONG = _env_int("WW_SCORE_RATE_WRONG", 10)
RATE_WINDOW = _env_int("WW_SCORE_RATE_WINDOW", 60)
NET = os.environ.get("WW_SCORE_NET", "10.X")
EVENT_HOLD = _env_int("WW_SCORE_EVENT_HOLD", 600)
TITLE = "WaterWorks Pipeline"
SUBTITLE = "Red Team Operations Scoreboard"

CATEGORY_ORDER = [
    "Recon", "Initial Access", "Privilege Escalation", "Lateral Movement",
    "OT DMZ", "OT Access", "OT Recon", "Impact", "Intel",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at REAL NOT NULL,
    created_ip TEXT
);
CREATE TABLE IF NOT EXISTS challenges (
    key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    points INTEGER NOT NULL,
    host TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    hints TEXT NOT NULL DEFAULT '[]',
    flag_sha256 TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    visible INTEGER NOT NULL DEFAULT 1,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS solves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    challenge_key TEXT NOT NULL,
    solved_at REAL NOT NULL,
    UNIQUE (team_id, challenge_key)
);
CREATE TABLE IF NOT EXISTS hint_unlocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    challenge_key TEXT NOT NULL,
    hint_index INTEGER NOT NULL,
    cost INTEGER NOT NULL,
    unlocked_at REAL NOT NULL,
    UNIQUE (team_id, challenge_key, hint_index)
);
CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL,
    team_name TEXT NOT NULL,
    challenge_key TEXT NOT NULL,
    result TEXT NOT NULL,
    correct INTEGER NOT NULL,
    preview TEXT NOT NULL DEFAULT '',
    ip TEXT,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sub_team_ts ON submissions(team_id, ts);
CREATE INDEX IF NOT EXISTS idx_solves_key ON solves(challenge_key, solved_at);
"""

app = Flask(__name__,
            template_folder=os.path.join(BASE_DIR, "templates"),
            static_folder=os.path.join(BASE_DIR, "static"))
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_NAME="wwscore",
    PERMANENT_SESSION_LIFETIME=7 * 24 * 3600,
    MAX_CONTENT_LENGTH=64 * 1024,
)

_submit_lock = threading.Lock()
_login_fail = defaultdict(deque)
_login_lock = threading.Lock()


# --------------------------------------------------------------------------- db
def connect():
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 15000")
    return db


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


@app.teardown_appcontext
def _close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    db = connect()
    try:
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript(SCHEMA)
        db.commit()
    finally:
        db.close()


def normalize_flag(key, value):
    value = (value or "").strip()
    if key.startswith("intel_"):
        value = value.upper()
    return value


def flag_hash(key, value):
    return hashlib.sha256(normalize_flag(key, value).encode("utf-8")).hexdigest()


def seed(path=SEED_FILE):
    """Upsert challenges by key. Never deletes teams, solves or challenges.
    The admin-controlled `visible` flag is preserved on update."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    items = data["challenges"] if isinstance(data, dict) else data
    stats = {"inserted": 0, "updated": 0, "unchanged": 0}
    db = connect()
    try:
        db.execute("BEGIN IMMEDIATE")
        for i, c in enumerate(items):
            key = str(c["key"])
            digest = str(c["flag_sha256"]).lower()
            if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
                raise ValueError("bad flag_sha256 for %s" % key)
            vals = (str(c["title"]), str(c["category"]), int(c["points"]),
                    str(c.get("host", "")), str(c.get("description", "")),
                    json.dumps(list(c.get("hints") or [])), digest,
                    int(c.get("sort_order", i + 1)))
            row = db.execute(
                "SELECT title, category, points, host, description, hints, "
                "flag_sha256, sort_order FROM challenges WHERE key = ?", (key,)).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO challenges (key, title, category, points, host, description, "
                    "hints, flag_sha256, sort_order, visible, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)", (key,) + vals + (time.time(),))
                stats["inserted"] += 1
            elif tuple(row) != vals:
                db.execute(
                    "UPDATE challenges SET title=?, category=?, points=?, host=?, description=?, "
                    "hints=?, flag_sha256=?, sort_order=?, updated_at=? WHERE key=?",
                    vals + (time.time(), key))
                stats["updated"] += 1
            else:
                stats["unchanged"] += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    stats["changed"] = bool(stats["inserted"] or stats["updated"])
    return stats


def load_secret_key():
    path = os.path.join(DATA_DIR, "secret_key")
    try:
        with open(path, encoding="ascii") as fh:
            key = fh.read().strip()
        if key:
            return key
    except FileNotFoundError:
        pass
    key = secrets.token_hex(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(key)
    return key


def bootstrap(do_seed=True):
    init_db()
    app.secret_key = load_secret_key()
    if do_seed and os.path.exists(SEED_FILE):
        seed(SEED_FILE)


# ------------------------------------------------------------------- helpers
def now():
    return time.time()


def client_ip():
    return request.remote_addr or "?"


def hint_cost(points):
    return max(1, int(round(points * HINT_PCT / 100.0)))


def login_throttled(ip):
    cutoff = now() - 60
    with _login_lock:
        dq = _login_fail[ip]
        while dq and dq[0] < cutoff:
            dq.popleft()
        return len(dq) >= 10


def login_failed(ip):
    with _login_lock:
        _login_fail[ip].append(now())


@app.template_filter("ts")
def fmt_ts(value):
    if not value:
        return "—"
    return datetime.fromtimestamp(value).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


@app.template_filter("hm")
def fmt_hm(value):
    if not value:
        return "—"
    return datetime.fromtimestamp(value).astimezone().strftime("%H:%M:%S")


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


@app.before_request
def _before():
    if request.method == "POST":
        sent = request.form.get("csrf_token", "")
        if not sent or not hmac.compare_digest(sent, session.get("csrf", "")):
            abort(400, "Session expired or invalid form token. Reload and try again.")
    g.team = None
    tid = session.get("team_id")
    if tid is not None:
        row = get_db().execute("SELECT id, name FROM teams WHERE id = ?", (tid,)).fetchone()
        if row is None:
            session.pop("team_id", None)
        else:
            g.team = row


@app.context_processor
def _ctx():
    return {
        "csrf_token": csrf_token,
        "team": g.get("team"),
        "is_admin": bool(session.get("is_admin")),
        "site_title": TITLE,
        "site_subtitle": SUBTITLE,
        "registration_open": REGISTRATION_OPEN,
    }


def team_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if g.team is None:
            flash("Log in with your team account first.", "warn")
            return redirect(url_for("login", next=request.path))
        return fn(*a, **kw)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("is_admin"):
            return redirect(url_for("admin"))
        return fn(*a, **kw)
    return wrapper


def sort_categories(cats):
    order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    return sorted(cats, key=lambda c: (order.get(c, len(order)), c))


def compute_standings(db):
    chals = {r["key"]: r for r in db.execute(
        "SELECT key, title, category, points, visible, sort_order FROM challenges")}
    teams = db.execute("SELECT id, name, created_at FROM teams").fetchall()
    penalties = {r[0]: r[1] for r in db.execute(
        "SELECT team_id, SUM(cost) FROM hint_unlocks GROUP BY team_id")}
    solves = db.execute(
        "SELECT s.team_id, s.challenge_key, s.solved_at, t.name FROM solves s "
        "JOIN teams t ON t.id = s.team_id ORDER BY s.solved_at, s.id").fetchall()

    cat_totals = defaultdict(int)
    for c in chals.values():
        if c["visible"]:
            cat_totals[c["category"]] += 1
    categories = sort_categories(cat_totals.keys())

    first_blood = {}
    per = {t["id"]: {"id": t["id"], "name": t["name"], "created_at": t["created_at"],
                     "points": 0, "solves": 0, "last_solve": None, "first_bloods": 0,
                     "cats": defaultdict(int)} for t in teams}
    for s in solves:
        c = chals.get(s["challenge_key"])
        p = per.get(s["team_id"])
        if c is None or p is None:
            continue
        if s["challenge_key"] not in first_blood:
            first_blood[s["challenge_key"]] = {"team": s["name"], "team_id": s["team_id"],
                                               "at": s["solved_at"]}
            p["first_bloods"] += 1
        p["points"] += c["points"]
        p["solves"] += 1
        p["last_solve"] = s["solved_at"]
        if c["visible"]:
            p["cats"][c["category"]] += 1

    rows = []
    for p in per.values():
        p["penalty"] = int(penalties.get(p["id"], 0) or 0)
        p["score"] = p["points"] - p["penalty"]
        p["progress"] = [{"category": cat, "solved": p["cats"].get(cat, 0),
                          "total": cat_totals[cat]} for cat in categories]
        rows.append(p)
    rows.sort(key=lambda p: (-p["score"],
                             p["last_solve"] if p["last_solve"] is not None else float("inf"),
                             p["created_at"]))
    for i, p in enumerate(rows, 1):
        p["rank"] = i

    fb_list = []
    for c in sorted(chals.values(), key=lambda c: (CATEGORY_ORDER.index(c["category"])
                                                   if c["category"] in CATEGORY_ORDER else 99,
                                                   c["sort_order"])):
        if not c["visible"] and c["key"] not in first_blood:
            continue
        fb_list.append({"key": c["key"], "title": c["title"], "category": c["category"],
                        "points": c["points"], "blood": first_blood.get(c["key"])})
    return rows, categories, fb_list, first_blood


# --------------------------------------------------------------------- public
@app.get("/healthz")
def healthz():
    get_db().execute("SELECT 1").fetchone()
    return Response("ok\n", mimetype="text/plain")


@app.get("/")
def index():
    return redirect(url_for("scoreboard"))


@app.get("/scoreboard")
def scoreboard():
    rows, categories, fb_list, _ = compute_standings(get_db())
    return render_template("scoreboard.html", rows=rows, categories=categories,
                           first_bloods=fb_list, refresh=30)


@app.get("/api/scoreboard")
def api_scoreboard():
    rows, _, _, _ = compute_standings(get_db())
    return jsonify([{"rank": r["rank"], "team": r["name"], "score": r["score"],
                     "solves": r["solves"], "penalty": r["penalty"],
                     "last_solve": r["last_solve"]} for r in rows])


@app.get("/rules")
def rules():
    return render_template("rules.html", net=NET, hold_min=max(1, round(EVENT_HOLD / 60)),
                           hint_pct=HINT_PCT, rate_wrong=RATE_WRONG, rate_window=RATE_WINDOW)


@app.route("/register", methods=["GET", "POST"])
def register():
    if not REGISTRATION_OPEN:
        flash("Team registration is closed. Ask the exercise staff for an account.", "warn")
        return redirect(url_for("login"))
    if request.method == "POST":
        name = " ".join(request.form.get("name", "").split())
        pw = request.form.get("password", "")
        pw2 = request.form.get("password2", "")
        err = None
        if not 2 <= len(name) <= 32:
            err = "Team name must be 2-32 characters."
        elif name.lower() == "admin":
            err = "That team name is reserved."
        elif len(pw) < 8:
            err = "Password must be at least 8 characters."
        elif pw != pw2:
            err = "Passwords do not match."
        if err:
            flash(err, "error")
            return render_template("register.html", name=name), 400
        db = get_db()
        try:
            cur = db.execute(
                "INSERT INTO teams (name, password_hash, created_at, created_ip) VALUES (?, ?, ?, ?)",
                (name, generate_password_hash(pw), now(), client_ip()))
            db.commit()
        except sqlite3.IntegrityError:
            flash("That team name is taken.", "error")
            return render_template("register.html", name=name), 400
        session.clear()
        session.permanent = True
        session["team_id"] = cur.lastrowid
        flash("Team %s registered. Good hunting." % name, "ok")
        return redirect(url_for("challenges"))
    return render_template("register.html", name="")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = client_ip()
        if login_throttled(ip):
            flash("Too many failed logins. Wait a minute.", "error")
            return render_template("login.html"), 429
        name = " ".join(request.form.get("name", "").split())
        pw = request.form.get("password", "")
        row = get_db().execute("SELECT id, name, password_hash FROM teams WHERE name = ?",
                               (name,)).fetchone()
        if row is None or not check_password_hash(row["password_hash"], pw):
            login_failed(ip)
            flash("Invalid team name or password.", "error")
            return render_template("login.html"), 401
        session.clear()
        session.permanent = True
        session["team_id"] = row["id"]
        nxt = request.args.get("next", "")
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = url_for("challenges")
        return redirect(nxt)
    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("scoreboard"))


@app.get("/challenges")
@team_required
def challenges():
    db = get_db()
    tid = g.team["id"]
    chals = db.execute("SELECT * FROM challenges WHERE visible = 1 ORDER BY sort_order, key").fetchall()
    solved = {r["challenge_key"]: r["solved_at"] for r in db.execute(
        "SELECT challenge_key, solved_at FROM solves WHERE team_id = ?", (tid,))}
    unlocked = defaultdict(set)
    for r in db.execute("SELECT challenge_key, hint_index FROM hint_unlocks WHERE team_id = ?", (tid,)):
        unlocked[r["challenge_key"]].add(r["hint_index"])
    counts = {r[0]: r[1] for r in db.execute(
        "SELECT challenge_key, COUNT(*) FROM solves GROUP BY challenge_key")}
    _, _, _, first_blood = compute_standings(db)

    groups = defaultdict(list)
    for c in chals:
        hints = json.loads(c["hints"] or "[]")
        groups[c["category"]].append({
            "key": c["key"], "title": c["title"], "points": c["points"], "host": c["host"],
            "description": c["description"], "solved_at": solved.get(c["key"]),
            "solves": counts.get(c["key"], 0), "blood": first_blood.get(c["key"]),
            "cost": hint_cost(c["points"]),
            "hints": [{"index": i, "text": h if i in unlocked[c["key"]] else None}
                      for i, h in enumerate(hints)],
        })
    cats = [{"name": cat, "chals": groups[cat],
             "solved": sum(1 for x in groups[cat] if x["solved_at"])}
            for cat in sort_categories(groups.keys())]
    rows, _, _, _ = compute_standings(db)
    me = next((r for r in rows if r["id"] == tid), None)
    return render_template("challenges.html", cats=cats, me=me)


@app.post("/hint/<key>/<int:idx>")
@team_required
def unlock_hint(key, idx):
    db = get_db()
    c = db.execute("SELECT key, points, hints FROM challenges WHERE key = ? AND visible = 1",
                   (key,)).fetchone()
    if c is None:
        abort(404)
    hints = json.loads(c["hints"] or "[]")
    if not 0 <= idx < len(hints):
        abort(404)
    cost = hint_cost(c["points"])
    cur = db.execute(
        "INSERT OR IGNORE INTO hint_unlocks (team_id, challenge_key, hint_index, cost, unlocked_at) "
        "VALUES (?, ?, ?, ?, ?)", (g.team["id"], key, idx, cost, now()))
    db.commit()
    if cur.rowcount:
        flash("Hint unlocked (-%d pts)." % cost, "warn")
    return redirect(url_for("challenges") + "#c-" + key)


@app.post("/submit/<key>")
@team_required
def submit(key):
    db = get_db()
    team = g.team
    raw = request.form.get("flag", "")[:512]
    anchor = url_for("challenges") + "#c-" + key
    if not raw.strip():
        flash("Enter a flag.", "warn")
        return redirect(anchor)
    with _submit_lock:
        c = db.execute("SELECT key, points, flag_sha256 FROM challenges WHERE key = ? AND visible = 1",
                       (key,)).fetchone()
        if c is None:
            abort(404)
        t = now()

        def record(result, preview=""):
            db.execute(
                "INSERT INTO submissions (team_id, team_name, challenge_key, result, correct, "
                "preview, ip, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (team["id"], team["name"], key, result, 1 if result == "correct" else 0,
                 preview, client_ip(), t))
            db.commit()

        if db.execute("SELECT 1 FROM solves WHERE team_id = ? AND challenge_key = ?",
                      (team["id"], key)).fetchone():
            record("already_solved", "[redacted]")
            flash("Your team already solved this one.", "warn")
            return redirect(anchor)

        wrong = db.execute(
            "SELECT COUNT(*) FROM submissions WHERE team_id = ? AND result = 'wrong' AND ts >= ?",
            (team["id"], t - RATE_WINDOW)).fetchone()[0]
        if wrong >= RATE_WRONG:
            record("throttled", "[not checked]")
            flash("Rate limit: %d wrong submissions per %d s. Slow down." % (RATE_WRONG, RATE_WINDOW),
                  "error")
            return redirect(anchor), 303

        if hmac.compare_digest(flag_hash(key, raw), c["flag_sha256"]):
            db.execute("INSERT OR IGNORE INTO solves (team_id, challenge_key, solved_at) VALUES (?, ?, ?)",
                       (team["id"], key, t))
            record("correct", "[correct]")
            first = db.execute("SELECT team_id FROM solves WHERE challenge_key = ? "
                               "ORDER BY solved_at, id LIMIT 1", (key,)).fetchone()
            msg = "Flag accepted: +%d pts." % c["points"]
            if first and first["team_id"] == team["id"]:
                msg += " FIRST BLOOD!"
            flash(msg, "ok")
            return redirect(anchor)

        # Wrong. Submitted text is never stored (a near-miss may contain a real
        # flag); only a short sha256 fingerprint so repeats are recognisable.
        other = None
        for o in db.execute("SELECT key, flag_sha256 FROM challenges WHERE key != ?", (key,)):
            if hmac.compare_digest(flag_hash(o["key"], raw), o["flag_sha256"]):
                other = o["key"]
                break
        if other:
            record("wrong", "[valid flag for %s]" % other)
            flash("That is a valid flag, but for a different challenge.", "warn")
        else:
            record("wrong", "sha256:" + hashlib.sha256(raw.strip().encode("utf-8")).hexdigest()[:12])
            flash("Incorrect flag.", "error")
    return redirect(anchor)


# ---------------------------------------------------------------------- admin
@app.route("/admin", methods=["GET"])
def admin():
    if not session.get("is_admin"):
        return render_template("admin_login.html", enabled=bool(ADMIN_SHA256))
    db = get_db()
    rows, _, _, _ = compute_standings(db)
    chals = db.execute(
        "SELECT c.key, c.title, c.category, c.points, c.visible, "
        "(SELECT COUNT(*) FROM solves s WHERE s.challenge_key = c.key) AS solves "
        "FROM challenges c ORDER BY c.sort_order, c.key").fetchall()
    team_filter = request.args.get("team", "").strip()
    q = "SELECT * FROM submissions"
    args = ()
    if team_filter:
        q += " WHERE team_name = ? COLLATE NOCASE"
        args = (team_filter,)
    subs = db.execute(q + " ORDER BY id DESC LIMIT 500", args).fetchall()
    return render_template("admin.html", rows=rows, chals=chals, subs=subs, team_filter=team_filter)


@app.post("/admin/login")
def admin_login():
    ip = client_ip()
    if login_throttled(ip):
        flash("Too many failed logins. Wait a minute.", "error")
        return redirect(url_for("admin"))
    user = request.form.get("username", "")
    pw = request.form.get("password", "")
    digest = hashlib.sha256(pw.encode("utf-8")).hexdigest()
    if ADMIN_SHA256 and user == "admin" and hmac.compare_digest(digest, ADMIN_SHA256):
        team_id = session.get("team_id")
        session.clear()
        if team_id is not None:
            session["team_id"] = team_id
        session["is_admin"] = True
        return redirect(url_for("admin"))
    login_failed(ip)
    flash("Invalid admin credentials.", "error")
    return redirect(url_for("admin"))


@app.post("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("scoreboard"))


@app.post("/admin/team/<int:tid>/reset")
@admin_required
def admin_reset_team(tid):
    db = get_db()
    db.execute("DELETE FROM solves WHERE team_id = ?", (tid,))
    db.execute("DELETE FROM hint_unlocks WHERE team_id = ?", (tid,))
    db.commit()
    flash("Team %d reset (solves and hint unlocks cleared; submission log kept)." % tid, "ok")
    return redirect(url_for("admin"))


@app.post("/admin/team/<int:tid>/delete")
@admin_required
def admin_delete_team(tid):
    db = get_db()
    db.execute("DELETE FROM teams WHERE id = ?", (tid,))
    db.commit()
    flash("Team %d deleted." % tid, "ok")
    return redirect(url_for("admin"))


@app.post("/admin/challenge/<key>/toggle")
@admin_required
def admin_toggle(key):
    db = get_db()
    db.execute("UPDATE challenges SET visible = 1 - visible WHERE key = ?", (key,))
    db.commit()
    return redirect(url_for("admin") + "#challenges")


def _csv(name, header, rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=%s" % name})


def _iso(ts):
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds") if ts else ""


@app.get("/admin/export/solves.csv")
@admin_required
def admin_export_solves():
    rows = get_db().execute(
        "SELECT t.name, s.challenge_key, c.category, c.points, s.solved_at FROM solves s "
        "JOIN teams t ON t.id = s.team_id LEFT JOIN challenges c ON c.key = s.challenge_key "
        "ORDER BY s.solved_at").fetchall()
    return _csv("solves.csv", ["team", "challenge", "category", "points", "solved_at"],
                [(r[0], r[1], r[2], r[3], _iso(r[4])) for r in rows])


@app.get("/admin/export/submissions.csv")
@admin_required
def admin_export_submissions():
    rows = get_db().execute(
        "SELECT ts, team_name, challenge_key, result, preview, ip FROM submissions ORDER BY id").fetchall()
    return _csv("submissions.csv", ["time", "team", "challenge", "result", "preview", "ip"],
                [(_iso(r[0]),) + tuple(r)[1:] for r in rows])


@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(405)
@app.errorhandler(413)
def _err(e):
    return render_template("error.html", code=e.code, message=e.description), e.code


# ----------------------------------------------------------------------- main
def main(argv):
    cmd = argv[1] if len(argv) > 1 else "serve"
    if cmd == "seed":
        init_db()
        print(json.dumps(seed(SEED_FILE)))
        return 0
    if cmd == "serve":
        bootstrap(do_seed=True)
        from waitress import serve
        serve(app, host=os.environ.get("WW_SCORE_HOST", "0.0.0.0"),
              port=_env_int("WW_SCORE_PORT", 80), threads=_env_int("WW_SCORE_THREADS", 8),
              ident="ww-scoreboard")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
