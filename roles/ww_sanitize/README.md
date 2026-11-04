# ww_sanitize — build-artifact / IoC sanitizer (Linux)

Runs **last** on every host in the WaterWorks range (wired via `depends_on` in
`range.yaml`). It makes each VM read as a genuine utility/enterprise system by
removing the fingerprints left by automated range building.

## What it does
- Removes a *stray* extra default account (e.g. a leftover `localuser`) if one
  exists, and any passwordless-sudo drop-in for the default accounts.
- Strips build-cache / proxy package sources (`192.0.2.2/3`) from apt config.
- Deletes automation staging dirs (`/opt/ludus`, `/var/tmp/ludus`, `~/.ansible/tmp`)
  and `ansible-*` temp files under `/tmp` and `/var/tmp`.
- Clears **only** root's and the default account's shell history.
- Truncates cloud-init / provisioning logs and removes cloud-init instance seed.
- Installs a corporate MOTD, SSH banner, and a cosmetic asset record
  (`Dell PowerEdge` identity).

## What it deliberately does NOT do
- It never touches scenario users, their home directories, planted `.bash_history`
  files, seeded databases, web apps, or flags. Only `root` and the default
  account's history are cleaned, so the immersive breadcrumbs planted by the
  other roles survive.
- **It does not delete or re-password the `debian` management account during a
  normal deploy.** On Debian templates the build automation connects to each VM
  as `debian` over SSH (with `sudo`) to deploy and to re-run roles. Deleting or
  changing that account mid-deploy would break the build and all future
  `deploy.sh roles` runs.

## Removing the default username/password (opt-in)

The `debian` / `debian` default is the one IoC that cannot be removed while the
build automation still needs to manage the host. When your range content is
frozen and you are handing it to players, set in `range.yaml` global_role_vars:

```yaml
global_role_vars:
  ww_sanitize_lockdown_default_account: true
```

and run one final `./deploy.sh roles`. This sets a strong random password on
`debian` and disables SSH password login for it, fully removing the default
credential.

**Trade-off:** afterwards the automation can no longer SSH in to re-run roles on
that host. Snapshot-based reset (`ludus testing start/stop`) is unaffected — it
reverts the Proxmox disk image and does not use SSH — so you can still reset the
range between teams. Leave this `false` while you are still iterating.

## Key variables
See `defaults/main.yml`. `ww_sanitize_ludus_source_ip` and
`ww_sanitize_proxy_markers` come from `global_role_vars`.
