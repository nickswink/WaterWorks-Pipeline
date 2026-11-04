# ww_itadmin

IT administration server for the WaterWorks Pipeline range (`ww-it01`,
`{{ ww_net }}.20.20`). Corporate Linux box used by IT staff; the only host
the firewall allows to SSH into the OT jump server (`ww-jump01`).

## Accounts

| User | Groups | Password | Notes |
|---|---|---|---|
| `j.alvarez` | helpdesk | `ww_newhire_password` | new hire, never changed temp password (spray target); `~/flag.txt` = `it_spray` |
| `d.whitfield` | itstaff, helpdesk | random | home 0750; `~/.ssh/id_ed25519` = key for `ww-jump01` |
| `k.tran` | itstaff, adm | random | sysadmin decoy |
| `s.patel` | helpdesk | random | apps analyst decoy |

`sshd` allows password authentication via `/etc/ssh/sshd_config.d/00-wwp-auth.conf`.

## Privilege escalation

`/opt/it-scripts/` (root:helpdesk 0775) and `nightly_config_backup.sh`
(root:helpdesk 0775) are run by root every minute from
`/etc/cron.d/it-config-backup`. A helpdesk member can edit the script to run
commands as root. `/root/flag.txt` = `it_root`.

## Planted content

- `/home/j.alvarez/`: helpdesk notes, ticket export, `.bash_history`
- `/home/d.whitfield/`: SSH key pair + `~/.ssh/config` (`ww-jump01`),
  `.bash_history`, `Documents/OT_Access_Notes.txt` (sudo `less` hint for
  `hydra_vendor` on the jump host, eng01 location)

The private key in `files/` must match the `d.whitfield` authorized key that
the jump host role installs.

## Requires

Range-wide vars: `ww_net`, `ww_flags`, `ww_newhire_password`, `ww_org_name`,
`ww_domain`.
