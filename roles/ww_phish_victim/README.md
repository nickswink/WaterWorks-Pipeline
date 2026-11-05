# ww_phish_victim

HR reviewer workstation **WW-WS01** — the Windows phishing / initial-access
target for the WaterWorks Pipeline range. A **standalone (workgroup) Windows
Server 2019** box (no domain). Managed over WinRM; Ansible runs as the local
admin.

## Initial-access mechanic

1. An attacker uploads a double-clickable "resume" (`.exe/.scr/.vbs/.bat/.cmd/.lnk/.hta/.js`)
   to the **public careers portal** on `ww-web01`.
2. The HR reviewer (`a.wallace`, "Amanda Wallace") is **auto-logged on**. A
   logon scheduled task starts `intake.ps1`, which polls the portal every
   ~20 s, downloads each new submission into the user's **Downloads**, strips
   Mark-of-the-Web (`Unblock-File`), and **opens it with `Start-Process`
   (ShellExecute)** — exactly the double-click / default-action behaviour,
   which runs `.exe/.scr/.vbs/.bat/.cmd/.lnk/.hta/.js` via their registered
   handlers.
3. The payload detonates in the interactive session and beacons out over the
   WireGuard egress that is already allowed for this host. The flag
   (`ww_flags.foothold_phish`) sits on the victim desktop as the reward.

## Portal contract (consumed, not provided here)

`ww-web01` at `http://<ww_net>.10.10` must expose:

- `GET /careers/inbox.json` → `{"files":[{"name":"resume.exe","size":1234,"mtime":...}, ...]}` (newest first)
- `GET /careers/files/<name>` → raw bytes of that upload (extension preserved)

The poller addresses the portal by **IP** (`{{ ww_net }}.10.10`), not DNS.

## Autologon + scheduled-task mechanism

- **Autologon** is set in `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon`:
  `AutoAdminLogon="1"`, `DefaultUserName=<victim>`, `DefaultPassword=<plaintext>`,
  `DefaultDomainName="WW-WS01"`. Plaintext password is how autologon works; it
  is acceptable for this lab.
- **Scheduled task** `HR Resume Intake` (`community.windows.win_scheduled_task`):
  trigger = **logon** for the victim, `logon_type: interactive_token`,
  run as the victim, `run_level: limited`, action =
  `powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File C:\ProgramData\HRIntake\intake.ps1`.
  Because it runs on logon with an interactive token, the poller lives in the
  reviewer's real desktop session, so ShellExecute'd payloads detonate
  interactively.

## Payload-execution realism (endpoint misconfig)

So BYO operator payloads actually run:

- **Defender**: `HKLM\SOFTWARE\Policies\Microsoft\Windows Defender\DisableAntiSpyware=1`
  plus best-effort `Set-MpPreference -DisableRealtimeMonitoring $true` with
  Downloads + `C:\ProgramData\HRIntake` exclusions (wrapped so it never fails
  the play).
- **SmartScreen**: `HKLM\SOFTWARE\Policies\Microsoft\Windows\System\EnableSmartScreen=0`.
- **Mark-of-the-Web**: machine policy
  `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Attachments\SaveZoneInformation=1`,
  and the poller also calls `Unblock-File` on every download.

## Layout

```
defaults/main.yml                           local knobs (portal base, poll, dirs)
meta/main.yml                               galaxy_info (author risk3sixty), deps []
tasks/main.yml                              the 8-step build
templates/intake.ps1.j2                     the resume-intake poller (ShellExecute opener)
templates/HR_Resume_Intake_README.txt.j2    in-world HR hint (desktop + Documents)
files/resume_*.txt                          benign sample resumes (pre-marked seen)
```

On disk at deploy time:

```
C:\ProgramData\HRIntake\intake.ps1      the poller
C:\ProgramData\HRIntake\seen.txt        processed-file list (samples pre-seeded)
C:\ProgramData\HRIntake\intake.log      activity log
C:\Users\<victim>\Downloads\            where resumes land and detonate
C:\Users\<victim>\Desktop\flag.txt      foothold flag
C:\Users\<victim>\Desktop\HR_Resume_Intake_README.txt   in-world hint
```

## Variables consumed

From `global_role_vars` in `range.yaml` (with safe fallbacks in `defaults/`):

| Var | Use |
|---|---|
| `ww_net` | portal base `http://<ww_net>.10.10` |
| `ww_ws_victim_user` | victim account + autologon + task run-as + profile paths |
| `ww_ws_victim_password` | victim password + autologon + task run-as |
| `ww_flags.foothold_phish` | desktop flag (asserted defined) |
| `ww_org_name` | in-world HR content branding |

Role-local defaults: `ww_phish_victim_portal_base`, `ww_phish_victim_poll_seconds`,
`ww_phish_victim_install_dir`, `ww_phish_victim_downloads_dir`,
`ww_phish_victim_desktop_dir`, `ww_phish_victim_documents_dir`,
`ww_phish_victim_logon_domain`, `ww_phish_victim_reboot`.

## Required collections

- `ansible.windows` (`win_user`, `win_file`, `win_regedit`, `win_copy`,
  `win_template`, `win_shell`, `win_reboot`)
- `community.windows` (`win_scheduled_task`)

## Integration / deploy notes

- The role **reboots at the end** (`ansible.windows.win_reboot`) so autologon
  logs the victim in and the onlogon task launches the poller. Set
  `ww_phish_victim_reboot: false` to skip if you orchestrate the reboot
  elsewhere.
- Firewall is untouched: `ww-ws01 -> web01:80` and `ww-ws01 -> WireGuard`
  egress are already provisioned in `range.yaml`.
- Standalone box — **no `domain:` block** in `range.yaml`; the scheduled-task
  and autologon use the local account, `DefaultDomainName="WW-WS01"`.
- Profile directories are pre-created so Ansible can plant the flag and HR
  content before first logon. If a Windows build instead materialises the
  profile under a suffixed path on first interactive logon, re-run the role
  (or move the flag/content tasks after the reboot) — the poller itself always
  resolves Downloads from the configured path and recreates it if missing.
- `idempotent`: `win_copy content`/`win_template`/`win_regedit`/`win_user`
  (`update_password: on_create`) and `win_scheduled_task` all converge.
  `seen.txt` is reset to the sample set on each run; runtime appends by the
  poller are expected and harmless.
