# ww_jumphost

OT remote-access jump host for **ww-jump01** (OT DMZ, Purdue L3.5). Debian 12
(bookworm), apt packages only. This is the single controlled hop between
corporate IT (VLAN 20) and the SCADA control center (VLAN 40): IT admins SSH in
from ww-it01, and the vendor account is used from here to reach the engineering
workstation. It is the pivot funnel - everything into SCADA/field goes through
here.

| Item | Value |
|---|---|
| Host | `ww-jump01` `<ww_net>.30.20` |
| Reaches | HMI `<ww_net>.40.10` (web :80 / VNC :5900), ENG WS `<ww_net>.40.20` (ssh :22) |
| Tools | `openssh-server/-client`, `sudo`, `less`, `vim`, `tmux`, `curl`, `netcat-openbsd` (no scanners) |

## Accounts

| User | Shell | Auth | Role |
|---|---|---|---|
| `d.whitfield` | `/bin/bash` | pubkey (`dwhitfield_jump.pub` in `authorized_keys`) + random pw | the account IT logs in as, from ww-it01 |
| `hydra_vendor` | `/bin/bash` | random pw (reached via the sudo->less escape) | vendor support; holds the ed25519 key to ww-eng01 |
| `p.raman`, `r.castillo` | `/bin/bash` | random pw | plausible operator / field accounts |

`d.whitfield` logs in with the key issued on ww-it01. `hydra_vendor`'s
`~/.ssh/id_ed25519` is the vendor key to ww-eng01, with a `~/.ssh/config`
`Host ww-eng01` entry so `ssh ww-eng01` just works once you are that user.

### sshd (drop-in `00-wwp-jump.conf`)

`PasswordAuthentication yes`, `PubkeyAuthentication yes`, `PermitRootLogin no`,
`AllowTcpForwarding yes` (it is a jump host - SSH -J/-L/-D tunnels are the point).
Banner `/etc/issue.net`. `LESSSECURE` is deliberately **not** set anywhere.

## Intended vulnerability (CWE-250 / GTFOBins `less`): sudo -> vendor pivot

`/etc/sudoers.d/it-ot-support`:

```
d.whitfield ALL=(hydra_vendor) NOPASSWD: /usr/bin/less /opt/hydra/logs/*
```

The comment ties it to "IT reviews vendor session logs (ticket IT-1182 /
SOP OT-RA-03)". The file is validated at install time with `visudo -cf`.

`/opt/hydra/logs/` holds realistic vendor session logs owned by `hydra_vendor`.
The intended exploit: as `d.whitfield`, run

```
sudo -u hydra_vendor /usr/bin/less /opt/hydra/logs/session-2026-10-14.log
```

then use a `less` shell escape (`!sh`, `:!/bin/sh`, or `v` to open vi then
`:!/bin/sh`) to drop into a shell **as hydra_vendor**. Because `LESSSECURE` is
not set, `less` honours the escape. That shell owns `~/.ssh/id_ed25519`, giving
`ssh ww-eng01` and lateral movement into SCADA.

## Flags / creds planted here

| What | Value source | Location |
|---|---|---|
| `jump_vendor` flag | `ww_flags.jump_vendor` | `/home/hydra_vendor/flag.txt` (0600) |
| HMI web login | `ww_controlroom_password` (var) | `/home/hydra_vendor/notes/site_contacts.txt` |
| HMI VNC password | `ww_vnc_password` (var) | `/home/hydra_vendor/notes/site_contacts.txt` |

`site_contacts.txt` renders `controlroom` / `ww_controlroom_password` and the
VNC `ww_vnc_password` from the global vars, so it stays in sync with `ww_hmi`.

## Breadcrumbs

- `d.whitfield` `~/.bash_history`: `sudo -l`, the `sudo -u hydra_vendor less ...`
  review, `curl http://<ww_net>.40.10` (HMI), and failed `ssh ww-eng01` attempts
  as d.whitfield (no key). `~/README.txt` and `/etc/motd` describe reachable
  SCADA hosts and the "no pivot without a ticket" rule.
- `hydra_vendor` `~/.tmux.conf` and `.ssh/config` hint that the field network is
  reachable only through the HMI / ENG hosts.
- `/opt/hydra/README` describes Hydra Controls Integration remote support.

## Required vars (global_role_vars)

`ww_net`, `ww_org_name`, `ww_flags` (asserts `jump_vendor`),
`ww_controlroom_password`, `ww_vnc_password`.
