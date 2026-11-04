# Cyber Attacks Against Water Utility and Pipeline OT: A Technical Case Study

*Background reading for the "WaterWorks Pipeline" Ludus CTF range. WaterWorks Pipeline is a fictional company. Every incident below is real and cited to a public source. Bracketed numbers such as [3] point to Section 7.*

*Research cut-off: 16 October 2026. ATT&CK for ICS technique IDs follow ATT&CK v20 (October 2026). Where MITRE has renumbered a technique since the older advisories were written, both IDs are given (see Section 5.1).*

---

## 1. Summary

**Scope.** This document covers 17 publicly documented incidents and campaigns from 2000 to 2026 against drinking water, wastewater, dam, district-heating and fuel-pipeline control systems. Fifteen have their own subsection in Section 3. The two smallest, Volt Typhoon and the 2025 Norwegian dam, are covered in Section 3.13. Primary sources were used where they exist: CISA, FBI and EPA advisories, DOJ press releases and indictments, an SEC filing, sworn congressional testimony, and vendor reports from Dragos, Claroty, Mandiant and Verizon. Claims made by attackers are kept separate from impact the victims confirmed.

**Key patterns**

1. **Internet-exposed HMIs and PLCs with default or no passwords are the most common way in.** This is the access vector in the 2023 Unitronics campaign (CyberAv3ngers, TCP/20256, default password `1111`) [9][10], in the 2024 pro-Russia hacktivist HMI manipulations over VNC/5900 [16][17], and in the July 2026 MicroLogix campaign that hit more than 30 Minnesota utilities and operators in at least seven states [21][22]. None of these needed an exploit. In each case the attacker connected to a device and used its own engineering or operator interface.
2. **Remote-access tools are the second most common vector.** Examples are TeamViewer at Oldsmar [2][4], a vendor remote log-in at Muleshoe, TX [20], a former employee's remote log-in that was never revoked at Post Rock RWD, KS [6][7], a legacy single-factor VPN profile at Colonial Pipeline [26][27], and the radio link in the Maroochy sewage case [29][30].
3. **Ransomware on IT systems causes the most total disruption, even though it rarely touches the process directly.** Operators shut down OT preemptively because they cannot trust it or cannot see it. Examples: Colonial Pipeline shut down all 5,500 miles of pipeline [26], a natural gas compression facility shut down for about two days [25], and Arkansas City, American Water, Veolia and South Staffs all reported IT-only incidents [33][34][35][37]. The CISA advisory AA21-287A documents ransomware reaching SCADA servers in four U.S. water and wastewater (WWS) facilities [1].
4. **Pivots from IT into OT run through flat networks and shared credentials.** Examples: the Kemuri Water Company AS/400 that acted as both billing server and "SCADA platform" [28], an unsegmented natural-gas OT network [25], Volt Typhoon's access to OT-adjacent vCenter and PuTTY session profiles at a water utility [24], and the unsegmented Lviv heating network [18].

**What attackers did to the physical process**

- **Changed setpoints and parameters.** At Oldsmar, the sodium hydroxide setpoint was changed from 100 to 11,100 ppm [3][4]. Pro-Russia hacktivists "maxed out set points" on pumps and blowers [17]. At Kemuri, chemical dosing and flow were changed [28].
- **Started and stopped equipment.** At Muleshoe, pumps were left running until a tank overflowed [19][20]. At Post Rock RWD, the plant and a filter were shut down [7]. In the Maroochy breach, sewage pump stations were disrupted [30].
- **Replaced logic and locked out operators.** CyberAv3ngers wiped Unitronics ladder logic, renamed devices and changed ports [9]. In the 2026 MicroLogix campaign, IP addresses and passwords were changed and project files altered [21]. In one AA26-097A case, safety shutdown and alarm logic was overridden [22].
- **Denied operators visibility.** Examples are HMI defacement [9], a firmware downgrade at Lviv [18], suppressed alarms [17][30], and encrypted HMIs and historians [25].

**How much physical harm was confirmed.** Confirmed physical consequences have been modest so far: tank overflows, local flooding, loss of pressure, boil-water notices, a sewage spill of about 800,000 litres (Maroochy), a heating outage of almost two days in sub-zero weather (Lviv), and a fuel-supply crisis (Colonial). No confirmed case has harmed public health. The reasons are consistent across incidents: alert operators, alarm functions, independent safeguards, the ability to switch to manual operation, and the day or more that treated water spends in a clearwell before reaching customers. Attribution and impact claims vary in reliability. Hacktivist personas regularly exaggerate [16][17], and the most famous water "hack", Oldsmar, has never been confirmed as an external intrusion [5].

**Lessons**

- Remove all inbound internet exposure of PLCs and HMIs. Put remote access behind a gateway with MFA, and secure cellular modems [21][22].
- Change default credentials, revoke former employees' access, and stop using shared logins [8][17].
- Segment IT from OT, with a real OT DMZ for the historian and remote access. Assume IT ransomware will force an OT decision [25][26].
- Engineer independent safety limits that a compromised controller cannot override. Examples are pump-stroke or tank-size limits on chemical feed, analyzers that trip the process, and hard-wired level switches [2]. Practise manual operation [21].
- Keep known-good, offline copies of PLC logic and verify them against what is running [21][22].

---

## 2. Background: Water and Pipeline OT

### 2.1 Physical process (general engineering background)

A typical surface-water utility moves water through these stages:

1. **Intake and raw-water pumping.** Low-lift pumps draw water from a river, reservoir or wellfield.
2. **Treatment.** Coagulation and flocculation, sedimentation, filtration, then disinfection with chlorine, chloramine or UV. Most plants also adjust pH. Sodium hydroxide (caustic soda, "lye") is a common chemical for pH and corrosion control, and it is the chemical that was dosed at Oldsmar [2]. Chemical feed is usually done by metering pumps whose speed or stroke a PLC controls against a setpoint, often measured in mg/L or ppm.
3. **Clearwell.** Finished water is stored here to provide disinfectant contact time. Its residence time is one reason a dosing change does not reach customers immediately. At Oldsmar, officials said it would have taken more than a day [3].
4. **High-service and booster pumping.** These pumps push water into transmission mains and pressure zones. Booster stations, like the one at Aliquippa [11], are often remote and unstaffed and talk to the plant over radio, cellular or leased lines.
5. **Storage tanks and towers.** These sit "on the hydraulic grade" and are filled and drained by pump start/stop logic driven by level transmitters. If a pump call is forced on and the high-level cut-off is defeated or removed from the logic, the tank overflows. That is what was reported at Muleshoe [19][20] and in the 2024 hacktivist incidents [17].
6. **Distribution and wastewater collection.** Wastewater lift stations are the mirror image of booster stations and are equally remote. Plymouth, MN reported cellular-connected lift stations affected in 2026 [32].

**Pressure and water hammer.** Water mains and pipelines are designed for a rated working pressure. In regulated natural gas and hazardous-liquid pipelines this is called the Maximum Allowable Operating Pressure (MAOP). Opening or closing a valve quickly, or tripping a large pump suddenly, produces a pressure surge called water hammer that can exceed the rated pressure and burst mains or damage fittings. The opposite case also matters. The FBI warns that loss of pressure "could potentially allow untreated ground water to seep into pipes" [21], which is why low-pressure events lead to boil-water advisories.

### 2.2 Control-system architecture (Purdue reference model)

NIST SP 800-82 Rev. 3 is the U.S. reference for OT architecture and security [38]. Mapped onto a water utility, the levels look like this:

| Level | Water-utility example | Notes from incidents |
|---|---|---|
| L5/L4 Enterprise | Email, ERP, billing and customer portals (e.g., American Water "MyWater"), AD | Ransomware and phishing usually land here first [1][25][33][34] |
| L3.5 OT DMZ | Historian replica, jump host, remote-access gateway, patch server | Often missing. Colonial and the gas compression victim had no effective barrier [25][26] |
| L3 Site operations | SCADA master and polling servers, historian, engineering workstation (EWS) with VisiLogic, Studio 5000 or TIA Portal | AA20-049A ransomware encrypted the HMIs, historians and polling servers [25]. In 2026, project files were stolen using vendor engineering software [22] |
| L2 Supervisory | HMI panels and operator workstations (often reachable by VNC/RDP/TeamViewer) | VNC/5900 HMI takeovers [16][17]. TeamViewer at Oldsmar [3] |
| L1 Control | PLCs and RTUs at the plant, booster stations, lift stations and tanks; ENCO, Unitronics, MicroLogix and similar controllers | Logic wiped or replaced [9][21]. Firmware downgraded [18] |
| L0 Process | Metering pumps, valves, level and pressure transmitters, analyzers (pH, chlorine residual) | Physical effects |

**Telemetry.** Remote sites connect over licensed or unlicensed radio (as at Maroochy, which used a dedicated analog two-way radio system through repeaters [30]), cellular modems, or leased lines. Many cellular modems are given public IP addresses. That turns the PLC behind the modem into an internet-accessible device, which is the exposure FBI and EPA described in 2026 at "water towers and sewer lift stations" [21][31].

### 2.3 Industrial protocols and why they are easy to abuse

| Protocol | Default port (IANA unless noted) | Typical water/pipeline use | Authentication |
|---|---|---|---|
| Modbus TCP (MBAP) | TCP/502 [39] | PLC and RTU I/O, chemical-feed controllers, ENCO heating controllers [18] | None. Any client that can reach the port can read (FC 3) or write (FC 6/16) holding registers, as FrostyGoop did [18] |
| DNP3 | TCP/UDP 20000 (DNP-Secure: 19999) [39] | SCADA master to RTU telemetry, common in utilities | Original DNP3 has none. Secure Authentication exists but is rarely deployed |
| EtherNet/IP (CIP) | TCP/UDP 44818 explicit; 2222 I/O [39] | Rockwell/Allen-Bradley PLCs (CompactLogix, MicroLogix) | No native authentication on older devices. Protection depends on the device password, the key switch and ACLs [21][22] |
| S7comm (ISO-TSAP) | TCP/102 [39] | Siemens S7-300/1200/1500 | Legacy S7comm has none. Newer firmware adds access levels |
| Unitronics PCOM | TCP/20256 (vendor default, not IANA) [10][13] | Unitronics Vision/Samba PLC+HMI combos common in small water systems | An optional password, often left at the default `1111` [10]. CVE-2024-38434 allowed the upload password to be reset (opcode 0x42) [13] |
| OPC UA | TCP/4840 (4843 TLS) [39] | Historian and SCADA integration | Supports authentication and encryption, but these are often configured as `None` |
| VNC (RFB) | TCP/5900 | Remote HMI access | Often an empty or default password [16][17] |

These protocols were designed for closed serial networks and assumed that anything able to send a frame was trusted. They have no session authentication, no message integrity, and the same function codes do both reading and writing [38]. In practice, network reachability equals control. That is why "Internet Accessible Device" (T0883) followed directly by "Unauthorized Message" (T1692.001) or "Modify Parameter" (T0836) recurs throughout Section 3.

---

## 3. Incident Case Studies

Each case lists ATT&CK for ICS techniques. **(src)** means the source itself made the mapping, either MITRE's campaign page or the advisory. **(analyst)** means I mapped it from the reported facts.

### 3.1 Maroochy Shire sewage system, Queensland, Australia (2000), insider using radio

- **Date:** 9 Feb to 23 Apr 2000. At least 46 occasions, starting 28 Feb [30].
- **Victim:** Maroochy Shire Council sewerage system: 142 sewage pumping stations, two monitoring computers, three radio frequencies [30].
- **Actor:** Vitek Boden. He had been site supervisor on the SCADA project for the integrator Hunter Watertech, resigned in December 1999, and was then refused a job by the Council [30].
- **Initial access:** Stolen radio equipment and a (possibly stolen) computer with the vendor's configuration software, used to talk to the PDS Compact 500 units at the pump stations over the dedicated analog two-way radio network [30].
- **Techniques:** T0822 External Remote Services, T0860 Wireless Compromise, T0864 Transient Cyber Asset, T0848 Rogue Master, T1692.001 Unauthorized Message: Command Message (formerly T0855), T1692.002 Reporting Message (formerly T0856), T0836 Modify Parameter, T0838 Modify Alarm Settings, T0878 Alarm Suppression, T0813/T0815 Denial of Control/View, T0879 Damage to Property **(src)** [29].
- **Physical impact:** Pumps did not run when they should have, alarms stopped reporting, communications were lost, and about 800,000 litres of raw sewage spilled into parks, rivers and hotel grounds [30].
- **Detection and response:** A Hunter Watertech engineer recorded radio traffic and found a bogus "station 14". He renumbered the real station to tell real messages from fake ones and was briefly locked out of the network himself. Boden was caught during a traffic stop. He was sentenced to two years [30].
- **Key point:** Spoofing a master over an unauthenticated telemetry link worked in 2000 and still works against unauthenticated Modbus and DNP3 today.

### 3.2 "Kemuri Water Company" (Verizon Data Breach Digest, 2016), IT-to-OT through a single AS/400

- **Source note:** This scenario appears in Verizon's *Data Breach Digest* (2016), Scenario 8 "Hacktivist attack: the Dark Shadow", pp. 38-41 [28]. It is not in the annual DBIR. "Kemuri Water Company" is a pseudonym. The actor is listed as an activist group, disposition "Unknown, Syria" [28].
- **Architecture flaw:** One AS/400 that the utility called its "SCADA platform" acted as a router into several networks, ran the "valve and flow control application" that drove "hundreds of Programmable Logic Controllers," and also held customer PII, billing and financials. Only one employee could administer it [28].
- **Initial access:** The attackers exploited a known vulnerability in the internet-facing customer payment application. The AS/400's internal IP and administrative credentials were stored "in clear text within an initialization (.ini) file" on that web server, and the AS/400 also had direct internet access [28].
- **Techniques (analyst):** T0819 Exploit Public-Facing Application, T0859 Valid Accounts, T0886 Remote Services, T0836 Modify Parameter, T0831 Manipulation of Control, T0882 Theft of Operational Information (plus more than 2.5 million customer records exfiltrated).
- **Physical impact:** Four connections over 60 days. In at least two, the actors "managed to manipulate the system to alter the amount of chemicals that went into the water supply" and affected flow rates. "Based on alert functionality," the utility reversed the changes quickly [28].
- **Key point:** A billing system wired directly to the process controller, with credentials sitting on the web tier, gave a one-hop path from the internet to the process.

### 3.3 Post Rock Rural Water District, Ellsworth County, Kansas (March 2019), former employee

- **Date:** 27 March 2019. Indicted March 2021, guilty plea later in 2021 [6][7][8].
- **Victim:** Ellsworth County Rural Water District No. 1, also called Post Rock Rural Water District [6].
- **Actor:** Wyatt Travnichek, employed January 2018 to January 2019. His job included monitoring the plant after hours through a remote log-in system [7].
- **Initial access:** His remote-access credentials were not revoked after he resigned. CISA AA21-287A describes the case as a former employee using "credentials that had not been revoked" [1].
- **Techniques (analyst):** T0859 Valid Accounts, T0822 External Remote Services, T0816 Device Restart/Shutdown, T0881 Service Stop, T0826 Loss of Availability.
- **Physical impact:** According to the plea, the remote log-in "was used to shut down the plant and turn off one of its filters." The indictment described the shutdown as affecting "cleaning and disinfecting procedures." Investigators tied the intrusion to his phone [7][8].
- **Outcome:** He pleaded guilty to tampering with a public water system and reckless damage to a protected computer. EPA and FBI recommended 12 months and a day [7]. I could not verify the final sentence from a primary source.
- **Key point:** Revoking access when staff leave is an OT control. EPA's 2024 enforcement alert still lists "failed to curtail access by former employees" as a common finding [8].

### 3.4 Oldsmar, Florida water treatment plant (5 February 2021): the canonical case, with an important caveat

- **Victim:** City of Oldsmar water treatment plant, serving about 15,000 people [3].
- **What was reported in 2021:** The operator saw remote access at about 8 a.m. and assumed it was a supervisor. At about 1:30 p.m., someone remotely took over the screen, moved the mouse, and raised the sodium hydroxide setpoint from 100 ppm to 11,100 ppm. The operator reversed it immediately [3][4]. The Pinellas County Sheriff's Office confirmed the remote-access tool was TeamViewer [4]. A Massachusetts DEP advisory said all plant computers ran 32-bit Windows 7, "shared the same password for remote access" and "appeared to be connected directly to the Internet without any type of firewall protection" [5a]. CISA AA21-042A said the actors "likely" exploited poor password security and an outdated OS, and listed desktop-sharing software such as TeamViewer as a likely vector [2].
- **Techniques (analyst, as originally reported):** T0822 External Remote Services, T0883 Internet Accessible Device, T0859 Valid Accounts, T0823 Graphical User Interface, T0836 Modify Parameter, T0831 Manipulation of Control.
- **Physical impact:** None. Officials said other safeguards and the more than a day of transit time meant the public was "never in danger" [3]. CISA noted the change was reversed before the SCADA alarm fired [2].
- **2023 reassessment (important):** In March 2023, former City Manager Al Braithwaite said at a public-administration conference that the event was a "non-event" probably caused by employee error [5][5b]. Asked by the *Tampa Bay Times*, FBI Tampa stated: "Through the course of the investigation the FBI was not able to confirm that this incident was initiated by a targeted cyber intrusion of Oldsmar" [5].
- **Assessment:** The insecure configuration (shared TeamViewer password, Windows 7, no firewall) is well documented. A malicious external actor is **not confirmed**. Treat Oldsmar as a case study in exposure and safeguard design, not as a proven poisoning attempt.

### 3.5 Ransomware reaching WWS SCADA (2020-2021), from CISA AA21-287A

CISA, FBI, EPA and NSA described the following confirmed incidents [1]:

| Date | Location | Detail |
|---|---|---|
| Sep 2020 | New Jersey | Potential Makop ransomware compromised files |
| Mar 2021 | Nevada | Unknown variant hit SCADA and backup systems |
| Jul 2021 | Maine | ZuCaNo ransomware introduced through remote access onto a wastewater SCADA computer. The plant ran manually until restored |
| Aug 2021 | California | Ghost variant. Three SCADA servers showed a ransom message after the actor had been present for about a month |

- **Techniques:** The advisory cites T1566 Phishing, T1210 Exploitation of Remote Services (e.g., exposed RDP/3389) and T0827 Loss of Control [1]. For ICS (analyst): T0866 Exploitation of Remote Services, T0886 Remote Services, T0826 Loss of Availability, T0829 Loss of View.
- **Key point:** Commodity ransomware does not need ICS knowledge to take out the Windows SCADA layer. Manual operation is then the only fallback.

### 3.6 Natural gas compression facility (CISA AA20-049A, Feb 2020), ransomware affecting pipeline operations

- **Initial access:** A spearphishing link (T1192 in the then-current Enterprise numbering) into IT, then a pivot to OT because there was no "robust segmentation" [25].
- **Impact:** Commodity ransomware encrypted Windows systems on both networks. In OT that meant HMIs, data historians and polling servers. PLCs were not affected and the operator never lost control. The operator ordered a deliberate shutdown of about two days. Other compression facilities on the same pipeline also halted because of dependencies [25].
- **Techniques (src):** T0826 Loss of Availability, T0829 Loss of View, T0828 Loss of Productivity and Revenue [25].
- **Lesson cited by CISA:** The emergency response plan covered physical threats but not cyber ones, and exercises gave staff no practice at cyber decisions [25].

### 3.7 Colonial Pipeline (May 2021): IT ransomware, OT shutdown

- **Victim:** A 5,500-mile refined-products pipeline carrying "nearly half of the fuel consumed on the East Coast" [26].
- **Actor:** The DarkSide ransomware group [26].
- **Initial access:** "a legacy virtual private network (VPN) profile that was not intended to be in use" [26]. Under questioning, the CEO confirmed it "did only have single-factor authentication. It was a complicated password" [27]. How the credential was obtained was not determined at the time of testimony [26].
- **Timeline:** A ransom note was found on an IT system just before 5:00 a.m. EDT on 7 May. The Control Center issued a stop-work order. Shutdown began at about 5:55, and by 6:10 "all 5,500 miles of pipelines had been shut down" to keep malware from reaching OT. Return to service began on the evening of 12 May. During restart, staff "drove over 29,000 miles" inspecting the line and manually reported pipeline data "while our OT was not visible" [26]. A ransom of $4.4 million was paid [27].
- **Techniques (analyst):** T0822 External Remote Services, T0859 Valid Accounts (Enterprise: T1133, T1078, T1486). Impact: T0828 Loss of Productivity and Revenue and T0826 Loss of Availability, both caused by the operator's own shutdown.
- **Key point:** The attacker never touched OT, and the pipeline still stopped. A red-team report that shows a credible route from IT to OT can be as consequential as a demonstrated write to a PLC.

### 3.8 Unitronics Vision PLCs: CyberAv3ngers (IRGC-CEC), Nov 2023 to Jan 2024, including Aliquippa, PA

- **Actor:** CyberAv3ngers, an IRGC-affiliated persona [9]. Treasury sanctioned six IRGC Cyber-Electronic Command officials on 2 Feb 2024 for these attacks [12]. MITRE tracks the activity as G1027 and campaign C0031 [14].
- **Victims:** Starting 22 Nov 2023, at least 75 devices in the U.S. were compromised, at least 34 of them in the WWS sector, plus victims in other countries [9]. The best-known case is the **Municipal Water Authority of Aliquippa**. Attackers took over a booster station that "monitors and regulates pressure for Raccoon and Potter Townships." An alarm sounded and the authority said there was no known risk to drinking water [11]. CISA reported that the utility took the system offline and switched to manual operations [10].
- **Initial access:** Internet-exposed Unitronics Vision Series PLC/HMIs with default or no passwords, authenticating over TCP/20256. CISA told owners to make sure the default password `1111` is not in use [9][10].
- **Actions on the device** [9]:
  - Erased the ladder logic and downloaded a project with no inputs or outputs.
  - Renamed the device. The name is a required connection field, so this broke remote connections.
  - Changed the software version so the engineering workstation could not connect.
  - Disabled upload and download and set an upload password.
  - Changed the PCOM port from 20256 to 20257.
  - Did not "burn" the project, so it could not be recovered from the device.
  - Displayed a splash screen reading: "You have been hacked, down with Israel. Every equipment 'made in Israel' is CyberAv3ngers legal target."
- **Forensics:** Claroty Team82 showed that the attackers used VisiLogic to download the malicious project. It recovered artifacts from the PLC Signature Log, including connection dates, the attacker's project path, PC username, OS and keyboard layout. The research also disclosed CVE-2024-38434 (upload-password reset via PCOM opcode 0x42) and CVE-2024-38435 (DoS) [13].
- **Techniques:**
  - Source mapping [14]: T0883 Internet Accessible Device, T1694.001 Default Credentials (formerly T0812), T0814 Denial of Service, T0826 Loss of Availability, T0828 Loss of Productivity and Revenue, T0829 Loss of View.
  - Analyst additions: T0843 Program Download and T0889 Modify Program (logic replaced), T0892 Change Credential (upload password set), T0836 Modify Parameter (port and name changed).
- **Physical impact:** Limited. Treasury said the operation "did not disrupt any critical services" [12]. The Aliquippa booster station ran manually. MITRE also notes "a communications failure at a remote pumping station" [14].
- **Key point:** Being "Made in Israel" was the targeting criterion. Exposure on the internet was the only precondition.

### 3.9 IOCONTROL (CyberAv3ngers, reported Dec 2024): custom malware for OT and IoT devices, including fuel systems

- **Source:** Claroty Team82, 10 Dec 2024 [15]. Team82 assesses the malware as an IRGC-CEC/CyberAv3ngers cyberweapon. Attribution is Team82's assessment.
- **Targets:** Linux-based IoT and OT devices from Baicells, D-Link, Hikvision, Red Lion, Orpak, Phoenix Contact, Teltonika, Unitronics and others. The analyzed sample was taken from a Gasboy fuel-management system's OrPT payment terminal. Team82 reports that "several hundred" Orpak and Gasboy fuel-management systems in Israel and the U.S. were compromised [15].
- **Technical details** [15]:
  - ARM 32-bit big-endian binary, packed with modified UPX (magic `UPX!` changed to `ABC!`).
  - Configuration encrypted with AES-256-CBC.
  - C2 over MQTT on TCP/8883 (TLS), with topics `{GUID}/hello`, `{GUID}/push` and `{GUID}/output`. The C2 hostname is resolved through Cloudflare DNS-over-HTTPS.
  - Persistence through `/etc/rc3.d/S93InitSystemd.sh`, with the binary at `/usr/bin/iocontrol`.
  - Opcodes: 0 = hello, 1 = check exec, 2 = arbitrary shell command, 3 = self-delete, 8 = port scan.
- **Techniques (analyst):** T0883 Internet Accessible Device, T0869 Standard Application Layer Protocol, T0885 Commonly Used Port, T0846 Remote System Discovery (port scan), T1701 Command and Scripting Interpreter, T0872 Indicator Removal on Host.
- **Key point:** The same actor moved from nuisance defacement to persistent, stealthy implants on field devices, including fuel distribution.

### 3.10 Pro-Russia hacktivists against water HMIs (2022-2025): CARR, Muleshoe TX, and the Z-Pentest lineage

- **Muleshoe, Texas (Jan 2024):** On 17-18 Jan 2024, the CyberArmyofRussia_Reborn (CARR) Telegram channel posted videos claiming HMI manipulation at U.S. and Polish water utilities [19]. The City of Muleshoe stated that on 18 Jan 2024 its SCADA system "was compromised through a third-party vendor's remote log-in system" and that the disinfection system was not affected [20]. The city manager told CNN (as reported by AP) that the water system overflowed before officials shut it down and ran it manually [31a]. Nearby Hale Center counted "37,000 attempts in four days to log into our firewall" and unplugged the system [31a].
- **Attribution chain:**
  - Mandiant (Apr 2024) judged that APT44 (Sandworm, GRU) operators "have the ability to direct and influence" CARR. It said it "cannot independently verify" the claimed water intrusions, but noted a local official confirmed a "system malfunction" that caused a tank overflow [19].
  - CISA AA25-343A (Dec 2025) assessed that GRU unit 74455 "likely" supported CARR's creation. It said disaffected CARR and NoName057(16) administrators later formed **Z-Pentest** (Sep 2024), which focuses on OT intrusions [17].
  - DOJ (9 Dec 2025) charged Ukrainian national Victoria Dubranova over CARR and NoName057(16). DOJ alleged CARR was "founded, funded, and directed" by the GRU, and that its victims included "public drinking water systems across several states," with "damage to controls and the spilling of hundreds of thousands of gallons of drinking water" [23]. These are allegations. I did not verify a trial outcome.
- **TTPs (CISA, May 2024 fact sheet and AA25-343A)** [16][17]:
  - Scan for VNC on 5900 and 5901-5910.
  - Brute-force or spray passwords from rented VPS infrastructure.
  - Log in to HMIs with default, weak or no passwords.
  - Use the operator GUI to "max out" setpoints, change limits, disable alarms, rename devices, and change passwords to lock operators out.
  - Take screenshots and video for propaganda.
  - Several compromised HMIs were "unsupported legacy, foreign-manufactured devices rebranded as U.S. devices" [16].
- **Techniques (src, AA25-343A)** [17]: T0883, T0886 Remote Services, T0823 Graphical User Interface, T0812 Default Credentials (now T1694.001), T0859, T0836 Modify Parameter, T0892 Change Credential, T0831 Manipulation of Control, T0878 Alarm Suppression, T0829 Loss of View, T0816 Device Restart/Shutdown, T0855 Unauthorized Command Message (now T1692.001), T0828.
- **Physical impact (confirmed by CISA):** "water pumps and blower equipment to exceed their normal operating parameters… Some victims experienced minor tank overflow events" [16]. AA25-343A adds that impacts have included "physical damage" in some cases, and that the groups "frequently misrepresent their capabilities" [17].

### 3.11 FrostyGoop, Lviv district heating (Jan 2024): Modbus-native ICS malware against a hot-water distribution network

District heating is a pressurized hot-water pipe network with pumps and controllers, so it is the closest documented analogue to a water-distribution attack using purpose-built Modbus malware.

- **Victim:** A municipal district energy company in Lviv, Ukraine, supplying more than 600 apartment buildings. Remediation took almost two days in sub-zero temperatures [18].
- **Intrusion chain** [18]:
  1. Likely exploitation of an "undetermined vulnerability in an externally facing router."
  2. A ReGeorg-like tunneling webshell accessed over Tor.
  3. Credential theft from the SAM hive.
  4. L2TP connections to Moscow-based IP addresses.
  5. Modbus commands sent from attacker hosts to ENCO controllers through hard-coded routes on an unsegmented network.
- **Malware:** A Golang Windows binary that reads and writes holding registers (FC 3, 6 and 16) on TCP/502 from a JSON task file (`task_test.json`). Dragos also notes more than 46,000 internet-exposed Modbus TCP devices worldwide [18].
- **Effect:** The firmware on the ENCO controllers was **downgraded** to a version that lacked monitoring capability, causing loss of view. The controllers were made to report inaccurate measurements, so the system ran incorrectly and heating was lost [18].
- **Techniques (src, MITRE S1165/C0041):** T0836 Modify Parameter, T0801 Monitor Process State, T0869 Standard Application Layer Protocol, T0885 Commonly Used Port, T1701 Command and Scripting Interpreter [36]. Analyst additions: T1693 Modify Firmware (formerly T0857), T0829 Loss of View, T0832 Manipulation of View, T0826 Loss of Availability.

### 3.12 July 2026 multi-state attacks on water and wastewater PLCs (Minnesota and others): MicroLogix 1100/1400

- **Date and scope:** On 26-27 July 2026, Minnesota IT Services reported a "coordinated cyberattack" on more than 30 community water systems [32]. FBI and EPA reported that since 27 July, WWS utilities "in at least seven states" had reported incidents [21]. MITRE tracks this as campaign C0066 [31].
- **Products and access** [21]:
  - Internet-exposed Rockwell/Allen-Bradley MicroLogix 1100 and 1400 PLCs, many reached through cellular gateways at towers and lift stations [31].
  - The actors changed the IP addresses, "turning on and setting passwords," which caused loss of view and in some cases loss of function.
  - At least one victim found modified project files and ladder-logic discrepancies across several sites.
  - Similar network setups provided by the same third parties let the actors "multiply successes."
- **Physical impact:** FBI reported "loss of pressure and flooding" [21]. In Braham, MN (population about 1,700), the computerised controls for the well and treatment plant were disabled and the plant went offline for about two hours [32b]. Plymouth disconnected cellular-connected equipment at two water towers and ran manually [32b]. Minnesota reported no change in drinking-water use [32].
- **Related advisory:** CISA AA26-097A (Apr 2026, updated 22 Jul 2026) describes an Iranian-affiliated APT exploiting internet-facing Rockwell CompactLogix/Micro850, Schneider M340 and Siemens S7-1200 PLCs [22]:
  - Ports 44818, 2222, 102 and 502, plus Dropbear SSH on modems over port 22.
  - Project files exfiltrated using Studio 5000, EcoStruxure Control Expert and TIA Portal.
  - In one victim, Add-On Instructions were modified so the logic "overrode specific instruction sets responsible for maintaining safe operating parameters" and "disabled critical shutdown and alarm logic."
- **Attribution:** None has been made public for the Minnesota and seven-state activity. Vendor blogs suggest an Iranian link, and the media noted the timing relative to AA26-097A, but no agency has confirmed a connection [32b]. One vendor blog attributes the access to CVE-2021-22681. The FBI PSA names no CVE, and AA26-097A states it "is not highlighting a new vulnerability," so treat the CVE claim as unverified.
- **Techniques (src, C0066)** [31]: T0883, T1694.001 Default Credentials, T0892 Change Credential, T0836 Modify Parameter (IP), T0889 Modify Program, T0813 Denial of Control, T0827 Loss of Control, T0829 Loss of View, T0826 Loss of Availability. Analyst additions from AA26-097A: T0845 Program Upload, T0882 Theft of Operational Information, T0838 Modify Alarm Settings, T0880 Loss of Safety.

### 3.13 Other verified incidents (shorter entries)

- **Israel water sector (Apr-Jul 2020):**
  - On 23 Apr 2020, the Israel National Cyber Directorate warned of attempted attacks on SCADA at wastewater plants, pumping stations and sewage systems. It urged password changes on internet-connected systems, "especially" those controlling chlorine dosing [40].
  - On 28 May 2020, INCD head Yigal Unna called it a "synchronized and organized attack" and said chlorine or other chemicals could have been mixed at the wrong levels with a "harmful and disastrous" result [41]. Attribution to Iran comes only from anonymous officials in press reports.
  - In July 2020, the Water Authority confirmed two more attacks, on agricultural pumps in the Upper Galilee and on infrastructure in central Israel, with no damage [42].
- **Volt Typhoon (PRC, AA24-038A, Feb 2024):**
  - Pre-positioning in WWS IT environments "to enable lateral movement to OT assets" [24].
  - At one water utility: VPN access with admin credentials, then RDP over nine months to a file server, a DC and vCenter. The actors pulled SCADA diagrams, enumerated PuTTY sessions that "may have exposed" profiles for water treatment plants and wells, and tested default OT vendor credentials [24].
  - In one compromise, they "moved laterally to a control system and were positioned to move to a second" [24].
  - Techniques (analyst): T0886, T0859, T0882, T0811 Data from Information Repositories, T1694.001.
- **IT-only incidents that forced OT caution:**
  - **South Staffordshire Water** (Aug 2022): corporate IT disrupted while supply stayed safe [37]. Cl0p first named Thames Water by mistake, then leaked SCADA screenshots, but SCADA control was never demonstrated [37a].
  - **Veolia North America** (Jan 2024): ransomware in back-end systems, billing delayed, no treatment impact [35].
  - **American Water Works** (Oct 2024): 8-K filed after "unauthorized activity" was found on 3 Oct; certain systems disconnected; no believed impact to water or wastewater operations [33].
  - **Arkansas City, KS** (22 Sep 2024): the treatment plant "switched to manual operations" as a precaution, with no service disruption [34]. The root cause has not been published.
- **Bremanger dam, Norway (Apr 2025):** Attackers opened outflow valves through a control system for about four hours, releasing more than 7.2 million litres. Norway's PST attributed it to pro-Russian hackers in August 2025 [43].

---

## 4. Cross-Incident Technical Analysis

### 4.1 Attack-path patterns

**Pattern A: Direct internet exposure of L1 and L2 assets (most common)**

`Shodan/Censys or masscan → PLC/HMI port (20256, 5900, 44818, 502) → default/no password → vendor tool or VNC → setpoint/logic/credential change`

Seen in the Unitronics campaign [9], the CARR/Z-Pentest HMI attacks [16][17], the July 2026 MicroLogix campaign [21], FrostyGoop pre-attack targeting [18], and Israel 2020 [40].

*Defenses that would have stopped it:*
- No inbound internet exposure. Cellular modems on a private APN, behind a VPN, or with no public IP [21].
- Non-default PLC and HMI passwords, and the key switch held in RUN [21][22].
- An ACL on the PLC that allows only the SCADA master's IP [21].

**Pattern B: Remote-access software or a VPN with weak authentication (L2/L3)**

`Valid credential (shared, legacy, ex-employee, vendor) → TeamViewer/VPN/vendor portal → HMI/EWS → operate GUI`

Seen at Oldsmar (TeamViewer, shared password) [2][5a], Post Rock (ex-employee) [7], Muleshoe (vendor log-in) [20], Colonial (legacy single-factor VPN) [26][27], and Maine ZuCaNo (remote access) [1].

*Defenses:* MFA on every remote path, an inventory of remote-access tools, joiner/mover/leaver processes that include OT, vendor access brokered and recorded through an OT DMZ jump host, and TeamViewer unattended access disabled [2].

**Pattern C: IT compromise with a pivot, or forced OT shutdown (L4 → L3)**

`Phishing/exposed service/edge-device exploit → AD credential theft → shared credentials/dual-homed host/flat routing → historian, EWS, HMI, vCenter`

Seen at the AA20-049A gas compression facility [25], Kemuri (credentials in an .ini file, AS/400 bridging IT and OT) [28], Volt Typhoon (vCenter adjacent to OT, PuTTY profiles, NTDS.dit reuse) [24], Lviv (router → webshell → SAM → Modbus) [18], and Colonial (precautionary shutdown) [26].

*Defenses:*
- A true L3.5 DMZ where the historian **pushes** data out.
- No AD trust between the IT and OT domains.
- No dual-homed hosts.
- Separate credentials for OT.
- Firewalls between OT zones that allow only the protocols expected between those zones [25].
- Offline backups of HMI, historian and PLC projects.
- A tested decision to "isolate OT, run manual" rather than a blanket shutdown.

**Pattern D: Insider or former contractor**

Seen at Maroochy [30] and Post Rock [7]. The insider knows the protocols, addresses and procedures, so technical barriers matter less than revoking access and watching for anomalies: unusual radio traffic at Maroochy, after-hours log-ins at Post Rock.

### 4.2 What made the physical consequences small

- **Humans in the loop.** Operators at Oldsmar, Kemuri and Aliquippa noticed alarms or screen activity [3][11][28].
- **Process time constants.** Clearwell storage and distribution travel time give hours to days before a dosing change reaches customers [3].
- **Independent safeguards.** CISA recommends physical limits that a controller cannot override, such as pump size and reservoir size [2]. The 2026 AOI attack was dangerous precisely because it targeted the software version of these safeguards [22].
- **Ability to operate manually.** Every utility that recovered quickly had this capability [16][21][26].

### 4.3 Evidence quality

| Incident | Intrusion confirmed? | Physical impact confirmed? | Attribution |
|---|---|---|---|
| Maroochy | Yes (conviction) | Yes | Individual (convicted) |
| Kemuri | Yes (Verizon IR) | Yes (dosing/flow changes) | "Activist", unnamed |
| Post Rock | Yes (guilty plea) | Yes (shutdown) | Individual (pleaded guilty) |
| Oldsmar | **Not confirmed** (FBI 2023) | Setpoint change only | None |
| Unitronics 2023 | Yes (CISA) | Limited | IRGC-CEC (USG, sanctions) |
| Muleshoe | Yes (city) | Tank overflow | CARR claim; Mandiant could not verify |
| CARR/Z-Pentest generally | Yes (CISA) | Minor overflows; some damage | GRU link per USG (alleged in indictment) |
| Lviv/FrostyGoop | Yes (SBU via Dragos) | Yes | Not attributed by Dragos |
| July 2026 MicroLogix | Yes (FBI/EPA) | Pressure loss, flooding | Not attributed |
| Israel 2020 | Attempts (INCD) | None | Iran per anonymous officials |

---

## 5. TTP-to-ATT&CK for ICS Mapping

### 5.1 Note on renumbered techniques (ATT&CK v20)

These checks were made on attack.mitre.org on 16 Oct 2026 [44]:

- **T0812** Default Credentials now redirects to **T1694.001** Insecure Credentials: Default Credentials.
- **T0891** Hardcoded Credentials now redirects to **T1694.002**.
- **T0855** Unauthorized Command Message now redirects to **T1692.001** Unauthorized Message: Command Message.
- **T0856** Spoof Reporting Message now redirects to **T1692.002**.
- **T0857** System Firmware now redirects to **T1693.001** (Modify Firmware).

Older advisories such as AA25-343A use the legacy IDs. The other IDs used in this document (T0883, T0822, T0836, T0831, T0886, T0866, T0816, T0826, T0828, T0879, T0829, T0878, T0892, T0889, T0843) are still current.

### 5.2 Mapping table

| Tactic | Technique (ID) | Observed in |
|---|---|---|
| Initial Access | Internet Accessible Device (T0883) | Unitronics [9][14], CARR/Z-Pentest [17], MicroLogix 2026 [31], FrostyGoop [18], Oldsmar [5a] |
| Initial Access | External Remote Services (T0822) | Maroochy [29], Oldsmar, Post Rock, Muleshoe, Colonial [26] |
| Initial Access | Exploit Public-Facing Application (T0819) | Kemuri [28], Lviv router [18], Volt Typhoon edge devices [24] |
| Initial Access | Exploitation of Remote Services (T0866) | Exposed RDP and ransomware [1] |
| Initial Access / Lateral Movement | Remote Services (T0886) | VNC HMIs [17], Volt Typhoon RDP [24], Kemuri |
| Initial Access / Lateral Movement | Valid Accounts (T0859) | Post Rock, Colonial, Volt Typhoon, CARR [17] |
| Lateral Movement / Persistence | Insecure Credentials: Default (T1694.001, formerly T0812) | Unitronics `1111` [10][14], VNC HMIs [17], MicroLogix [31], Volt Typhoon vendor defaults [24] |
| Initial Access | Wireless Compromise (T0860) | Maroochy radio [29] |
| Execution | Graphical User Interface (T0823) | Oldsmar, CARR HMIs [17] |
| Execution | Command and Scripting Interpreter (T1701) | FrostyGoop [36], IOCONTROL [15] |
| Collection | Program Upload (T0845) / Theft of Operational Information (T0882) | AA26-097A project exfiltration [22], Volt Typhoon diagrams [24], Kemuri |
| Collection | Monitor Process State (T0801) | FrostyGoop [36] |
| Command and Control | Commonly Used Port (T0885) / Standard App Layer Protocol (T0869) | FrostyGoop Modbus/502 [36], IOCONTROL MQTT/8883 [15] |
| Impair Process Control | Modify Parameter (T0836) | Oldsmar, Kemuri, CARR setpoints [17], FrostyGoop [36], MicroLogix IP changes [31] |
| Impair Process Control | Unauthorized Message: Command (T1692.001, formerly T0855) | Maroochy [29], CARR [17], FrostyGoop Modbus writes |
| Impair Process Control | Modify Firmware (T1693, formerly T0857) | Lviv ENCO downgrade [18] |
| Inhibit Response Function | Modify Program (T0889) / Program Download (T0843) | Unitronics logic wipe [9], MicroLogix logic [31], AOI tampering [22] |
| Inhibit Response Function | Alarm Suppression (T0878) / Modify Alarm Settings (T0838) | Maroochy [29], CARR [17], AA26-097A [22] |
| Inhibit Response Function | Change Credential (T0892) | CARR lockout [17], MicroLogix passwords [31], Unitronics upload password [9] |
| Inhibit Response Function | Device Restart/Shutdown (T0816) / Service Stop (T0881) | Post Rock [7], CARR [17] |
| Inhibit Response Function | Denial of Service (T0814) | Unitronics HMI defacement [14] |
| Impact | Manipulation of Control (T0831) | Kemuri, CARR [17], Muleshoe |
| Impact | Loss of View (T0829) / Manipulation of View (T0832) | AA20-049A [25], Unitronics [14], Lviv [18], MicroLogix [31] |
| Impact | Loss/Denial of Control (T0827/T0813) | MicroLogix [31], Maroochy [29], AA21-287A [1] |
| Impact | Loss of Availability (T0826) | AA20-049A [25], Colonial, Unitronics, MicroLogix, Lviv |
| Impact | Loss of Productivity and Revenue (T0828) | AA20-049A [25], Colonial, Unitronics [14] |
| Impact | Loss of Safety (T0880) | AA26-097A safety/alarm logic disabled [22] |
| Impact | Damage to Property (T0879) | Maroochy sewage spill [29], tank overflows and flooding [16][21] |

---

## 6. Lessons for Red Teams

### 6.1 Rules of engagement for real OT assessments

1. **Never write to production controllers without explicit, written, per-action authorization and an operator on the phone.** Every confirmed physical effect in Section 3 came from ordinary writes: setpoints, logic downloads, and password or IP changes. Your write would have the same effect.
2. **Discover passively first.** Use SPAN/TAP captures, historian tag lists, and engineering documents from file shares (Volt Typhoon got its OT map this way [24]). Many PLCs and RTUs misbehave under aggressive scanning. If active scanning is approved, limit it to protocol-aware identification at low rates (e.g., Modbus FC 43/14 device ID, CIP List Identity, PCOM ID), and never run sweeping NSE scripts against Level 1.
3. **Prove impact without causing it.** Acceptable evidence includes:
   - A packet capture showing the PLC accepts unauthenticated reads (FC 3) on registers whose meaning you have identified from the HMI or historian. This shows writes (FC 6/16) on the same path would also be accepted, as FrostyGoop demonstrates [18].
   - A screenshot of an HMI session reached with default or shared credentials, taken without clicking any control.
   - A read of PLC project or logic (program upload, T0845), compared with the documented safety interlocks to show which ones exist only in software [22].
   - Network evidence of a path from IT or the internet to Level 1 (routes, firewall rules, dual-homed hosts, shared accounts).
4. **Use a digital twin or test bench for destructive demonstrations.** Clone the PLC model and project, or use a vendor simulator, and show the overflow, dosing or lockout scenario there.
5. **Coordinate with operations.** Confirm the manual-operation fallback and an abort word, avoid chemical-delivery and high-demand periods, and agree beforehand what "stop" means.

### 6.2 Emulation plans derived from real incidents

| Scenario | Real-world basis | What to demonstrate |
|---|---|---|
| Internet-to-HMI | CARR/Z-Pentest VNC [17], Unitronics [9] | Exposed services found by OSINT or scanning. Successful authentication with defaults. Read-only HMI screenshot |
| Remote-access abuse | Oldsmar [5a], Muleshoe [20], Colonial [27] | Inventory of unmanaged remote tools. Shared or legacy credentials. Missing MFA |
| IT-to-OT pivot | AA20-049A [25], Kemuri [28], Volt Typhoon [24] | Credential reuse into OT, historian or EWS reachable from IT, OT documents on IT shares |
| Logic and safety integrity | AA26-097A AOI tampering [22], Unitronics [9] | Upload logic (read only) and show which interlocks are software-only. Recommend hard-wired limits |
| Insider/leaver | Post Rock [7], Maroochy [30] | Active accounts of former staff or vendors. Unmonitored radio or cellular telemetry |

### 6.3 Applying this in the WaterWorks Pipeline range

The range follows the Purdue model: Internet DMZ, corporate IT, an OT DMZ with a historian, a SCADA/HMI segment with web and VNC access, and field PLCs/RTUs that speak Modbus/TCP and PCOM. That lets players work through Patterns A to C in a safe environment:

- **Web and contractor portal to corporate IT.** Kemuri-style credential exposure and Muleshoe-style vendor remote access.
- **Corporate IT to historian, then HMI.** AA20-049A and Volt Typhoon style pivots through shared credentials and dual-homed or over-trusted services.
- **HMI over VNC with shared or default credentials.** CARR/Z-Pentest TTPs.
- **Direct unauthenticated Modbus reads and writes and PCOM reads against the intake, chemical-feed and booster controllers.** FrostyGoop and Unitronics TTPs. In the range, a write is the scored impact. In a real assessment, the same finding should be reported with read-only evidence plus a digital-twin demonstration.

Write findings in terms of **consequence**: "an attacker on the corporate network can change the caustic dosing setpoint with no authentication; the only barrier is operator vigilance". That is the language that drove the fixes recommended by CISA, EPA and FBI throughout Section 3.

---

## 7. References

All URLs were retrieved and checked between 14 and 16 Oct 2026, except where a note says otherwise.

1. CISA/FBI/EPA/NSA, AA21-287A, *Ongoing Cyber Threats to U.S. Water and Wastewater Systems*, 14 Oct 2021. https://www.cisa.gov/news-events/cybersecurity-advisories/aa21-287a
2. CISA, AA21-042A, *Compromise of U.S. Water Treatment Facility*, 11 Feb 2021. https://www.cisa.gov/news-events/cybersecurity-advisories/aa21-042a
3. The Register, "Florida water treatment plant hacked…", 9 Feb 2021. https://www.theregister.com/2021/02/09/florida_water_hacked/
4. TechTarget/SearchSecurity (A. Culafi), "Florida city's water nearly poisoned in TeamViewer attack", 9 Feb 2021. https://www.techtarget.com/cybersecurity/news/252496102/Florida-citys-water-nearly-poisoned-in-TeamViewer-attack
5. Tampa Bay Times (J. Evans), "Cyberattack on Oldsmar's water supply never happened, official says", 11 Apr 2023 (contains the FBI Tampa statement). https://www.tampabay.com/news/pinellas/2023/04/11/oldsmar-cyberattack-water-supply-poisoning-fbi-update
   - 5a. iTWire, "Breached water plant ran Windows 7, used single password for TeamViewer" (quotes the Massachusetts DEP advisory), 11 Feb 2021. https://www.itwire.com/security/breached-water-plant-ran-windows-7,-used-single-password-for-teamviewer.html
   - 5b. Water Online, "Former Official Claims Oldsmar Drinking Water 'Hack' Was Really Operator Error", 29 Mar 2023. https://www.wateronline.com/doc/former-official-claims-oldsmar-drinking-water-hack-was-really-operator-error-0001
6. U.S. Attorney's Office, D. Kansas, "Kansas Man Indicted for Tampering with a Public Water System", Mar 2021. https://www.justice.gov/usao-ks/pr/indictment-kansas-man-indicted-tampering-public-water-system. Also reported by Security Affairs, 2 Apr 2021: https://securityaffairs.com/116238/cyber-crime/public-water-system-hack.html
7. U.S. Attorney's Office, D. Kansas, "Kansas Man Pleads Guilty to Water Facility Tampering", 2021. https://www.justice.gov/usao-ks/pr/kansas-man-pleads-guilty-water-facility-tampering
8. U.S. EPA, *Enforcement Alert: Drinking Water Systems to Address Cybersecurity Vulnerabilities*, May 2024. https://www.epa.gov/enforcement/enforcement-alert-drinking-water-systems-address-cybersecurity-vulnerabilities
9. FBI/CISA/NSA/EPA/INCD/CCCS/NCSC-UK, AA23-335A, *IRGC-Affiliated Cyber Actors Exploit PLCs in Multiple Sectors, Including U.S. Water and Wastewater Systems Facilities*, 1 Dec 2023 (rev. 18 Dec 2024). https://www.cisa.gov/news-events/cybersecurity-advisories/aa23-335a
10. CISA Alert, *Exploitation of Unitronics PLCs used in Water and Wastewater Systems*, 28 Nov 2023. https://www.cisa.gov/news-events/alerts/2023/11/28/exploitation-unitronics-plcs-used-water-and-wastewater-systems
11. CBS News Pittsburgh, "Municipal Water Authority of Aliquippa hacked by Iranian-backed cyber group", 26 Nov 2023. https://www.cbsnews.com/pittsburgh/news/municipal-water-authority-of-aliquippa-hacked-iranian-backed-cyber-group/
12. U.S. Treasury, "Treasury Sanctions Actors Responsible for Malicious Cyber Activities on Critical Infrastructure" (jy2072), 2 Feb 2024. https://home.treasury.gov/news/press-releases/jy2072
13. Claroty Team82, "From Exploits to Forensics: Unraveling the Unitronics Attack", 7 Aug 2024. https://blog.claroty.com/team82/research/from-exploits-to-forensics-unraveling-the-unitronics-attack
14. MITRE ATT&CK, Campaign C0031 *Unitronics Defacement Campaign*. https://attack.mitre.org/campaigns/C0031/
15. Claroty Team82, "Inside a New OT/IoT Cyber Weapon: IOCONTROL", 10 Dec 2024. https://claroty.com/team82/research/inside-a-new-ot-iot-cyber-weapon-iocontrol
16. CISA et al., *Defending OT Operations Against Ongoing Pro-Russia Hacktivist Activity* (fact sheet), 1 May 2024. https://www.cisa.gov/resources-tools/resources/defending-ot-operations-against-ongoing-pro-russia-hacktivist-activity. PDF: https://www.ic3.gov/CSA/2024/240501.pdf
17. FBI/CISA/NSA et al., AA25-343A, *Pro-Russia Hacktivists Conduct Opportunistic Attacks Against US and Global Critical Infrastructure*, 9 Dec 2025. https://www.cisa.gov/news-events/cybersecurity-advisories/aa25-343a
18. Dragos, *Impact of FrostyGoop ICS Malware on Connected OT Systems* (Intel Brief), July 2024. https://hub.dragos.com/hubfs/Reports/Dragos-FrostyGoop-ICS-Malware-Intel-Brief-0724_.pdf
19. Mandiant/Google Cloud, *APT44: Unearthing Sandworm*, 17 Apr 2024, pp. 13-14. Report: https://services.google.com/fh/files/misc/apt44-unearthing-sandworm.pdf. Blog: https://cloud.google.com/blog/topics/threat-intelligence/apt44-unearthing-sandworm. Also reported by CyberScoop, 17 Apr 2024: https://cyberscoop.com/sandworm-apt44-texas-water-facility/
20. KXAN (quoting City of Muleshoe statement), "Reports: Russian hackers caused Muleshoe water tank to overflow", Apr 2024. https://digital-release.kxan.com/news/texas/reports-russian-hackers-caused-muleshoe-water-tank-to-overflow/amp/
21. FBI/EPA PSA I-073026-PSA, *Malicious Cyber Actors Targeting Water and Wastewater Sector Internet-Facing Programmable Logic Controllers, Causing Operational Disruptions*, 30 Jul 2026. https://www.ic3.gov/PSA/2026/PSA260730.pdf
22. FBI/CISA/NSA/EPA/DOE/CNMF/Treasury, AA26-097A (Iranian-affiliated actors exploiting internet-facing PLCs), 7 Apr 2026, updated 22 Jul 2026. https://www.cisa.gov/news-events/cybersecurity-advisories/aa26-097a
23. U.S. DOJ, "Justice Department Announces Actions to Combat Two Russian State-Sponsored Cyber Criminal Groups", 9 Dec 2025. https://www.justice.gov/opa/pr/justice-department-announces-actions-combat-two-russian-state-sponsored-cyber-criminal
24. CISA/NSA/FBI et al., AA24-038A, *PRC State-Sponsored Actors Compromise and Maintain Persistent Access to U.S. Critical Infrastructure*, 7 Feb 2024. https://www.cisa.gov/news-events/cybersecurity-advisories/aa24-038a
25. CISA, AA20-049A, *Ransomware Impacting Pipeline Operations*, 18 Feb 2020. https://www.cisa.gov/news-events/cybersecurity-advisories/aa20-049a
26. J. Blount (Colonial Pipeline CEO), written testimony, Senate HSGAC, 8 Jun 2021. https://www.hsgac.senate.gov/imo/media/doc/Testimony-Blount-2021-06-08.pdf
27. S. Hrg. 117-429, *Threats to Critical Infrastructure: Examining the Colonial Pipeline Cyber Attack* (hearing transcript), 8 Jun 2021. https://www.govinfo.gov/content/pkg/CHRG-117shrg46569/html/CHRG-117shrg46569.htm
28. Verizon RISK Team, *Data Breach Digest: Scenarios from the Field* (2016), Scenario 8, pp. 38-41. Original URL (now redirects): http://www.verizonenterprise.com/resources/reports/rp_data-breach-digest_xg_en.pdf. Archived: https://web.archive.org/web/20160521005216/http://www.verizonenterprise.com/resources/reports/rp_data-breach-digest_xg_en.pdf
29. MITRE ATT&CK, Campaign C0020 *Maroochy Water Breach*. https://attack.mitre.org/campaigns/C0020/
30. M. Abrams & J. Weiss (MITRE), *Malicious Control System Cyber Security Attack Case Study: Maroochy Water Services, Australia*, 2008. https://www.mitre.org/sites/default/files/pdf/08_1145.pdf (read via https://web.archive.org/web/2026/https://www.mitre.org/sites/default/files/pdf/08_1145.pdf because the direct fetch returned 403)
31. MITRE ATT&CK, Campaign C0066 *2026 U.S. Water Utilities Attacks*. https://attack.mitre.org/campaigns/C0066/
   - 31a. AP via The Texas Tribune (K. Miller), "Rural Texas towns report cyberattacks that caused one water system to overflow", 19 Apr 2024. https://www.texastribune.org/2024/04/19/texas-cyberattacks-russia/
32. FOX 9 (Minneapolis), "More than 30 Minnesota water systems targeted in cyberattack" (MNIT statement), 28 Jul 2026. https://www.fox9.com/news/30-minnesota-water-systems-targeted-cyber-attack
   - 32b. Security Affairs, "Hackers Strike Minnesota Water Utilities, One Plant Briefly Offline", 29 Jul 2026. https://securityaffairs.com/196246/hacking/hackers-strike-minnesota-water-utilities-one-plant-briefly-offline.html
33. American Water Works Co., Form 8-K (Item 8.01), filed 7 Oct 2024. https://www.sec.gov/Archives/edgar/data/1410636/000119312524233300/d869346d8k.htm
34. SecurityWeek, "Kansas Water Facility Switches to Manual Operations Following Cyberattack", 24 Sep 2024. https://www.securityweek.com/kansas-water-facility-switches-to-manual-operations-following-cyberattack/. City statement as reported by WaterWorld: https://www.waterworld.com/water-utility-management/press-release/55142198/arkansas-city-water-treatment-facility-faces-cybersecurity-incident
35. BleepingComputer, "Water services giant Veolia North America hit by ransomware attack", 23 Jan 2024. https://www.bleepingcomputer.com/news/security/water-services-giant-veolia-north-america-hit-by-ransomware-attack/
36. MITRE ATT&CK, Software S1165 *FrostyGoop* / Campaign C0041. https://attack.mitre.org/software/S1165/
37. South Staffordshire PLC, "Important statement" (via Cambridge Water), 16 Aug 2022. https://www.cambridge-water.co.uk/news/important-statement
   - 37a. BleepingComputer, "Hackers attack UK water supplier but extort wrong victim", 16 Aug 2022. https://www.bleepingcomputer.com/news/security/hackers-attack-uk-water-supplier-but-extort-wrong-victim/
38. NIST SP 800-82 Rev. 3, *Guide to Operational Technology (OT) Security*, Sep 2023. https://csrc.nist.gov/pubs/sp/800/82/r3/final
39. IANA, *Service Name and Transport Protocol Port Number Registry* (mbap 502, dnp 20000, dnp-sec 19999, EtherNet-IP 2222/44818, iso-tsap 102, opcua-tcp 4840). https://www.iana.org/assignments/service-names-port-numbers/service-names-port-numbers.xhtml
40. Kaspersky ICS CERT, "Targeted attacks on Israeli water supply and wastewater treatment facilities", 29 Apr 2020. https://ics-cert.kaspersky.com/publications/israel-water-cyberattacks/
41. Insurance Journal (AP), "Israeli Cyber Chief: Major Attack on Water Systems Thwarted", 29 May 2020. https://www.insurancejournal.com/news/international/2020/05/29/570415.htm
42. Times of Israel, "Cyber attacks again hit Israel's water system, shutting agricultural pumps", 17 Jul 2020. https://www.timesofisrael.com/cyber-attacks-again-hit-israels-water-system-shutting-agricultural-pumps/
43. BleepingComputer, "Pro-Russian hackers blamed for water dam sabotage in Norway", 14 Aug 2025. https://www.bleepingcomputer.com/news/security/pro-russian-hackers-blamed-for-water-dam-sabotage-in-norway/
44. MITRE ATT&CK for ICS, technique matrix (v20). https://attack.mitre.org/techniques/ics/. See also T1694 https://attack.mitre.org/techniques/T1694/ and T1692 https://attack.mitre.org/techniques/T1692/
