"""AquaHistorian 4.2 - shared configuration and database helpers."""

import configparser
import os
import sqlite3

PRODUCT = "AquaHistorian"
DEFAULT_CONF = "/etc/aquahist/aquahist.conf"

# The seeded tables (tags, users, system_config) deliberately have no key
# index; initdb.py keeps names unique. (Legacy 3.x schema.)
SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
    ts      INTEGER NOT NULL,
    tag     TEXT    NOT NULL,
    value   REAL,
    quality TEXT
);
CREATE INDEX IF NOT EXISTS idx_samples_tag_ts ON samples(tag, ts);
CREATE INDEX IF NOT EXISTS idx_samples_ts ON samples(ts);

CREATE TABLE IF NOT EXISTS current_values (
    tag         TEXT PRIMARY KEY,
    ts          INTEGER,
    value,
    quality     TEXT,
    units       TEXT,
    description TEXT
);

CREATE TABLE IF NOT EXISTS tags (
    name        TEXT NOT NULL,
    site        TEXT,
    source      TEXT,
    address     TEXT,
    units       TEXT,
    description TEXT
);

CREATE TABLE IF NOT EXISTS users (
    username     TEXT NOT NULL,
    password_md5 TEXT NOT NULL,
    role         TEXT NOT NULL,
    last_login   TEXT
);

CREATE TABLE IF NOT EXISTS system_config (
    key   TEXT NOT NULL,
    value TEXT
);

CREATE TABLE IF NOT EXISTS collector_status (
    id                   INTEGER PRIMARY KEY CHECK (id = 1),
    last_attempt         INTEGER,
    last_success         INTEGER,
    consecutive_failures INTEGER DEFAULT 0,
    last_error           TEXT,
    tags_last_poll       INTEGER DEFAULT 0
);
"""

DEFAULTS = {
    "server": {
        "listen": "0.0.0.0",
        "port": "8080",
        "threads": "8",
        "secret_key_file": "/etc/aquahist/secret_key",
    },
    "database": {"path": "/var/lib/aquahist/history.db"},
    "product": {"version": "4.2.1", "build": "4.2.1"},
}


def load_config(path=None):
    """Return the parsed INI configuration as a ConfigParser."""
    cp = configparser.ConfigParser(interpolation=None)
    cp.read_dict(DEFAULTS)
    cp.read(path or os.environ.get("AQUAHIST_CONF", DEFAULT_CONF))
    return cp


def connect(db_path, readonly=False):
    """Open the historian database (WAL, busy timeout)."""
    if readonly:
        conn = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True,
                               timeout=10, check_same_thread=False)
    else:
        conn = sqlite3.connect(db_path, timeout=10, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init_schema(conn):
    conn.executescript(SCHEMA)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("INSERT OR IGNORE INTO collector_status (id, consecutive_failures, tags_last_poll) "
                 "VALUES (1, 0, 0)")
    conn.commit()


def system_config(conn):
    return {k: v for k, v in conn.execute("SELECT key, value FROM system_config")}
