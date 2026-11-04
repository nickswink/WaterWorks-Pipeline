#!/usr/bin/env python3
"""Initialize the public notices database. Idempotent: creates the schema if
needed and seeds starter notices only when the table is empty."""
import os
import sqlite3
import sys

DB = sys.argv[1] if len(sys.argv) > 1 else "/opt/wwp-portal/data/notices.db"

SEED = [
    (
        "Planned Main Flushing - Summit & Hilltop Service Areas",
        "Scheduled uni-directional flushing of transmission and distribution "
        "mains serving the Summit and Hilltop pressure zones begins the week of "
        "the 20th and continues for approximately five business days. Customers "
        "may experience temporary discoloration or lower pressure. Running cold "
        "water for 2 to 3 minutes should clear any discoloration. Avoid washing "
        "light-colored laundry during active flushing in your area.",
        "Flushing",
        "May 12, 2026",
    ),
    (
        "2025 Consumer Confidence Report Now Available",
        "Our 2025 Annual Water Quality Report (Consumer Confidence Report) is "
        "now available on the Water Quality page. The report confirms that "
        "Cedar Ridge water met or exceeded all state and federal drinking water "
        "standards during 2025.",
        "General",
        "April 1, 2026",
    ),
    (
        "Hydrant Maintenance - Riverside District",
        "Field crews will perform annual hydrant inspection and maintenance in "
        "the Riverside District through the end of the month. Brief, localized "
        "discoloration is possible near active work. No interruption of service "
        "is anticipated.",
        "General",
        "March 18, 2026",
    ),
]

os.makedirs(os.path.dirname(DB), exist_ok=True)
conn = sqlite3.connect(DB)
conn.execute(
    "CREATE TABLE IF NOT EXISTS notices ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "title TEXT NOT NULL,"
    "body TEXT NOT NULL,"
    "category TEXT NOT NULL,"
    "published TEXT NOT NULL)"
)
count = conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
if count == 0:
    conn.executemany(
        "INSERT INTO notices (title, body, category, published) "
        "VALUES (?, ?, ?, ?)",
        SEED,
    )
    conn.commit()
    print("seeded %d notices" % len(SEED))
else:
    print("notices table already populated (%d rows); no changes" % count)
conn.close()
