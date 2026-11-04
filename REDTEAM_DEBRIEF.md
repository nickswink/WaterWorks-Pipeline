# WaterWorks Pipeline — Red Team Debrief

An after-action report for the WaterWorks Pipeline engagement. It frames the range
the way you'd write up a real OT assessment: the narrative of the compromise, the
kill chain mapped to **MITRE ATT&CK for Enterprise and ICS**, the specific
engineering realities that made physical impact possible, and — most importantly —
the defensive findings a client would actually pay for.

This document is written to be read **after** completing the range (or alongside
[WALKTHROUGH.md](WALKTHROUGH.md)). It assumes you know the solution.

---

## 1. Engagement summary

> **Objective:** Determine whether an internet-based attacker could affect the
> safety or availability of the Cedar Ridge water supply.
>
> **Result:** Full compromise. Starting from the public website with no
> credentials, the team achieved code execution in the DMZ, pivoted through
> corporate IT and the OT DMZ into the SCADA network, reached the Level-1 field
> controllers, and demonstrated five distinct physical-impact scenarios including
> a caustic chemical overdose of finished drinking water and a transmission-main
> rupture. **Time-to-impact is dominated by segmentation and credential hygiene,
> not by exploit difficulty** — exactly the pattern seen in the real incidents in
> [CASE_STUDY.md](CASE_STUDY.md).

The compromise crossed every Purdue level:

```
 L5/DMZ      L4 Corp IT      L3.5 OT DMZ        L2/L3 SCADA        L1 Field
 ww-web01 ─▶ ww-fs01    ─┐
            ww-it01 ────┼─▶ ww-jump01 ────────▶ ww-hmi01    ─┐
            (creds)     └─▶ ww-hist01           ww-eng01 ────┼─▶ ww-plc01
                            (recon)             (eng tools)  ├─▶ ww-plc02
                                                             └─▶ ww-rtu03
```

---

## 2. The kill chain

### Phase 1 — Initial access (Internet DMZ)

The public website exposed a classic chain: directory recon
(`robots.txt` → staging page) revealed a report-download endpoint, which was
vulnerable to **path traversal**. That leaked the Flask application secret, which
let the team **forge an admin session** for the contractor portal. The admin
"public notice" preview rendered attacker input through a template engine —
**server-side template injection** → remote code execution as the web service
account. A `sudo` misconfiguration (`NOPASSWD: rsync`) gave root.

Root on the DMZ box yielded the real prize: **stored CIFS credentials** for a
service account used to sync water-quality reports from the corporate file server.

| Technique | ATT&CK |
|-----------|--------|
| Active scanning / content discovery | T1595, T1083 |
| Path traversal to read app config | T1190, T1083 |
| Forged signed-cookie session | T1539, T1550.004 |
| Server-side template injection → RCE | T1190, T1059 |
| Sudo (`rsync`) privilege escalation | T1548.003 |
| Unsecured stored credentials | T1552.001 |

### Phase 2 — Corporate IT (L4)

The stolen service-account credentials opened the file server over SMB. The
**Engineering** and **Public** shares were an intelligence goldmine: a full network
overview, an OT remote-access SOP, a CISA advisory action-tracker showing a PLC
default password left unchanged, the surge-study summary, and a new-hire IT
checklist that documented the **default-password pattern for new accounts**
(`WaterWorks<year>!`). Cross-referencing the staff directory's hire dates with that
pattern produced a working password for a recently hired helpdesk technician —
a **targeted password guess**, not a spray, straight onto the IT admin server.

On the IT box, a world-writable **root cron** script gave local root, and the IT
manager's home directory held an **SSH private key and `~/.ssh/config`** pointing
at the OT jump host.

| Technique | ATT&CK |
|-----------|--------|
| Valid accounts (service acct) over SMB | T1078, T1021.002 |
| Data from network shares (OT intel) | T1039, T1552 |
| Credential pattern inference from docs | T1589.001, T1110.001 |
| Writable cron → root | T1053.003, T1548 |
| Private keys from a user home | T1552.004 |

### Phase 3 — OT DMZ (L3.5): the controlled hop

This is the pivot the whole architecture funnels through. The IT manager's key
logged the team into **`ww-jump01`**, the sanctioned bastion for OT access. A
`sudo` rule let `d.whitfield` run `less` as the integrator's vendor account to
"review session logs" — and **`less` honors shell escapes**, giving a shell as
`hydra_vendor`. That account held the SSH key to the engineering workstation and
a notes file leaking the **shared control-room HMI login and VNC password**.

Separately, the historian (`ww-hist01`) — reachable from corporate IT for "trend
viewing" — exposed a **SQL-injectable** trend parameter that dumped its config
table, including the bearer token the historian uses to poll the SCADA HMI API.

| Technique | ATT&CK (Enterprise / ICS) |
|-----------|--------|
| Remote services / internal SSH pivot | T1021.004 / T0886 |
| `GTFOBins`-style `less` shell escape to lateral account | T1548, T1202 |
| SQL injection on historian | T1190 |
| Credential & token theft from OT DMZ hosts | T1552 / T0882 Theft of Operational Information |

### Phase 4 — SCADA (L2/L3)

From the jump host, the stolen control-room credentials logged into the **HMI**
(web and VNC). The engineering workstation (`ww-eng01`), reachable only from the
jump host, held the integrator's **engineering toolkit** (Modbus and Unitronics
PCOM clients), the **PLC project files** — with register maps, the surge analysis,
and the booster's **maintenance override key** written in a code comment — and a
**SUID-root binary with a PATH-hijack** flaw that gave root on the engineering box.

At this point the team had everything needed to command Level 1: tooling,
addressing, process knowledge, and the maintenance key that unlocks the booster's
protective interlocks.

| Technique | ATT&CK (Enterprise / ICS) |
|-----------|--------|
| Valid accounts on HMI (web + VNC) | T1078 / T0859 |
| Graphical/remote operator interface | T0823 Graphical User Interface |
| Engineering workstation as staging | T0818 / T0866 |
| Project-file theft (incl. maint key) | T0864 / T1552, T0882 |
| SUID PATH hijack → root on eng WS | T1548.001 |

### Phase 5 — OT recon & impact (L1)

With direct Modbus/TCP (and PCOM) reachability from SCADA to the field devices,
the team enumerated the controllers (Modbus **FC43 device identification**, FC17
server ID, and PCOM memory beyond the Modbus-mapped range) and then **manipulated
the process**:

| Impact | What the team did | ICS ATT&CK |
|--------|-------------------|------------|
| **Intake dry-run** | Cleared the low-low protection coil, forced a pump to HAND run, starved the wet well → pump cavitated and was destroyed | T0836 Modify Parameter, T0831 Manipulation of Control, T0879 Damage to Property |
| **Caustic overdose** | Disabled the high-pH cutout and drove the NaOH dose far past the HMI's accepted range (the Oldsmar scenario) → corrosive finished water | T0836, T0839 Module Firmware? *(no)* → T0836 Modify Parameter, T0806 Brute Force I/O *(no)*; **T0836 + T0831** |
| **Panel defacement** | Overwrote the operator-panel message registers | T0832 Manipulation of View |
| **Tank overflow** | Entered maintenance mode, defeated the high-level cutoff, forced the booster pumps on → Summit Tank overtopped | T0836, T0831, T0828 Loss of Productivity and Revenue |
| **Main break** | Disarmed the surge valve and HP-trip, raised the valve slew rate, ran the pumps, then slammed FCV-301 shut → water-hammer transient ruptured the 1962 crossing | T0836, T0831, T0879 Damage to Property, T0826 Loss of Availability |

Supporting ICS techniques across the phase: **T0883 Internet Accessible Device**
(conceptually, how the real attacks start), **T0886 Remote Services**,
**T0855/T1692.001 Unauthorized Command Message**, **T0846 Remote System
Discovery**, **T0888 Remote System Information Discovery**, **T0816 Device
Restart/Shutdown** (PCOM stop of the chemical-feed PLC).

---

## 3. Why the physical impact was possible

Each impact maps to a specific, realistic engineering weakness — and to a real
incident:

1. **Protocol trust.** Modbus/TCP and PCOM have no authentication. On the SCADA
   segment, reachability *is* control. (See CASE_STUDY §2.3.)
2. **Interlocks implemented in the same controller an attacker owns.** The
   low-low pump protection, pH HIHI cutout, tank high-level cutoff, HP trip, and
   surge valve are all defeatable by writing the same registers/coils an operator
   uses — because they live *in* the PLC, not in an independent safety instrumented
   system. Real plants increasingly separate safety (SIS) from control for exactly
   this reason.
3. **The HMI enforced limits the PLC did not.** The caustic overdose works because
   the operator screen caps the dose at a sane value but the controller accepts
   anything. This is precisely the Oldsmar dynamic — the setpoint change bypassed
   the operator-facing guardrails.
4. **A maintenance key in a project file.** The booster's interlock-bypass key was
   documented in a code comment and equal to the station's street number. Secrets
   in engineering artifacts + guessable values = no barrier.
5. **Water hammer is real physics.** The main break isn't a magic flag — it
   requires defeating three independent protections *and* understanding the surge
   study, then inducing a transient above the pipe's rating. That's the level of
   process knowledge a capable OT attacker brings (cf. FrostyGoop, CASE_STUDY §3.11).

---

## 4. Defensive findings (what the client should fix)

Ordered by impact-reduction per dollar:

1. **Remove the IT→OT flat paths.** The jump host is good practice, but the vendor
   account's shell-escape-able `sudo less` rule and reused SSH keys collapsed the
   boundary. Enforce per-session, MFA-gated, logged OT access (a real jump/PAM) and
   forbid interactive pagers under `sudo` (`LESSSECURE=1`, `sudoedit`, or restricted
   commands).
2. **Independent safety.** Move the pH-high, pump-dry, tank-high, and over-pressure
   trips into a safety controller the control network cannot override. Rate- and
   range-limit setpoints *at the PLC*, not only at the HMI.
3. **Credential hygiene.** Kill the default new-hire password pattern, rotate the
   PLC/HMI/VNC shared credentials (the CISA advisory to change the PLC default was
   tracked and ignored), remove stored service-account credentials from hosts, and
   scope the report-sync account to exactly one read-only share.
4. **Patch the DMZ web stack.** Path traversal, template injection, and session
   secret exposure are ordinary appsec bugs — but on the internet edge of a utility
   they are the entire foothold.
5. **Detection.** None of the Modbus writes, the FC43 scans, the PCOM stop, or the
   setpoint changes were alarmed independently of the compromised HMI. Deploy OT
   network monitoring (e.g. Modbus write/function-code alerting) that does not
   depend on the HMI the attacker controls.
6. **Network egress.** Field and SCADA zones should have no internet path at all
   (see SETUP.md §6).

---

## 5. Mapping to real incidents

| Range element | Real-world basis (see CASE_STUDY.md) |
|---------------|--------------------------------------|
| Caustic (NaOH) overdose via setpoint, HMI-limit bypass | Oldsmar, FL 2021 (§3.4) |
| Internet/remote access + shared passwords as the way in | Oldsmar, Kemuri, Unitronics campaign (§3.2–3.4, 3.8) |
| Unitronics PCOM / port 20256 / default creds | CyberAv3ngers 2023–24, incl. Aliquippa (§3.8) |
| Modbus-native manipulation of a water distribution process | FrostyGoop / Lviv heating (§3.11) |
| Ex-insider / vendor credential abuse into OT | Post Rock Rural Water (§3.3), Maroochy (§3.1) |
| Ignored CISA advisory / deferred security upgrades | WWS sector advisories (§3.5, §4.2) |
| HMI manipulation over operator interface/VNC | Pro-Russia hacktivists 2022–25 (§3.10) |

---

## 6. For instructors

- **Difficulty knobs:** `ww_plc_event_hold_s` (impact replay window), the
  new-hire password pattern discoverability, and whether you pre-brief the surge
  study all change the challenge sharply.
- **Teaching beats:** the range is designed so each phase *teaches* a transferable
  OT lesson — protocol trust, interlock placement, HMI-vs-PLC limit enforcement,
  secrets in engineering files, and water-hammer physics. The main-break flag is
  intentionally the hardest: it rewards reading the engineering documentation the
  way a real OT attacker must.
- Pair this debrief with [CASE_STUDY.md](CASE_STUDY.md) §6 ("Lessons for red
  teams") for the professional-practice framing.
