# ww_hmi — AquaView SCADA HMI (ww-hmi01)

Deploys the **AquaView SCADA HMI**, the SCADA master for the Cedar Ridge
Regional Transmission System. It polls the three field controllers over
Modbus/TCP, serves a token-authenticated tag API for the historian, and
presents operator screens plus a VNC "remote operator support" console.

## Services

| Service | Port | Runs as | Purpose |
|---|---|---|---|
| `aquaview-hmi.service` | 80/tcp | `aquaview` | Flask + waitress web app + background Modbus poller |
| `aquaview-xvfb.service` | — | `hydra_vendor` | Virtual framebuffer `:0` (headless, no GPU) |
| `aquaview-vnc.service` | 5900/tcp | `hydra_vendor` | fluxbox + operator-console xterm + x11vnc |

App in `/opt/aquaview`, config in `/etc/aquaview/aquaview.json`.

## Tag poller

A background thread polls each controller every `ww_hmi_poll_interval` (~2 s)
using `mbclient.ModbusClient` and caches scaled tag values. The tag catalog
(DESIGN.md §5) is built in `app.py` and maps `<SITE>.<TAG>` to
`(table, address, scale)`:

| SITE | Controller | Profile |
|---|---|---|
| `INTAKE` | ww-plc01 (`<ww_net>.50.10`) | intake / Modicon M340 |
| `WTP` | ww-plc02 (`<ww_net>.50.20`) | chemfeed / Unitronics V570 (MI→HR, MB→coils) |
| `BOOSTER` | ww-rtu03 (`<ww_net>.50.30`) | booster / SCADAPack 474 |

A controller that is down never crashes the poller: the whole site is flagged
`COMM_FAIL` and the last cached values are retained.

## SCADA tag API (historian contract)

`GET /api/v1/tags` — requires `Authorization: Bearer <ww_hmi_api_token>`
(401 otherwise). Returns:

```json
{"timestamp": "2026-10-16T12:00:00Z",
 "tags": {"WTP.FINISHED_PH": {"value": 8.0, "units": "pH",
          "quality": "GOOD", "desc": "Finished water pH"}, ...}}
```

Booleans are emitted as `0.0`/`1.0`; ASCII event buffers are emitted as strings.
This matches what `ww_historian`'s collector expects.

## Web UI

Dark SCADA theme, 5 s auto-refresh. Accounts: `controlroom` /
`ww_controlroom_password` (operator) and read-only `viewer` / `viewer`.

| Route | Page |
|---|---|
| `/login`, `/logout` | session auth |
| `/` | Overview — inline-SVG process mimic (intake→WTP→main→booster→Summit Tank), coloured by alarm |
| `/intake`, `/chemfeed`, `/booster` | per-site live tags + current alarms |
| `/alarms` | live alarm list; latched-impact `WTR{…}` event text surfaced **verbatim** |
| `/shift-log` | pinned ops note containing the `hmi_access` flag |
| `/api/v1/tags` | historian tag API (bearer) |
| `/healthz` | plaintext health probe |

## Flags

* `ww_flags.hmi_access` — rendered on the **Shift Log** web page (behind login)
  and into `/home/hydra_vendor/Desktop/Shift_Log.txt` (readable in the VNC
  console). Injected from config; not hardcoded.
* Impact flags are **not** hardcoded — they are read live from the controllers'
  event-text register blocks and shown on the Alarms page.

## VNC console

Xvfb `:0` + fluxbox + an xterm titled *"AquaView Operator Console — ww-hmi01"*
(which prints the shift log) + x11vnc on `:5900`. The password
(`ww_vnc_password`) is stored as a classic VNC DES file (truncated to 8 chars)
at `/home/hydra_vendor/.vnc/passwd`.

## Key variables

See `defaults/main.yml`. Scenario values (`ww_net`, `ww_flags`,
`ww_hmi_api_token`, `ww_controlroom_password`, `ww_vnc_password`, `ww_org_name`)
come from `global_role_vars` in `range.yaml`.
