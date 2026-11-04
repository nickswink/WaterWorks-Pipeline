# ww_plc — Cedar Ridge field controller runtime

Deploys `wwplc.py`, a dependency-free Python runtime that emulates one field
controller with a real process-physics model and native industrial protocols.
Used by `ww-plc01`, `ww-plc02`, and `ww-rtu03`.

## Profiles (`ww_plc_site`)

| Site | Profile | Protocols | Flags produced |
|------|---------|-----------|----------------|
| `intake` | Modicon M340 | Modbus/TCP 502 (+ FC43 Device ID) | `plc01_devid`, `impact_drypump` |
| `chemfeed` | Unitronics Vision V570 | Modbus/TCP 502 **+ PCOM/TCP 20256** | `plc02_pcom`, `impact_naoh`, `impact_deface` |
| `booster` | SCADAPack 474 | Modbus/TCP 502 | `impact_overflow`, `impact_mainbreak` |

Full register maps, physics, and the exact write sequences that trigger each
impact are documented in `docs/DESIGN.md` §5.

## Behaviour

* A fixed-period scan task (default 100 ms) runs the hydraulic / chemical model.
* Holding registers, coils, discrete inputs, and input registers behave like a
  real PLC: setpoints are writable, process variables are computed, protective
  interlocks defend the process unless an attacker explicitly defeats them.
* When an impact condition is met, the controller latches the event, writes the
  corresponding `WTR{...}` flag into an event-text register block (ASCII), and
  raises it on the HMI alarm banner. After `ww_plc_event_hold_s` seconds
  (default 600) the simulated plant is "repaired" to engineered defaults so the
  challenge is replayable.

## Key variables

See `defaults/main.yml`. Flags and `ww_plc_event_hold_s` come from
`global_role_vars` in `range.yaml`; `ww_rtu03_maint_key` sets the booster
maintenance key (HR 20).

## Service

`wwfield.service` (systemd), running as the unprivileged `wwfield` account with
only `CAP_NET_BIND_SERVICE`. Logs at `/var/log/wwfield/controller.log`.
