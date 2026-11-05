# WaterWorks Pipeline — Operator Setup Guide

Deployment, verification, and teardown for the range. Run everything from a shell
where the `ludus` client has an API key configured (the Ludus host itself, or any
machine with the client set up and reachable to your Ludus server).

---

## 1. Prerequisites

- A working Ludus server (tested against Ludus client `2.1.x`).
- Two templates built:
  - **`debian-12-x64-server`** — used by every Linux host (10 of 12 VMs).
  - **`win2019-server-x64`** — used by the Windows phishing workstation `ww-ws01`.

  ```bash
  ludus templates list | grep -E 'debian-12-x64-server|win2019-server-x64'
  # build whichever is missing:
  ludus templates build -n debian-12-x64-server-template
  ludus templates build -n win2019-server-x64-template
  ludus templates status
  ```

- ~24 GB RAM and ~24 vCPU across the 12 range VMs + router. The Windows box
  (`ww-ws01`, 4 GB) is the only heavy one; the rest are small and overcommit fine.
- The Windows workstation role (`ww_phish_victim`) needs the **`ansible.windows`**
  and **`community.windows`** collections. `./deploy.sh deps` installs them
  automatically (`ludus ansible collection add ...`); the Linux roles need no
  external Galaxy content.

---

## 2. One-command deploy

```bash
./deploy.sh
```

This will:

1. `ludus ansible role add -d roles/<each>` for all ten local roles (`-f`, idempotent).
2. Create the range **`waterworks`** if it does not exist, then push `range.yaml`.
3. `ludus range deploy --range waterworks`.

First build takes roughly **30–60 minutes**. Follow along with:

```bash
ludus range logs -f --range waterworks
ludus range list   --range waterworks
```

> `deploy.sh` passes `--range waterworks` to every command. Override with
> `RANGE=<id> ./deploy.sh` if you want a different range ID, or
> `LUDUS=/path/to/ludus ./deploy.sh` to point at a specific client binary.

### Sub-commands

```bash
./deploy.sh deps       # add/update local roles only
./deploy.sh config     # create range (if needed) + push range.yaml
./deploy.sh roles      # re-run user-defined roles only   (-t user-defined-roles)
./deploy.sh network    # re-apply firewall rules only      (-t network)
./deploy.sh status     # ludus range list
```

---

## 3. Before you deploy: edit these

Open [range.yaml](range.yaml) and review:

- **`network.always_blocked_networks`** — set this to the LAN your Ludus host
  lives on (default `10.0.0.0/24`). This is a hard guardrail so the range can
  never reach your real infrastructure. **Do not skip this.**
- **`global_role_vars.ww_flags`** — the 21 flag strings. The defaults are fine for
  a private event; **rotate them** if your flags may have leaked or if you're
  running a public competition. They are the single source of truth: the scoreboard
  hashes them and the PLC/role content embeds them at deploy time, so changing a
  value here updates everything on the next `./deploy.sh`.
- **`global_role_vars.ww_scoreboard_admin_password`** — the scoreboard `/admin`
  password. Change it.
- **`global_role_vars.ww_plc_event_hold_s`** — how long (seconds) an impact event
  latches before the simulated plant self-repairs. Default `600` (10 min). Lower
  it for a demo, raise it for a slow-paced event.

---

## 4. Verify the build

After deploy finishes:

```bash
# All VMs should be deployed/started:
ludus range list --range waterworks

# From a WireGuard-connected client, the only directly reachable targets:
curl -skI http://waterworkspipeline.com            # ww-web01 (DMZ)
curl -sI  http://<10.x.60.10>/healthz              # ww-score scoreboard
```

Deeper health checks (the segmentation means these only work from the right
pivot point, so run them from the matching host once you've landed):

| Service | Host | Check |
|---------|------|-------|
| Website | ww-web01 | `curl -s http://waterworkspipeline.com/robots.txt` |
| Scoreboard | ww-score | open `http://<10.x.60.10>` and register a team |
| File server | ww-fs01 | `smbclient -L //10.x.20.10 -N` |
| Historian | ww-hist01 | `curl -s http://10.x.30.10:8080/login` (from VLAN 20) |
| HMI web | ww-hmi01 | `curl -s http://10.x.40.10/login` (from ww-jump01) |
| HMI VNC | ww-hmi01 | `nc -vz 10.x.40.10 5900` (from ww-jump01) |
| Controllers | ww-plc0x | `mbpoll -1 -t4 -r1 -c4 10.x.50.10` (from SCADA) |

The `scoreboard.range` and `waterworkspipeline.com` names resolve via the range's
own DNS for connected clients.

---

## 5. Host inventory

| VM | Host | VLAN | IP (`.octet`) | RAM | vCPU | Role |
|----|------|------|------|-----|------|------|
| ww-web01 | DMZ web | 10 | .10 | 2 | 2 | `ww_web_portal` |
| ww-fs01 | File server | 20 | .10 | 2 | 2 | `ww_fileserver` |
| ww-it01 | IT admin | 20 | .20 | 2 | 2 | `ww_itadmin` |
| ww-ws01 | HR workstation (Windows 2019) | 20 | .30 | 4 | 2 | `ww_phish_victim` |
| ww-hist01 | Historian | 30 | .10 | 2 | 2 | `ww_historian` |
| ww-jump01 | Jump host | 30 | .20 | 2 | 2 | `ww_jumphost` |
| ww-hmi01 | SCADA HMI | 40 | .10 | 4 | 2 | `ww_hmi` |
| ww-eng01 | Eng workstation | 40 | .20 | 2 | 2 | `ww_engws` |
| ww-plc01 | Intake PLC | 50 | .10 | 1 | 1 | `ww_plc` (intake) |
| ww-plc02 | Chem-feed PLC | 50 | .20 | 1 | 1 | `ww_plc` (chemfeed) |
| ww-rtu03 | Booster RTU | 50 | .30 | 1 | 1 | `ww_plc` (booster) |
| ww-score | Scoreboard | 60 | .10 | 2 | 2 | `ww_scoreboard` |

Every Linux host also runs `ww_sanitize` last to remove build artifacts.
`ww-ws01` (Windows) reboots at the end of its role so the HR autologon + the
"HR Resume Intake" task start; after deploy it should be sitting logged in as
`a.wallace` with the intake task polling the careers page.

---

## 6. Hardening the network further (optional)

The default `network.external_default: ACCEPT` lets every VM reach the internet
during the build (apt). Real OT networks are air-gapped from the internet. To
model that after a successful deploy, flip the field/SCADA zones to no-internet:

```yaml
# in range.yaml network.rules, then: ./deploy.sh network
  - { name: "SCADA no internet",  vlan_src: 40, vlan_dst: public, protocol: all, ports: all, action: REJECT }
  - { name: "Field no internet",  vlan_src: 50, vlan_dst: public, protocol: all, ports: all, action: REJECT }
```

(Leave the DMZ with egress so `ww-web01` can still call back to the operator.)

### Removing the default `debian` account password

Every Debian VM ships with the `debian` / `debian` account that **Ludus uses to
deploy and manage the host** — so the `ww_sanitize` role deliberately leaves it
working during normal deploys. Once your range is frozen and you're handing it to
players, remove that default credential by setting in `range.yaml`:

```yaml
global_role_vars:
  ww_sanitize_lockdown_default_account: true
```

then `./deploy.sh roles` one last time. It sets a strong random password on
`debian` and disables its SSH password login. **After this, `deploy.sh roles` can
no longer re-run roles** (SSH auth will fail), but snapshot reset
(`ludus testing start/stop`) still works. Keep it `false` while iterating.

---

## 7. Reset & teardown

```bash
# Re-run roles after editing content/flags (keeps VMs):
./deploy.sh roles

# Revert to a clean snapshot between teams (if you took one):
ludus range snapshot list   --range waterworks
ludus testing start         --range waterworks   # snapshots, cuts internet
ludus testing stop          --range waterworks   # reverts to pre-test state

# Destroy the VMs but keep the range object:
ludus range rm --range waterworks

# Delete everything:
ludus range rm-range --range waterworks
```

Impact challenges auto-restore after `ww_plc_event_hold_s`, so you usually do
**not** need to reset between attempts — a new team can re-trigger every impact.

---

## 8. Troubleshooting

- **A role fails mid-deploy:** re-run `./deploy.sh roles` — roles are idempotent.
  Check `ludus range logs --range waterworks` and
  `ludus range errors --range waterworks`.
- **Can reach internal VLANs directly over VPN:** confirm the `wireguard` REJECT
  rules in `range.yaml` deployed — `./deploy.sh network`. By design you should
  only reach VLAN 10 and VLAN 60 from the VPN.
- **A controller shows no data on the HMI:** check `wwfield.service` on the PLC
  host (`systemctl status wwfield`); the HMI poller marks it `COMM_FAIL` until it
  recovers.
- **Scoreboard rejects a known-good flag:** confirm `ww_flags` in `range.yaml`
  matches what the roles deployed, then `./deploy.sh roles` to re-seed both.
