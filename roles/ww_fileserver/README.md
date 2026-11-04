# ww_fileserver

Corporate Samba file server for the WaterWorks Pipeline range (`ww-fs01`,
`{{ ww_net }}.20.10`). Standalone server (workgroup `WWP`, "WWP File
Services", SMB2+ only, no domain, NetBIOS disabled).

## Shares

| Share | Path | Read | Write | Notes |
|---|---|---|---|---|
| `Public` | /srv/samba/Public | any valid user (incl. `svc_ccrsync`) | `@itstaff`, `@wq` | CCR reports, newsletters, board minutes, staff directory, helpdesk docs |
| `Engineering` | /srv/samba/Engineering | `@engineering`, `@eng_ro` | `@engineering` | network overview (`fs_engineering` flag), SCADA SOP/description, AA23-335A tracker |
| `HR` | /srv/samba/HR | `@hr` | `@hr` | only `t.kessler` |
| `IT$` | /srv/samba/IT | `@itstaff` | `@itstaff` | hidden; IT runbooks |

Linux permissions mirror the share ACLs (setgid group dirs; `eng_ro` gets
read on Engineering through a POSIX ACL with default ACLs for new files).

## Accounts

All are Samba + Linux users with `/usr/sbin/nologin`.

| User | Groups | Password |
|---|---|---|
| `svc_ccrsync` | eng_ro | `ww_ccrsync_password` (intended path) |
| `d.whitfield`, `j.alvarez` | itstaff, public_rw | random (defaults) |
| `m.oyelaran` | engineering | random |
| `t.kessler` | engineering, hr | random |
| `e.brooks` | wq, public_rw | random |

Existing Samba passwords are not reset on re-runs (accounts are only added
when missing from `pdbedit -L`).

## Requires

Range-wide vars: `ww_net`, `ww_flags`, `ww_ccrsync_password`, `ww_org_name`,
`ww_domain`.
