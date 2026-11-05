#!/usr/bin/env python3
"""
WaterWorks Pipeline Co. — public utility website and contractor portal.

Customer-facing site for the Cedar Ridge Regional Transmission System:
service alerts, Consumer Confidence Reports, public notices, careers,
and a login area for contractors and staff.
"""
import json
import os
import sqlite3
import uuid
from datetime import datetime

from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    render_template_string,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

APP_ROOT = os.path.dirname(os.path.abspath(__file__))


def load_env(path):
    """Load KEY=VALUE pairs from a .env-style file into os.environ."""
    cfg = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                cfg[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return cfg


ENV = load_env(os.path.join(APP_ROOT, ".env"))

app = Flask(__name__)
app.config["SECRET_KEY"] = ENV.get("FLASK_SECRET_KEY", "change-me")
app.config["PORTAL_ADMIN_USER"] = ENV.get("PORTAL_ADMIN_USER", "webadmin")
app.config["PORTAL_ADMIN_HASH"] = ENV.get("PORTAL_ADMIN_PASSWORD_HASH", "")

# Resume uploads: cap request bodies at 25 MB so a single applicant cannot
# fill the disk. Larger uploads trigger a 413 handled gracefully below.
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

REPORTS_DIR = ENV.get("REPORTS_DIR", os.path.join(APP_ROOT, "reports"))
UPLOAD_DIR = ENV.get("WW_UPLOAD_DIR", os.path.join(APP_ROOT, "uploads"))
NOTICES_DB = os.path.join(APP_ROOT, "data", "notices.db")
STAGING_FILE = os.path.join(APP_ROOT, "content", "staging.html")

ORG_NAME = "WaterWorks Pipeline Co."
ORG_DOMAIN = "waterworkspipeline.com"


# --------------------------------------------------------------------------- #
#  Data helpers (public notices stored in sqlite)
# --------------------------------------------------------------------------- #
def db():
    conn = sqlite3.connect(NOTICES_DB)
    conn.row_factory = sqlite3.Row
    return conn


def get_notices():
    try:
        conn = db()
        rows = conn.execute(
            "SELECT id, title, body, category, published FROM notices "
            "ORDER BY id DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []


def add_notice(title, body, category):
    conn = db()
    conn.execute(
        "INSERT INTO notices (title, body, category, published) "
        "VALUES (?, ?, ?, ?)",
        (title, body, category, datetime.now().strftime("%B %d, %Y")),
    )
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------- #
#  Context available to every template (footer, branding, nav)
# --------------------------------------------------------------------------- #
@app.context_processor
def inject_globals():
    return {
        "org_name": ORG_NAME,
        "org_domain": ORG_DOMAIN,
        "current_year": datetime.now().year,
    }


# --------------------------------------------------------------------------- #
#  Public pages
# --------------------------------------------------------------------------- #
@app.route("/")
def home():
    notices = get_notices()[:3]
    return render_template("home.html", notices=notices)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/water-quality")
def water_quality():
    return render_template("water_quality.html")


@app.route("/notices")
def notices():
    return render_template("notices.html", notices=get_notices())


@app.route("/careers")
def careers():
    return render_template("careers.html")


# --------------------------------------------------------------------------- #
#  Careers: public resume drop (HR review queue)
# --------------------------------------------------------------------------- #
def _safe_upload_name(name):
    """Reduce an uploaded filename to a safe basename, preserving extension.

    Uses werkzeug.secure_filename to strip directories and traversal. If the
    sanitized name is empty (e.g. the original was all unsafe characters),
    fall back to a generated name while keeping the original extension.
    """
    base = os.path.basename(name or "")
    safe = secure_filename(base)
    if not safe:
        _, ext = os.path.splitext(base)
        ext = ext if ext else ".bin"
        safe = "resume-%s%s" % (uuid.uuid4().hex[:8], ext)
    return safe


def _unique_path(directory, name):
    """Return a path inside directory that does not yet exist.

    If name is already taken, append -1, -2, ... before the extension so
    multiple applications coexist rather than overwriting each other.
    """
    candidate = os.path.join(directory, name)
    if not os.path.exists(candidate):
        return candidate
    stem, ext = os.path.splitext(name)
    i = 1
    while True:
        candidate = os.path.join(directory, "%s-%d%s" % (stem, i, ext))
        if not os.path.exists(candidate):
            return candidate
        i += 1


def _resolve_upload(name):
    """Resolve a requested upload name to an absolute path inside UPLOAD_DIR.

    Returns None if the name escapes the uploads directory (path traversal).
    """
    base = os.path.basename(name or "")
    if not base or base in (".", ".."):
        return None
    uploads_root = os.path.realpath(UPLOAD_DIR)
    target = os.path.realpath(os.path.join(uploads_root, base))
    if target != uploads_root and os.path.commonpath([uploads_root, target]) != uploads_root:
        return None
    if target == uploads_root:
        return None
    return target


@app.route("/careers/apply", methods=["POST"])
def careers_apply():
    """Accept a resume upload from the public careers page and store it."""
    upload = request.files.get("resume")
    applicant = request.form.get("name", "").strip()
    if upload is None or not upload.filename:
        flash("Please attach a resume file before submitting your application.")
        return redirect(url_for("careers"))

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    name = _safe_upload_name(upload.filename)
    dest = _unique_path(UPLOAD_DIR, name)
    upload.save(dest)

    return render_template(
        "apply_confirm.html",
        applicant=applicant,
        stored_name=os.path.basename(dest),
    )


@app.route("/careers/inbox.json")
def careers_inbox():
    """List every resume currently in the uploads directory, newest first."""
    files = []
    try:
        for entry in os.listdir(UPLOAD_DIR):
            full = os.path.join(UPLOAD_DIR, entry)
            if not os.path.isfile(full):
                continue
            st = os.stat(full)
            files.append(
                {
                    "name": entry,
                    "size": int(st.st_size),
                    "mtime": int(st.st_mtime),
                }
            )
    except OSError:
        files = []
    files.sort(key=lambda f: f["mtime"], reverse=True)
    return Response(
        json.dumps({"files": files}), mimetype="application/json"
    )


@app.route("/careers/files/<path:name>")
def careers_file(name):
    """Stream the raw bytes of a stored resume as an attachment."""
    target = _resolve_upload(name)
    if target is None or not os.path.isfile(target):
        abort(404)
    return send_file(
        target,
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=os.path.basename(target),
    )


@app.errorhandler(413)
def too_large(_err):
    """Return a friendly message when an upload exceeds MAX_CONTENT_LENGTH."""
    return (
        render_template("apply_too_large.html"),
        413,
    )


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        flash(
            "Thank you. Your message has been received; Customer Service will "
            "respond within one business day."
        )
        return redirect(url_for("contact"))
    return render_template("contact.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# --------------------------------------------------------------------------- #
#  Consumer Confidence Report downloads
# --------------------------------------------------------------------------- #
@app.route("/reports/download")
def reports_download():
    """Serve a requested CCR report file from the reports directory."""
    file = request.args.get("file", "")
    if not file:
        abort(400)
    # Build the path to the requested report and stream it back.
    path = REPORTS_DIR + "/" + file
    try:
        fh = open(path, "rb")
    except (OSError, IsADirectoryError):
        abort(404)
    data = fh.read()
    fh.close()
    filename = os.path.basename(file) or "report.txt"
    resp = Response(data, mimetype="text/plain")
    resp.headers["Content-Disposition"] = (
        "attachment; filename=\"%s\"" % filename
    )
    return resp


# --------------------------------------------------------------------------- #
#  Crawler directives + staging
# --------------------------------------------------------------------------- #
@app.route("/robots.txt")
def robots():
    body = (
        "User-agent: *\n"
        "Disallow: /staging/\n"
        "Disallow: /reports/archive/\n"
        "Disallow: /portal/\n"
        "Sitemap: https://%s/sitemap.xml\n" % ORG_DOMAIN
    )
    return Response(body, mimetype="text/plain")


@app.route("/staging/")
@app.route("/staging/index.html")
def staging():
    try:
        with open(STAGING_FILE, "r", encoding="utf-8") as fh:
            return Response(fh.read(), mimetype="text/html")
    except OSError:
        abort(404)


# --------------------------------------------------------------------------- #
#  Contractor / staff portal
# --------------------------------------------------------------------------- #
@app.route("/portal/login", methods=["GET", "POST"])
def portal_login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        admin_user = app.config["PORTAL_ADMIN_USER"]
        admin_hash = app.config["PORTAL_ADMIN_HASH"]
        if (
            username == admin_user
            and admin_hash
            and check_password_hash(admin_hash, password)
        ):
            session["user"] = username
            session["role"] = "admin"
            return redirect(url_for("portal_admin"))
        flash("Invalid credentials. Contact IT if you need portal access.")
    return render_template("portal_login.html")


@app.route("/portal/logout")
def portal_logout():
    session.clear()
    return redirect(url_for("portal_login"))


@app.route("/portal/admin", methods=["GET", "POST"])
def portal_admin():
    if session.get("role") != "admin":
        return redirect(url_for("portal_login"))

    preview_html = None
    if request.method == "POST":
        title = request.form.get("title", "")
        category = request.form.get("category", "General")
        body = request.form.get("body", "")
        action = request.form.get("action", "preview")
        if action == "publish":
            add_notice(title, body, category)
            flash("Notice published to the public notices page.")
            return redirect(url_for("notices"))
        # Preview: render the notice body as the public page will show it.
        template = (
            "<div class=\"notice-preview\">"
            "<h3>" + title + "</h3>"
            "<p class=\"notice-meta\">Category: " + category + "</p>"
            "<div class=\"notice-body\">" + body + "</div>"
            "</div>"
        )
        preview_html = render_template_string(template)

    return render_template(
        "portal_admin.html",
        user=session.get("user"),
        preview_html=preview_html,
    )


if __name__ == "__main__":
    # Development only. In production the app is served by waitress.
    app.run(host="127.0.0.1", port=8000, debug=False)
