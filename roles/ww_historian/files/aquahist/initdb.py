#!/usr/bin/env python3
"""AquaHistorian 4.2 - database initialisation / seed tool.

Creates the schema and upserts the register map, local accounts and system
configuration from a JSON seed file. Safe to run repeatedly: prints CHANGED
when anything was written, OK otherwise.
"""

import argparse
import hashlib
import json
import os
import pwd
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import connect, init_schema  # noqa: E402


def md5(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def seed(conn, data):
    changed = False

    for key, value in data.get("system_config", {}).items():
        row = conn.execute("SELECT value FROM system_config WHERE key = ?", (key,)).fetchone()
        if row is None or row[0] != value:
            if row is None:
                conn.execute("INSERT INTO system_config (key, value) VALUES (?, ?)", (key, value))
            else:
                conn.execute("UPDATE system_config SET value = ? WHERE key = ?", (value, key))
            changed = True

    for name, site, source, address, units, desc in data.get("tags", []):
        new = (site, source, address, units, desc)
        row = conn.execute("SELECT site, source, address, units, description FROM tags WHERE name = ?",
                           (name,)).fetchone()
        if row is None or tuple(row) != new:
            if row is None:
                conn.execute("INSERT INTO tags (site, source, address, units, description, name) "
                             "VALUES (?, ?, ?, ?, ?, ?)", new + (name,))
            else:
                conn.execute("UPDATE tags SET site = ?, source = ?, address = ?, units = ?, description = ? "
                             "WHERE name = ?", new + (name,))
            changed = True

    for username, password, role in data.get("users", []):
        row = conn.execute("SELECT password_md5, role FROM users WHERE username = ?", (username,)).fetchone()
        if row is None:
            # Accounts without a seeded password get a strong random one.
            pw = password if password is not None else secrets.token_urlsafe(24)
            conn.execute("INSERT INTO users (username, password_md5, role, last_login) VALUES (?, ?, ?, NULL)",
                         (username, md5(pw), role))
            changed = True
        else:
            if password is not None and row[0] != md5(password):
                conn.execute("UPDATE users SET password_md5 = ? WHERE username = ?", (md5(password), username))
                changed = True
            if row[1] != role:
                conn.execute("UPDATE users SET role = ? WHERE username = ?", (role, username))
                changed = True

    conn.commit()
    return changed


def main():
    ap = argparse.ArgumentParser(description="AquaHistorian database init/seed")
    ap.add_argument("--db", required=True)
    ap.add_argument("--seed", required=True)
    ap.add_argument("--owner", default=None, help="chown database files to this user")
    args = ap.parse_args()

    existed = os.path.exists(args.db)
    with open(args.seed, encoding="utf-8") as fh:
        data = json.load(fh)

    conn = connect(args.db)
    before = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    init_schema(conn)
    after = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    changed = seed(conn, data) or not existed or before != after
    conn.close()

    if args.owner and os.geteuid() == 0:
        pw = pwd.getpwnam(args.owner)
        for suffix in ("", "-wal", "-shm"):
            path = args.db + suffix
            if os.path.exists(path):
                st = os.stat(path)
                if (st.st_uid, st.st_gid) != (pw.pw_uid, pw.pw_gid):
                    os.chown(path, pw.pw_uid, pw.pw_gid)
                    changed = True

    print("CHANGED" if changed else "OK")


if __name__ == "__main__":
    main()
