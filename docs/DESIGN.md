# WaterWorks Pipeline Range — Builder's Design Spec

> **Spoilers.** This is the single source of truth for range builders: every
> IP, account, password, flag location, and PLC register used by the roles.
> Players should read `README.md` instead.

## 1. Scenario

**WaterWorks Pipeline Co. (WWP)** is a fictional regional water wholesaler that
owns the **Cedar Ridge Regional Transmission System**:

```
Cedar River ──► Intake PS-1 ──24" raw main──► Cedar Ridge WTP ──16" transmission main──► Hilltop Booster PS-3 ──► Summit Elevated Tank ──► 4 member towns
               (PLC01, M340)                 (PLC02, Vision V570                       (RTU03, SCADAPack 474)      (1.0 MG, 40 ft)
                3 x 3 MGD pumps               chem feed: NaOH + Cl2)                    2 booster pumps, FCV-301,
                                                                                         SAV-301 surge valve
```

- Public domain: `waterworkspipeline.com`; internal DNS suffix: `wwp.local`
- HQ: 410 Riverside Dr, Cedar Ridge. Hilltop Booster PS-3: **8042 Hilltop Rd**.
- System integrator / OT vendor: **Hydra Controls Integration LLC** (`hydra_vendor`).
- Timezone: `America/Chicago`.

### People

| Name | Username | Role | Notes |
|---|---|---|---|
| Dana Whitfield | `d.whitfield` | IT Manager | SSH key from ww-it01 → ww-jump01 |
| Marcus Oyelaran | `m.oyelaran` | SCADA / Controls Engineer | owns PLC project files on ww-eng01 |
| Priya Raman | `p.raman` | Control Room Operator (lead) | uses shared `controlroom` login |
| Tom Kessler | `t.kessler` | Plant Superintendent | |
| Jordan Alvarez | `j.alvarez` | Helpdesk Technician (hired 2026-09-08) | still on new-hire default password |
| Amanda Wallace | `a.wallace` | HR reviewer (ww-ws01 Windows) | auto-logged-on; opens uploaded resumes |
| Elena Brooks | `e.brooks` | Water Quality Manager | publishes CCR reports |
| Ray Castillo | `r.castillo` | Field Technician, Pump Stations | |
| Hydra Controls | `hydra_vendor` | Vendor remote support account | |
| Service account | `svc_ccrsync` | Syncs CCR reports from FS01 to the website | over-permissioned |

## 2. Network (Purdue-aligned)

`X` = Ludus range second octet (`{{ range_second_octet }}`).

| VLAN | Subnet | Zone (Purdue) | Hosts |
|---|---|---|---|
| 10 | 10.X.10.0/24 | Internet DMZ (L5/DMZ) | ww-web01 .10 |
| 20 | 10.X.20.0/24 | Corporate IT (L4) | ww-fs01 .10, ww-it01 .20, **ww-ws01 .30 (Windows HR workstation)** |
| 30 | 10.X.30.0/24 | OT DMZ (L3.5) | ww-hist01 .10, ww-jump01 .20 |
| 40 | 10.X.40.0/24 | SCADA Control Center (L2/L3) | ww-hmi01 .10, ww-eng01 .20 |
| 50 | 10.X.50.0/24 | Field Controllers (L1) | ww-plc01 .10, ww-plc02 .20, ww-rtu03 .30 |
| 60 | 10.X.60.0/24 | Range services (out of scope) | ww-score .10 |

### Allowed flows (everything else inter-VLAN is REJECTed)

| # | Source | Destination | Ports | Business justification |
|---|---|---|---|---|
| 1 | WireGuard (players) | VLAN 10, VLAN 60 | any | "Internet" + scoreboard |
| 2 | ww-web01 | WireGuard | any | DMZ host egress (reverse shells/C2) |
| 2b | ww-ws01 (.20.30) | WireGuard | any | phishing beacon egress (C2) |
| 3 | ww-web01 | ww-fs01 | tcp/445 | CCR report sync (cifs mount) |
| 4 | ww-web01 | VLAN 20 | tcp/22 | **stale** "CHG-2023-114 temp migration" rule |
| 5 | VLAN 20 | ww-web01 | tcp/22,80 | staff manage website |
| 6 | VLAN 20 | ww-hist01 | tcp/8080 | trend viewing from the office |
| 7 | ww-it01 | ww-jump01 | tcp/22 | IT admin → OT jump host |
| 8 | ww-hist01 | ww-hmi01 | tcp/80 | historian collects tags from SCADA API |
| 9 | ww-jump01 | ww-hmi01 | tcp/80,5900 | remote HMI support (web + VNC) |
| 10 | ww-jump01 | ww-eng01 | tcp/22 | remote engineering |
| 11 | ww-hmi01 | VLAN 50 | tcp/502 | SCADA polling (Modbus/TCP) |
| 12 | ww-eng01 | VLAN 50 | tcp/502,20256 | engineering (Modbus/TCP + PCOM) |

Internal VLANs (20-50) cannot open connections to WireGuard clients
(`wireguard_vlan_default: REJECT`), **except ww-ws01 (.20.30), which may beacon
out** (flow 2b). Players must use forward connections and tunnels
(SSH -L/-D/-J, ligolo-ng, chisel) through their footholds.

### Initial-access paths (two parallel entries)

1. **Web (DMZ):** exploit ww-web01 (traversal → SSTI → root) as documented below.
2. **Phishing (Windows):** the public **Careers** page on ww-web01 accepts resume
   uploads (`POST /careers/apply`, unauthenticated). The HR workstation **ww-ws01**
   auto-logs-on as `a.wallace` and runs an "HR Resume Intake" scheduled task that
   polls `GET http://10.X.10.10/careers/inbox.json`, downloads each new file to
   Downloads, strips Mark-of-the-Web (`Unblock-File`), and **opens it with
   `Start-Process` (ShellExecute = a real double-click)** — detonating any
   double-clickable payload (`.exe/.scr/.vbs/.bat/.cmd/.hta/.lnk/.js`) in the
   user's session. Operators bring their own payload/C2; the beacon egresses over
   WireGuard (flow 2b). ww-ws01 sits in Corporate IT (VLAN 20), so a beacon there
   reaches `ww-fs01`/`ww-it01` on the same subnet with no firewall in the way —
   a deeper foothold than the DMZ. Defender + SmartScreen are disabled on ws01 so
   BYO payloads run. Reward: `foothold_phish` on `a.wallace`'s Desktop.

   Careers drop contract (served by ww-web01, consumed by ww-ws01):
   `POST /careers/apply` (field `resume`, any extension kept) →
   `GET /careers/inbox.json` (`{"files":[{name,size,mtime}]}`) →
   `GET /careers/files/<name>` (raw bytes). Uploads stored in
   `/opt/wwp-portal/uploads`, never executed on web01.

## 3. Credentials

| Where | Account | Secret | Found at |
|---|---|---|---|
| ww-web01 portal | `webadmin` (admin role) | random, not intended to be cracked | — (session forged with leaked `SECRET_KEY`) |
| ww-web01 | Flask `SECRET_KEY` | `ww_portal_secret_key` | `/opt/wwp-portal/.env` via LFI |
| ww-web01 → ww-fs01 | `svc_ccrsync` | `ww_ccrsync_password` (`CCRsync#Feb2019`) | `/root/.smbcredentials-ccr` |
| ww-it01 | `j.alvarez` | `ww_newhire_password` (`WaterWorks2026!`) | pattern in FS01 `Public/IT_Helpdesk/New_Hire_IT_Checklist.txt` + hire date in `Staff_Directory.csv` |
| ww-ws01 | `a.wallace` | `ww_ws_victim_password` (`Autumn2026!Review`) | autologon (Winlogon registry); not needed to attack — the beacon runs as this user |
| ww-it01 → ww-jump01 | `d.whitfield` | ed25519 key (no passphrase) | `/home/d.whitfield/.ssh/id_ed25519` (root needed) |
| ww-jump01 | `hydra_vendor` | via `sudo -u hydra_vendor less /opt/hydra/logs/*` escape | `sudo -l` as d.whitfield |
| ww-jump01 → ww-eng01 | `hydra_vendor` | ed25519 key | `/home/hydra_vendor/.ssh/id_ed25519` |
| ww-hmi01 VNC :5900 | (VNC auth) | `ww_vnc_password` (`Cedar201` — shared pw truncated to 8 chars by VNC DES) | `/home/hydra_vendor/.vnc/passwd` (fixed-key DES) |
| ww-hmi01 web | `controlroom` | `ww_controlroom_password` (`Cedar2019!`) | `/home/hydra_vendor/notes/site_contacts.txt` |
| ww-hist01 web | `guest` | `guest` (vendor default, read-only) | login page hint |
| ww-hist01 SCADA API | bearer token | `ww_hmi_api_token` | historian `system_config` table (SQLi) |
| ww-rtu03 | maintenance key (HR 40021) | `ww_rtu03_maint_key` (`8042`) | `HILLTOP_RTU03_main.st` on ww-eng01 (root), or OSINT (station street number) |
| ww-score | `admin` | `ww_scoreboard_admin_password` | SETUP.md |

## 4. Flags

Format `WTR{...}`. Values live **only** in `range.yaml → global_role_vars.ww_flags`.

| Key | Pts | Category | Host | Location / trigger |
|---|---|---|---|---|
| `foothold_phish` | 150 | Initial Access | ww-ws01 | `C:\Users\a.wallace\Desktop\flag.txt` (after the uploaded "resume" detonates and you have the beacon) |
| `web_recon` | 50 | Recon | ww-web01 | HTML comment on `/staging/` (disallowed in robots.txt) |
| `web_lfi` | 100 | Initial Access | ww-web01 | `/opt/wwp-portal/.env` via `/reports/download?file=` traversal |
| `web_rce` | 150 | Initial Access | ww-web01 | `/home/wwp-web/flag.txt` (SSTI in admin notice preview) |
| `web_root` | 150 | Privilege Escalation | ww-web01 | `/root/flag.txt` (`sudo rsync`) |
| `fs_engineering` | 150 | Lateral Movement | ww-fs01 | `\\ww-fs01\Engineering\Network\WWP_Network_Overview.txt` (document control ID) |
| `it_spray` | 150 | Lateral Movement | ww-it01 | `/home/j.alvarez/flag.txt` |
| `it_root` | 150 | Privilege Escalation | ww-it01 | `/root/flag.txt` (group-writable root cron script) |
| `hist_sqli` | 200 | OT DMZ | ww-hist01 | `system_config` row `audit_token` via SQLi in `/trend?tag=` |
| `jump_vendor` | 200 | Lateral Movement | ww-jump01 | `/home/hydra_vendor/flag.txt` |
| `hmi_access` | 200 | OT Access | ww-hmi01 | HMI "Shift Log" page (VNC or web login) |
| `eng_root` | 250 | Privilege Escalation | ww-eng01 | `/root/flag.txt` (SUID `projbackup` PATH hijack) |
| `plc01_devid` | 150 | OT Recon | ww-plc01 | Modbus FC43 Read Device ID, object 0x06 UserApplicationName |
| `plc02_pcom` | 200 | OT Recon | ww-plc02 | PCOM `RW` read of MI 3000-3023 (not mapped to Modbus) |
| `impact_drypump` | 300 | Impact | ww-plc01 | Intake pump dry-run ≥10 s → HR 9000-9023 |
| `impact_naoh` | 300 | Impact | ww-plc02 | Finished-water pH ≥ 11.00 for 5 s → MI 930-953 |
| `impact_deface` | 250 | Impact | ww-plc02 | Panel message (MI 900-923) changed → MI 960-983 |
| `impact_overflow` | 300 | Impact | ww-rtu03 | Summit Tank ≥ 38.0 ft for 5 s → HR 9000-9023 |
| `impact_mainbreak` | 500 | Impact | ww-rtu03 | Transient pressure ≥ 240 psi → HR 9032-9055 |
| `intel_oldsmar` | 50 | Intel | — | `WTR{11100}` (NaOH ppm set at Oldsmar, 2021) |
| `intel_pcom` | 50 | Intel | — | `WTR{20256}` (Unitronics PCOM TCP port) |
| `intel_attack` | 50 | Intel | — | `WTR{T0836}` (ATT&CK for ICS: Modify Parameter) |

Impact flags are written into PLC memory as ASCII (2 chars/register,
high byte first, NUL padded) only when the physical condition occurs; they are
also shown on the HMI alarm banner. Events latch for `ww_plc_event_hold_s`
(default 600 s), after which the simulated plant is "repaired" and restored to
its engineered defaults.

## 5. PLC register maps

All Modbus addresses are **0-based protocol addresses**; documentation
notation adds 1 (e.g. HR 0 = 40001, IR 0 = 30001, coil 0 = 00001, DI 0 = 10001).
Scaled values are unsigned 16-bit integers.

### ww-plc01 — Cedar River Intake PS-1 (Modicon M340 profile), Modbus/TCP 502, unit 1

| Table | Addr | Tag | Units / values | Default |
|---|---|---|---|---|
| Coil | 0,1,2 | P101/P102/P103_HAND_RUN | 0/1 (only in HAND) | 0 |
| Coil | 10 | LL_PROTECT_EN | wet-well low-low pump protection | 1 |
| Coil | 11 | ALARM_RESET | momentary | 0 |
| DI | 0,1,2 | P10x_RUNNING | | |
| DI | 3,4,5 | P10x_FAULT | damaged / tripped | |
| DI | 8 | WW_LEVEL_HH | | |
| DI | 9 | WW_LEVEL_LL | | |
| IR | 0 | WW_LEVEL | ft ×100 | ~1200 |
| IR | 1 | RIVER_INFLOW | MGD ×100 | ~500 |
| IR | 2 | PUMP_FLOW | MGD ×100 | |
| IR | 3,4,5 | P10x_AMPS | A ×10 | ~860 running |
| IR | 6 | HEADER_PRESS | psi ×10 | ~550 |
| IR | 7 | RAW_TURBIDITY | NTU ×100 | |
| IR | 8,9,10 | P10x_VIBRATION | mm/s ×10 | ~25; >110 when cavitating |
| IR | 11 | GATE_POS | % ×10 | 1000 |
| HR | 0,1,2 | P10x_MODE | 0 OFF, 1 HAND, 2 AUTO | 2,2,0 |
| HR | 10 | LEAD_START | ft ×100 | 1200 |
| HR | 11 | LAG_START | ft ×100 | 1400 |
| HR | 12 | LEAD_STOP | ft ×100 | 600 |
| HR | 13 | LAG_STOP | ft ×100 | 1000 |
| HR | 14 | LL_TRIP | ft ×100 | 300 |
| HR | 15 | GATE_SP | % ×10 | 1000 |
| HR | 100 | HEARTBEAT | counter | |
| HR | 9000-9023 | EVENT_TEXT | ASCII | 0 |

Device ID (FC43/0x0E): VendorName `Schneider Electric`, ProductCode `BMX P34 2020`,
Revision `v3.40`, VendorUrl `www.se.com`, ProductName `Modicon M340`,
ModelName `BMX P34 2020`, UserApplicationName `CEDAR_INTAKE_PS1 <flag plc01_devid>`.
FC17 Report Server ID returns `CEDAR RIVER INTAKE PS-1 M340`.

Dry-run: a running pump with wet-well level < 2.00 ft accumulates cavitation
time; ≥ 10 s → pump damaged → `impact_drypump`. Requires `LL_PROTECT_EN=0`
(otherwise pumps trip at LL_TRIP) and pumps in HAND (AUTO stops at LEAD_STOP).

### ww-plc02 — Cedar Ridge WTP Chemical Feed (Unitronics Vision V570 profile)

Modbus/TCP 502 unit 1 maps **MI 0-999 → HR 0-999** and **MB 0-999 → coils 0-999**.
PCOM/TCP 20256 (ASCII, protocol 101) reaches **MI/MB 0-4095**.

| Op | Addr | Tag | Units | Default |
|---|---|---|---|---|
| MI | 0 | PLANT_FLOW | MGD ×100 | ~500 |
| MI | 1 | NAOH_DOSE_SP | ppm | 100 |
| MI | 2 | NAOH_DOSE_PV | ppm | |
| MI | 3 | FINISHED_PH | pH ×100 | ~800 |
| MI | 4 | NAOH_PUMP_SPEED | % ×10 | |
| MI | 5 | CL2_DOSE_SP | mg/L ×100 | 150 |
| MI | 6 | CL2_RESIDUAL | mg/L ×100 | |
| MI | 7 | CLEARWELL_LEVEL | ft ×100 | |
| MI | 8 | RAW_PH | pH ×100 | ~680 |
| MI | 9 | NAOH_TANK_LEVEL | % ×10 | |
| MI | 10 | PH_HI_SP | pH ×100 | 850 |
| MI | 11 | PH_HIHI_SP | pH ×100 | 950 |
| MI | 12 | DOSE_MODE | 0 OFF, 1 MANUAL, 2 AUTO | 2 |
| MI | 20 | HEARTBEAT | | |
| MI | 900-923 | PANEL_MSG | ASCII (48 chars) | `CEDAR RIDGE WTP - CHEMICAL FEED` |
| MI | 930-953 | EVENT_A_TEXT | ASCII (NaOH event) | |
| MI | 960-983 | EVENT_B_TEXT | ASCII (defacement event) | |
| MI | 3000-3023 | COMMISSIONING_NOTE | ASCII (`plc02_pcom` flag) | |
| MB | 0 | NAOH_PUMP_EN | | 1 |
| MB | 1 | CL2_FEED_EN | | 1 |
| MB | 2 | PH_HIHI_CUTOUT_EN | stops NaOH pump at PH_HIHI_SP | 1 |
| MB | 3 | ALARM_RESET | momentary | 0 |
| DI | 0 | NAOH_PUMP_RUNNING | | |
| DI | 1 | PH_HI_ALARM | | |
| DI | 2 | PH_HIHI_ALARM | | |
| DI | 3 | PLC_RUN | 1 = RUN, 0 = STOP | |

pH model: `target = RAW_PH + 2.2·log10(1 + dose/40)` (100 ppm → ≈8.0;
11,100 ppm → ≈12.2), first-order lag τ = 12 s. Requires disabling
`PH_HIHI_CUTOUT_EN` **and** a setpoint the HMI refuses (HMI limit 0-200 ppm).
PCOM `CCS` stops the PLC (outputs de-energize, memory frozen); auto-`CCR`
after the event hold time.

### ww-rtu03 — Hilltop Booster PS-3 + Summit Tank (SCADAPack 474 profile), Modbus/TCP 502, unit 1

`[P]` = protective setting: the RTU logic restores the engineered value every
scan unless maintenance mode is active.

| Table | Addr | Tag | Units | Default |
|---|---|---|---|---|
| Coil | 0,1 | P301/P302_HAND_RUN | | 0 |
| Coil | 10 | HP_TRIP_EN [P] | pump high-discharge-pressure trip | 1 |
| Coil | 11 | HL_CUTOFF_EN [P] | tank high-level pump cutoff | 1 |
| Coil | 12 | SAV_ARMED [P] | surge anticipator valve SAV-301 | 1 |
| Coil | 13 | ALARM_RESET | momentary | 0 |
| DI | 0,1 | P30x_RUNNING | | |
| DI | 2 | HP_TRIP_ACTIVE | | |
| DI | 3 | TANK_HH | | |
| DI | 4 | TANK_OVERFLOW | | |
| DI | 5 | SAV_OPEN | | |
| DI | 6 | MAINT_BYPASS_ACTIVE | | |
| DI | 7 | MAIN_BREAK | | |
| IR | 0 | SUCTION_PRESS | psi ×10 | ~450 |
| IR | 1 | DISCH_PRESS | psi ×10 (incl. transient) | |
| IR | 2 | FLOW | gpm | |
| IR | 3 | FCV301_POS | % ×10 | |
| IR | 4 | TANK_LEVEL | ft ×100 | ~2800 |
| IR | 5 | TANK_DEMAND | gpm | |
| IR | 6 | PEAK_TRANSIENT_60S | psi ×10 | |
| IR | 7 | MAINT_LOCKOUT_S | seconds remaining | |
| HR | 0,1 | P30x_MODE | 0 OFF, 1 HAND, 2 AUTO | 2,2 |
| HR | 2 | FCV301_SP | % ×10 | 1000 |
| HR | 3 | FCV301_SLEW [P] | %/s ×10 | 20 |
| HR | 10 | LEAD_START | ft ×100 | 2200 |
| HR | 11 | LEAD_STOP | ft ×100 | 3300 |
| HR | 12 | LAG_START | ft ×100 | 1900 |
| HR | 13 | HL_CUTOFF_SP [P] | ft ×100 | 3500 |
| HR | 14 | HP_TRIP_SP [P] | psi ×10 | 1400 |
| HR | 20 | MAINT_KEY | write key → maintenance mode 900 s; reads 0 | |
| HR | 21 | MAINT_MODE | 1 = active (read only) | 0 |
| HR | 22 | MAINT_TIMER | s remaining | |
| HR | 100 | HEARTBEAT | | |
| HR | 9000-9023 | EVENT_A_TEXT | overflow | |
| HR | 9032-9055 | EVENT_B_TEXT | main break | |

Maintenance key lockout: 5 wrong keys within 60 s → 120 s lockout.

Hydraulics (16" DI main, wave speed a = 1100 m/s, L = 4,023 m, critical
period 2L/a = 7.3 s; pumps H0 = 110 psi shutoff, 3,000 gpm runout each):

- Steady discharge with valve closed = 45 + 110 = 155 psi (HP trip at 140).
- Valve-closure surge = Joukowsky ΔP = ρ·a·Δv summed over the last 7.3 s
  (equivalent to Michaud for slow closures). Full closure at 2 %/s ≈ +37 psi;
  in ≤ 7 s ≈ +218 psi.
- SAV-301 armed clamps transients at 165 psi.
- The 1962 cast-iron Miller Creek crossing fails at ≥ 240 psi → main break.
- Main break requires: maint key, `HP_TRIP_EN=0`, `SAV_ARMED=0`,
  `FCV301_SLEW` raised (≥ ~50 = 5 %/s), pumps running, fast valve close.
- Overflow requires: maint key, `HL_CUTOFF_EN=0`, pumps forced on in HAND.

Tank volume runs at 60× real time (1 lab second = 1 process minute).
