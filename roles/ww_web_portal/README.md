# ww_web_portal

Public utility website and contractor portal for **WaterWorks Pipeline Co.**
(Cedar Ridge Regional Transmission System), deployed on `ww-web01`
(Internet DMZ, VLAN 10). This is the internet-facing initial-access surface.

## What it builds

- A Flask application (`/opt/wwp-portal/app.py`) served by **waitress** on
  `127.0.0.1:8000` as the `wwp-web` service account (`wwp-portal.service`).
- **nginx** on `:80` reverse-proxying to the app (`default_server`, serves the
  `waterworkspipeline.com` / `www` / `portal` virtual hosts).
- A polished, self-contained site (no external CDNs): Home, About, Water
  Quality (CCR downloads), Notices, Careers, Contact, and a Contractor Portal
  login. Inline SVG water-drop logo; all CSS in `static/style.css`.
- Public notices stored in a SQLite database (`data/notices.db`), seeded once.
- A nightly CCR report sync (CIFS mount of the corporate file share, `rsync`,
  cron) that fails harmlessly when the file server is unreachable.

## Layout on the host

```
/opt/wwp-portal/        root:wwp-web  (code 0640, readable by the service user)
  app.py  .env  templates/  static/  content/staging.html  reports/  data/
/etc/systemd/system/wwp-portal.service
/etc/nginx/sites-available/wwp.conf
/etc/sudoers.d/wwp-web
/root/scripts/ccr_sync.sh   /etc/cron.d/ccr-sync
/root/.smbcredentials-ccr
```

## Required variables (from `global_role_vars`)

`ww_flags`, `ww_portal_secret_key`, `ww_ccrsync_password`, `ww_net`,
`ww_org_name`, `ww_domain`. See `defaults/main.yml` for role-local tunables.
Flag values are injected at deploy time and are not duplicated in defaults.

## Services

- `wwp-portal.service` — Flask app under waitress.
- `nginx` — reverse proxy on port 80.
