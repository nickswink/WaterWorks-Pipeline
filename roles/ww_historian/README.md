# ww_historian

AquaHistorian 4.2 process historian for **ww-hist01** (OT DMZ, Purdue L3.5).
Debian 12 (bookworm), apt packages only (`python3-flask`, `python3-waitress`, `sqlite3`).

| Item | Value |
|---|---|
| Web UI | `http://<ww_net>.30.10:8080/` (waitress, user `aquahist`, unit `aquahist-web`) |
| Collector | unit `aquahist-collector`, polls `GET http://<ww_net>.40.10/api/v1/tags` every 5 s with `Authorization: Bearer <ww_hmi_api_token>` |
| App / data / config | `/opt/aquahist`, `/var/lib/aquahist/history.db`, `/etc/aquahist/` |

Collector contract: JSON `{"timestamp": "...", "tags": {"<SITE>.<TAG>": {"value": <num|bool|str>, "units": "...", "quality": "GOOD", "desc": "..."}}}`.
Numeric/bool values go to `samples(ts, tag, value, quality)` (bools as 0/1, 24 h retention); the latest value of every tag
(including text) goes to `current_values`. Connection failures are logged and retried; the dashboard shows COMM FAIL
and per-tag STALE / bad quality.

Seeded tables: `tags` (full register map for ww-plc01 / ww-plc02 / ww-rtu03), `users` (`guest`/`guest` viewer,
`hist_admin` and `svc_scada_ro` with random passwords), `system_config` (SCADA API URL and token, license,
`audit_token` = `ww_flags.hist_sqli`).

**Intended vulnerability (CWE-89):** `/trend?tag=` and `/export.csv?tag=` concatenate `tag` into a SQLite query
(read-only connection) and print errors verbosely. Example:
`/trend?tag=' UNION SELECT key, value FROM system_config-- -`

Required vars (global_role_vars): `ww_net`, `ww_flags`, `ww_hmi_api_token`, `ww_org_name`.
