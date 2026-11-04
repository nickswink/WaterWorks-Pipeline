# ww_scoreboard

CTF scoreboard for the WaterWorks Pipeline range, deployed on `ww-score` (VLAN 60, port 80).
It is a Flask + SQLite app served by waitress and runs under systemd as the `ww-scoreboard` service.
Everything comes from Debian 12 apt packages: no pip, no containers, no external CDNs.

## Required variables (range.yaml `global_role_vars`)

| Var | Purpose |
|---|---|
| `ww_flags` | dict of challenge key -> flag string. The role hashes these and never writes them to disk. |
| `ww_scoreboard_admin_password` | password for `/admin` (user `admin`). Only its sha256 is stored. |
| `ww_net` | `10.<octet>`, shown on challenge cards and the rules page (optional). |
| `ww_plc_event_hold_s` | used on the rules page for the auto-restore time (optional, default 600). |

All other settings live in `defaults/main.yml`, including the challenge catalogue
(`ww_scoreboard_challenges`: titles, points, categories, descriptions and hints).

## Layout on the host

| Path | Owner / mode | Contents |
|---|---|---|
| `/opt/ww-scoreboard/` | root, 0755/0644 | app.py, templates/, static/ |
| `/etc/ww-scoreboard/challenges.json` | root:wwscore 0640 | seed file (flag sha256 hashes only) |
| `/etc/ww-scoreboard/scoreboard.env` | root:wwscore 0640 | runtime settings and the admin password hash |
| `/var/lib/ww-scoreboard/` | wwscore 0750 | `scoreboard.db` (SQLite) and the session `secret_key` |

## Seeding

The role renders `challenges.json` with `flag_sha256 = ww_flags[key] | trim | hash('sha256')`.
For `intel_*` keys the answer is upper-cased before hashing, and submissions are upper-cased too, so those answers are case-insensitive.
Then `app.py seed` upserts the challenges by key. It never deletes teams, solves or submissions, and it keeps the admin's visible/hidden setting.
The service also re-seeds when it starts.

## Operations

```
systemctl status ww-scoreboard
journalctl -u ww-scoreboard -f
sqlite3 /var/lib/ww-scoreboard/scoreboard.db 'select * from submissions order by id desc limit 20;'
```

To wipe the competition, stop the service, delete `/var/lib/ww-scoreboard/scoreboard.db*` and re-run the role.
