#!/usr/bin/env python3
"""
wwplc - field controller runtime for the Cedar Ridge Regional Transmission System.

One process emulates one controller:
  * intake   - Cedar River Intake PS-1           (Modicon M340 profile)
  * chemfeed - Cedar Ridge WTP chemical feed     (Unitronics Vision V570 profile)
  * booster  - Hilltop Booster PS-3 + Summit Tank (SCADAPack 474 profile)

Protocols (stdlib only, no third-party deps):
  * Modbus/TCP server: FC 1,2,3,4,5,6,15,16,17 and 43/14 (Read Device Identification)
  * PCOM/TCP server (ASCII, protocol 101) for the Unitronics profile:
      ID, RW/SW (memory integers), RB/SB (memory bits), CCR (run), CCS (stop)

The process model runs a fixed-period scan (default 100 ms) like a PLC task.
"""

import argparse
import asyncio
import collections
import json
import logging
import math
import random
import struct
import time

log = logging.getLogger("wwplc")

# Modbus exception codes
ILLEGAL_FUNCTION = 0x01
ILLEGAL_ADDRESS = 0x02
ILLEGAL_VALUE = 0x03
DEVICE_FAILURE = 0x04

MEM_SIZE = 10000


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def u16(v):
    return int(clamp(round(v), 0, 0xFFFF))


def put_text(regs, start, count, text):
    """ASCII into registers, two chars per register, high byte first, NUL padded."""
    raw = text.encode("ascii", "replace")[: count * 2].ljust(count * 2, b"\x00")
    for i in range(count):
        regs[start + i] = (raw[2 * i] << 8) | raw[2 * i + 1]


def get_text(regs, start, count):
    raw = b"".join(struct.pack(">H", regs[start + i] & 0xFFFF) for i in range(count))
    return raw.split(b"\x00", 1)[0].decode("ascii", "replace")


class Memory:
    def __init__(self):
        self.co = [0] * MEM_SIZE  # coils / MB
        self.di = [0] * MEM_SIZE  # discrete inputs
        self.ir = [0] * MEM_SIZE  # input registers
        self.hr = [0] * MEM_SIZE  # holding registers / MI


# ---------------------------------------------------------------------------
#  Site models
# ---------------------------------------------------------------------------
class Site:
    profile = "generic"
    # highest address + 1 reachable over Modbus per table
    modbus_limits = {"co": MEM_SIZE, "di": MEM_SIZE, "ir": MEM_SIZE, "hr": MEM_SIZE}
    device_id = {}
    server_id = "WWP CONTROLLER"

    def __init__(self, cfg):
        self.cfg = cfg
        self.flags = cfg.get("flags", {})
        self.hold = float(cfg.get("event_hold_s", 600))
        self.m = Memory()
        self.t0 = time.monotonic()
        self.running = True  # PLC RUN/STOP state
        self.events = {}  # name -> restore deadline (monotonic)
        self.load_defaults()

    # -- helpers ------------------------------------------------------------
    def now(self):
        return time.monotonic() - self.t0

    def fire(self, name, start, flag_key, message):
        """Latch an impact event and publish its flag into PLC memory."""
        if name in self.events:
            return
        self.events[name] = time.monotonic() + self.hold
        text = self.flags.get(flag_key, "WTR{flag_not_configured}")
        put_text(self.m.hr, start, 24, text)
        log.warning("EVENT %s: %s (latched %ds)", name, message, self.hold)

    def due_restores(self):
        now = time.monotonic()
        due = [n for n, until in self.events.items() if now >= until]
        for n in due:
            del self.events[n]
        return due

    # -- hooks --------------------------------------------------------------
    def load_defaults(self):
        pass

    def on_write(self, table, addr, values):
        """Return None to accept or a Modbus exception code to reject."""
        return None

    def scan(self, dt):
        pass


class IntakeSite(Site):
    """Cedar River Intake PS-1: wet well, slide gate, three vertical turbine pumps."""

    profile = "Modicon M340"
    modbus_limits = {"co": 64, "di": 64, "ir": 64, "hr": 10000}
    server_id = "CEDAR RIVER INTAKE PS-1 M340"
    PUMP_MGD = 3.0
    WELL_FT_PER_MGD_S = 0.04
    SUBMERGENCE_FT = 2.0

    def __init__(self, cfg):
        self.device_id = {
            0x00: "Schneider Electric",
            0x01: "BMX P34 2020",
            0x02: "v3.40",
            0x03: "www.se.com",
            0x04: "Modicon M340",
            0x05: "BMX P34 2020",
            0x06: "CEDAR_INTAKE_PS1 " + cfg.get("flags", {}).get("plc01_devid", ""),
        }
        super().__init__(cfg)

    def load_defaults(self):
        hr, co = self.m.hr, self.m.co
        hr[0], hr[1], hr[2] = 2, 2, 0
        hr[10], hr[11], hr[12], hr[13], hr[14], hr[15] = 1200, 1400, 600, 1000, 300, 1000
        co[0] = co[1] = co[2] = 0
        co[10], co[11] = 1, 0
        put_text(hr, 9000, 24, "")
        self.level = 12.0
        self.gate = 100.0
        self.lead_run = True
        self.lag_run = False
        self.ll_trip = False
        self.dry = [0.0, 0.0, 0.0]
        self.damaged = [False, False, False]

    def scan(self, dt):
        m, t = self.m, self.now()
        hr, co, di, ir = m.hr, m.co, m.di, m.ir
        if "drypump" in self.due_restores():
            log.info("intake: pump replaced, station restored to engineered defaults")
            self.load_defaults()

        river = 5.0 + 0.25 * math.sin(2 * math.pi * t / 900.0) + random.uniform(-0.03, 0.03)
        self.gate += clamp(hr[15] / 10.0 - self.gate, -5.0 * dt, 5.0 * dt)
        self.gate = clamp(self.gate, 0.0, 100.0)
        inflow = river * self.gate / 100.0

        if co[11]:
            self.ll_trip = False
            co[11] = 0
        if co[10] and self.level <= hr[14] / 100.0:
            self.ll_trip = True
        if self.ll_trip and (not co[10] or self.level > hr[14] / 100.0 + 1.0):
            self.ll_trip = False

        # automatic lead / lag on wet-well level
        if self.level >= hr[10] / 100.0:
            self.lead_run = True
        elif self.level <= hr[12] / 100.0:
            self.lead_run = False
        if self.level >= hr[11] / 100.0:
            self.lag_run = True
        elif self.level <= hr[13] / 100.0:
            self.lag_run = False

        auto = [i for i in range(3) if hr[i] == 2 and not self.damaged[i]]
        run = [False, False, False]
        for i in range(3):
            if self.damaged[i] or not self.running:
                continue
            if hr[i] == 1:
                run[i] = bool(co[i])
            elif hr[i] == 2:
                if auto and auto[0] == i:
                    run[i] = self.lead_run
                elif len(auto) > 1 and auto[1] == i:
                    run[i] = self.lag_run
            if self.ll_trip:
                run[i] = False

        if self.level > self.SUBMERGENCE_FT:
            eff = 1.0
        else:
            eff = clamp((self.level - 0.5) / (self.SUBMERGENCE_FT - 0.5), 0.0, 1.0)
        outflow = sum(self.PUMP_MGD * eff for r in run if r)
        self.level = clamp(self.level + (inflow - outflow) * self.WELL_FT_PER_MGD_S * dt, 0.0, 20.0)

        for i in range(3):
            cavitating = run[i] and self.level < self.SUBMERGENCE_FT
            if cavitating:
                self.dry[i] += dt
                if self.dry[i] >= 10.0 and not self.damaged[i]:
                    self.damaged[i] = True
                    self.fire("drypump", 9000, "impact_drypump",
                              "P-10%d ran dry for %.0fs - bowl assembly destroyed" % (i + 1, self.dry[i]))
            di[i] = int(run[i])
            di[3 + i] = int(self.damaged[i])
            if run[i]:
                amps = 86.0 * (0.55 + 0.45 * eff) + (random.uniform(-9, 9) if cavitating else random.uniform(-0.6, 0.6))
                vib = random.uniform(11.0, 16.5) if cavitating else 2.4 + random.uniform(-0.2, 0.2)
            else:
                amps, vib = 0.0, 0.3 + random.uniform(0, 0.1)
            ir[3 + i] = u16(amps * 10)
            ir[8 + i] = u16(vib * 10)

        n = sum(run)
        di[8] = int(self.level >= 17.0)
        di[9] = int(self.level <= hr[14] / 100.0)
        ir[0] = u16(self.level * 100)
        ir[1] = u16(river * 100)
        ir[2] = u16(outflow * 100)
        ir[6] = u16((51.0 + 2.5 * n + random.uniform(-0.3, 0.3)) * 10 if n else 0)
        ir[7] = u16((4.2 + 1.4 * math.sin(2 * math.pi * t / 1300.0)) * 100)
        ir[11] = u16(self.gate * 10)
        if self.running:
            hr[100] = (hr[100] + 1) & 0xFFFF


class ChemFeedSite(Site):
    """Cedar Ridge WTP chemical feed: flow-paced NaOH (pH) and chlorine."""

    profile = "Unitronics Vision V570"
    modbus_limits = {"co": 1000, "di": 16, "ir": 0, "hr": 1000}
    server_id = "CEDAR RIDGE WTP CHEMFEED V570"
    PCOM_MODEL = "V570-57-T20B"
    DEFAULT_MSG = "CEDAR RIDGE WTP - CHEMICAL FEED"
    PH_TAU_S = 12.0
    DOSE_RAMP_PPM_S = 400.0

    def load_defaults(self):
        hr, co = self.m.hr, self.m.co
        hr[1], hr[5], hr[10], hr[11], hr[12] = 100, 150, 850, 950, 2
        co[0], co[1], co[2], co[3] = 1, 1, 1, 0
        put_text(hr, 900, 24, self.DEFAULT_MSG)
        put_text(hr, 930, 24, "")
        put_text(hr, 960, 24, "")
        put_text(hr, 3000, 24, "HYDRA CTRL 2017-05 " + self.flags.get("plc02_pcom", ""))
        self.ph = getattr(self, "ph", 8.0)
        self.dose = getattr(self, "dose", 100.0)
        self.cl2 = 1.20
        self.tank = 78.0
        self.cutout = False
        self.high_s = 0.0
        self.running = True

    def restore_dosing(self):
        hr, co = self.m.hr, self.m.co
        hr[1], hr[10], hr[11], hr[12] = 100, 850, 950, 2
        co[0], co[2] = 1, 1
        self.cutout = False
        put_text(hr, 930, 24, "")

    def scan(self, dt):
        m, t = self.m, self.now()
        hr, co, di = m.hr, m.co, m.di
        for name in self.due_restores():
            if name == "naoh":
                log.info("chemfeed: operators restored NaOH dosing to 100 ppm")
                self.restore_dosing()
            elif name == "deface":
                log.info("chemfeed: panel message restored")
                put_text(hr, 900, 24, self.DEFAULT_MSG)
                put_text(hr, 960, 24, "")
            elif name == "stopped":
                log.info("chemfeed: PLC returned to RUN by technician")
                self.running = True

        flow = 5.0 + 0.2 * math.sin(2 * math.pi * t / 700.0)
        raw_ph = 6.80 + 0.05 * math.sin(2 * math.pi * t / 1100.0)

        if self.running:
            if co[3]:
                self.cutout = False
                co[3] = 0
            if co[2] and self.ph >= hr[11] / 100.0:
                self.cutout = True
            if self.cutout and (not co[2] or self.ph < hr[10] / 100.0):
                self.cutout = False
            pump_on = bool(co[0]) and hr[12] in (1, 2) and not self.cutout
            target = float(hr[1]) if pump_on else 0.0
            cl2_on = bool(co[1])
        else:
            pump_on, target, cl2_on = False, 0.0, False

        self.dose += clamp(target - self.dose, -self.DOSE_RAMP_PPM_S * dt, self.DOSE_RAMP_PPM_S * dt)
        ph_target = raw_ph + 2.2 * math.log10(1.0 + self.dose / 40.0)
        self.ph += (ph_target - self.ph) * clamp(dt / self.PH_TAU_S, 0.0, 1.0)
        cl2_target = 0.8 * hr[5] / 100.0 if cl2_on else 0.0
        self.cl2 += (cl2_target - self.cl2) * clamp(dt / 20.0, 0.0, 1.0)
        self.tank -= self.dose * flow * 2.0e-7 * dt
        if self.tank < 20.0:
            self.tank = 85.0  # bulk delivery

        if self.ph >= 11.0:
            self.high_s += dt
            if self.high_s >= 5.0:
                self.fire("naoh", 930, "impact_naoh",
                          "finished water pH %.2f - caustic overdose entering distribution" % self.ph)
        else:
            self.high_s = 0.0

        if get_text(hr, 900, 24) != self.DEFAULT_MSG:
            self.fire("deface", 960, "impact_deface",
                      "operator panel message replaced: %r" % get_text(hr, 900, 24))

        di[3] = int(self.running)
        if not self.running:
            di[0] = 0
            return  # memory frozen while in STOP
        di[0] = int(pump_on and self.dose > 1.0)
        di[1] = int(self.ph >= hr[10] / 100.0)
        di[2] = int(self.ph >= hr[11] / 100.0)
        hr[0] = u16(flow * 100)
        hr[2] = u16(self.dose)
        hr[3] = u16(self.ph * 100)
        hr[4] = u16(min(100.0, self.dose / 150.0 * 100.0) * 10)
        hr[6] = u16(self.cl2 * 100)
        hr[7] = u16((14.0 + 0.6 * math.sin(2 * math.pi * t / 800.0)) * 100)
        hr[8] = u16(raw_ph * 100)
        hr[9] = u16(self.tank * 10)
        hr[20] = (hr[20] + 1) & 0xFFFF

    def pcom_stop(self):
        if self.running:
            self.running = False
            self.events["stopped"] = time.monotonic() + self.hold
            log.warning("chemfeed: PLC placed in STOP via PCOM")

    def pcom_run(self):
        self.running = True
        self.events.pop("stopped", None)
        log.info("chemfeed: PLC placed in RUN via PCOM")


class BoosterSite(Site):
    """Hilltop Booster PS-3, FCV-301, SAV-301 and Summit elevated tank."""

    profile = "SCADAPack 474"
    modbus_limits = {"co": 64, "di": 64, "ir": 64, "hr": 10000}
    server_id = "HILLTOP BOOSTER PS-3 SCADAPACK 474"

    # protective settings restored every scan outside maintenance mode
    PROTECTED_HR = {3: 20, 13: 3500, 14: 1400}
    PROTECTED_CO = {10: 1, 11: 1, 12: 1}

    # hydraulics
    H0_PSI = 110.0          # pump shutoff head
    QMAX_GPM = 3000.0       # runout per pump
    K_SYS = 0.703e-5        # system resistance, psi/gpm^2 at full valve opening
    PIPE_AREA_M2 = 0.1297   # 16-inch ID
    WAVE_SPEED = 1100.0     # m/s, ductile iron
    CRIT_PERIOD_S = 7.3     # 2L/a, L = 4,023 m
    SAV_CLAMP_PSI = 165.0
    BURST_PSI = 240.0
    TANK_GAL_PER_FT = 12500.0  # 0.5 MG / 40 ft; 1 lab second = 1 process minute

    def __init__(self, cfg):
        self.maint_key = int(cfg.get("maint_key", 8042))
        super().__init__(cfg)

    def load_defaults(self):
        hr, co = self.m.hr, self.m.co
        hr[0], hr[1], hr[2] = 2, 2, 1000
        hr[10], hr[11], hr[12] = 2200, 3300, 1900
        for a, v in self.PROTECTED_HR.items():
            hr[a] = v
        for a, v in self.PROTECTED_CO.items():
            co[a] = v
        co[0] = co[1] = co[13] = 0
        put_text(hr, 9000, 24, "")
        put_text(hr, 9032, 24, "")
        self.valve = 1.0
        self.tank = getattr(self, "tank", 28.0)
        self.lead_run = False
        self.lag_run = False
        self.hp_trip_until = 0.0
        self.sav_open_until = 0.0
        self.broken = False
        self.overflow_s = 0.0
        self.surge = collections.deque()
        self.peaks = collections.deque()
        self.maint_until = 0.0
        self.bad_keys = collections.deque()
        self.lockout_until = 0.0

    def on_write(self, table, addr, values):
        if table == "hr" and addr <= 20 < addr + len(values):
            key = values[20 - addr]
            now = time.monotonic()
            if now < self.lockout_until:
                log.warning("booster: maintenance key attempt during lockout")
            elif key == self.maint_key:
                self.maint_until = now + 900
                self.bad_keys.clear()
                log.warning("booster: MAINTENANCE MODE enabled via HR 20")
            else:
                self.bad_keys.append(now)
                while self.bad_keys and now - self.bad_keys[0] > 60:
                    self.bad_keys.popleft()
                if len(self.bad_keys) >= 5:
                    self.lockout_until = now + 120
                    self.bad_keys.clear()
                    log.warning("booster: maintenance key lockout (5 failures/60s)")
        return None

    def flow(self, n, a, p_static, p_suction):
        if n == 0 or a < 0.005:
            return 0.0
        head = p_suction + self.H0_PSI - p_static
        if head <= 0:
            return 0.0
        denom = self.H0_PSI / (n * self.QMAX_GPM) ** 2 + self.K_SYS / (a * a)
        return math.sqrt(head / denom)

    def velocity(self, q_gpm):
        return q_gpm * 6.309e-5 / self.PIPE_AREA_M2

    def scan(self, dt):
        m, now_s = self.m, self.now()
        hr, co, di, ir = m.hr, m.co, m.di, m.ir
        mono = time.monotonic()
        for name in self.due_restores():
            if name == "mainbreak":
                log.info("booster: Miller Creek crossing repaired, station restored")
                self.load_defaults()
                self.tank = max(self.tank, 20.0)
            elif name == "overflow":
                log.info("booster: overflow event cleared")
                put_text(hr, 9000, 24, "")

        maint = mono < self.maint_until
        if not maint:
            for a, v in self.PROTECTED_HR.items():
                hr[a] = v
            for a, v in self.PROTECTED_CO.items():
                co[a] = v
        hr[20] = 0
        hr[21] = int(maint)
        hr[22] = u16(self.maint_until - mono) if maint else 0

        if co[13]:
            if mono >= self.hp_trip_until - 25:
                self.hp_trip_until = 0.0
            co[13] = 0

        # automatic lead / lag on tank level
        if self.tank <= hr[10] / 100.0:
            self.lead_run = True
        elif self.tank >= hr[11] / 100.0:
            self.lead_run = False
        if self.tank <= hr[12] / 100.0:
            self.lag_run = True
        elif self.tank >= hr[11] / 100.0:
            self.lag_run = False

        auto = [i for i in range(2) if hr[i] == 2]
        run = [False, False]
        for i in range(2):
            if hr[i] == 1:
                run[i] = bool(co[i])
            elif hr[i] == 2:
                run[i] = self.lead_run if auto[0] == i else self.lag_run
        if co[11] and self.tank >= hr[13] / 100.0:
            run = [False, False]
        if mono < self.hp_trip_until:
            run = [False, False]
        n = sum(run)

        slew = hr[3] / 1000.0  # fraction per second
        a_prev = self.valve
        self.valve += clamp(clamp(hr[2] / 1000.0, 0.0, 1.0) - self.valve, -slew * dt, slew * dt)

        p_suction = 45.0 + 0.8 * math.sin(2 * math.pi * now_s / 240.0)
        p_static = 65.0 + 0.433 * self.tank
        demand = 1800.0 + 400.0 * math.sin(2 * math.pi * now_s / 600.0)

        if self.broken:
            q = n * 2600.0
            p_dis = 18.0 + 4.0 * n
            p_eff = p_dis
            inflow = 0.0
        else:
            q = self.flow(n, self.valve, p_static, p_suction)
            if n:
                p_dis = p_suction + self.H0_PSI * (1.0 - (q / (n * self.QMAX_GPM)) ** 2)
                q_prev = self.flow(n, a_prev, p_static, p_suction)
                dv = self.velocity(q_prev) - self.velocity(q)
                if dv > 0:
                    self.surge.append((now_s, dv))
            else:
                p_dis = p_static
            inflow = q

            while self.surge and now_s - self.surge[0][0] > self.CRIT_PERIOD_S:
                self.surge.popleft()
            dv_window = sum(d for _, d in self.surge)
            surge_psi = 1000.0 * self.WAVE_SPEED * dv_window / 6895.0
            p_eff = p_dis + surge_psi
            if co[12] and p_eff > self.SAV_CLAMP_PSI:
                p_eff = self.SAV_CLAMP_PSI
                self.sav_open_until = mono + 3.0

            if co[10] and p_eff >= hr[14] / 10.0 and n:
                self.hp_trip_until = mono + 30.0
                log.info("booster: high discharge pressure trip at %.0f psi", p_eff)

            if p_eff >= self.BURST_PSI:
                self.broken = True
                self.fire("mainbreak", 9032, "impact_mainbreak",
                          "transient %.0f psi ruptured the Miller Creek crossing" % p_eff)

        self.tank = clamp(self.tank + (inflow - demand) * dt / self.TANK_GAL_PER_FT, 0.0, 38.2)
        if self.tank >= 38.0:
            self.overflow_s += dt
            if self.overflow_s >= 5.0:
                self.fire("overflow", 9000, "impact_overflow",
                          "Summit Tank overflowing at %.1f ft" % self.tank)
        else:
            self.overflow_s = 0.0

        self.peaks.append((now_s, p_eff))
        while self.peaks and now_s - self.peaks[0][0] > 60:
            self.peaks.popleft()

        for i in range(2):
            di[i] = int(run[i])
        di[2] = int(mono < self.hp_trip_until)
        di[3] = int(self.tank >= 36.0)
        di[4] = int(self.tank >= 38.0)
        di[5] = int(mono < self.sav_open_until)
        di[6] = int(maint)
        di[7] = int(self.broken)
        ir[0] = u16(p_suction * 10)
        ir[1] = u16(p_eff * 10)
        ir[2] = u16(q)
        ir[3] = u16(self.valve * 1000)
        ir[4] = u16(self.tank * 100)
        ir[5] = u16(demand)
        ir[6] = u16(max(p for _, p in self.peaks) * 10)
        ir[7] = u16(self.lockout_until - mono) if mono < self.lockout_until else 0
        hr[100] = (hr[100] + 1) & 0xFFFF


SITES = {"intake": IntakeSite, "chemfeed": ChemFeedSite, "booster": BoosterSite}


# ---------------------------------------------------------------------------
#  Modbus/TCP server
# ---------------------------------------------------------------------------
class ModbusServer:
    def __init__(self, site, unit_ids):
        self.site = site
        self.unit_ids = set(unit_ids)

    async def handle(self, reader, writer):
        peer = writer.get_extra_info("peername")
        log.info("modbus: connection from %s", peer)
        try:
            while True:
                hdr = await reader.readexactly(7)
                tid, pid, length, uid = struct.unpack(">HHHB", hdr)
                if pid != 0 or length < 2 or length > 260:
                    break
                pdu = await reader.readexactly(length - 1)
                if uid not in self.unit_ids:
                    resp = bytes([pdu[0] | 0x80, 0x0B])  # gateway target failed to respond
                else:
                    resp = self.process(pdu, peer)
                writer.write(struct.pack(">HHHB", tid, 0, len(resp) + 1, uid) + resp)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    def check(self, table, addr, qty):
        return addr + qty <= self.site.modbus_limits[table]

    def process(self, pdu, peer):
        fc = pdu[0]
        m = self.site.m

        def exc(code):
            return bytes([fc | 0x80, code])

        try:
            if fc in (1, 2):
                addr, qty = struct.unpack(">HH", pdu[1:5])
                table = "co" if fc == 1 else "di"
                if not 1 <= qty <= 2000:
                    return exc(ILLEGAL_VALUE)
                if not self.check(table, addr, qty):
                    return exc(ILLEGAL_ADDRESS)
                bits = getattr(m, table)[addr:addr + qty]
                out = bytearray((qty + 7) // 8)
                for i, b in enumerate(bits):
                    if b:
                        out[i // 8] |= 1 << (i % 8)
                return bytes([fc, len(out)]) + bytes(out)
            if fc in (3, 4):
                addr, qty = struct.unpack(">HH", pdu[1:5])
                table = "hr" if fc == 3 else "ir"
                if not 1 <= qty <= 125:
                    return exc(ILLEGAL_VALUE)
                if not self.check(table, addr, qty):
                    return exc(ILLEGAL_ADDRESS)
                regs = getattr(m, table)[addr:addr + qty]
                return bytes([fc, qty * 2]) + struct.pack(">%dH" % qty, *regs)
            if fc == 5:
                addr, val = struct.unpack(">HH", pdu[1:5])
                if val not in (0x0000, 0xFF00):
                    return exc(ILLEGAL_VALUE)
                if not self.check("co", addr, 1):
                    return exc(ILLEGAL_ADDRESS)
                rc = self.site.on_write("co", addr, [1 if val else 0])
                if rc:
                    return exc(rc)
                m.co[addr] = 1 if val else 0
                log.info("modbus: %s FC05 coil %d <- %d", peer[0], addr, m.co[addr])
                return pdu[:5]
            if fc == 6:
                addr, val = struct.unpack(">HH", pdu[1:5])
                if not self.check("hr", addr, 1):
                    return exc(ILLEGAL_ADDRESS)
                rc = self.site.on_write("hr", addr, [val])
                if rc:
                    return exc(rc)
                m.hr[addr] = val
                log.info("modbus: %s FC06 HR %d <- %d", peer[0], addr, val)
                return pdu[:5]
            if fc == 15:
                addr, qty, nbytes = struct.unpack(">HHB", pdu[1:6])
                if not 1 <= qty <= 1968 or nbytes != (qty + 7) // 8 or len(pdu) < 6 + nbytes:
                    return exc(ILLEGAL_VALUE)
                if not self.check("co", addr, qty):
                    return exc(ILLEGAL_ADDRESS)
                data = pdu[6:6 + nbytes]
                vals = [(data[i // 8] >> (i % 8)) & 1 for i in range(qty)]
                rc = self.site.on_write("co", addr, vals)
                if rc:
                    return exc(rc)
                m.co[addr:addr + qty] = vals
                log.info("modbus: %s FC15 coils %d..%d <- %s", peer[0], addr, addr + qty - 1, vals)
                return bytes([fc]) + struct.pack(">HH", addr, qty)
            if fc == 16:
                addr, qty, nbytes = struct.unpack(">HHB", pdu[1:6])
                if not 1 <= qty <= 123 or nbytes != qty * 2 or len(pdu) < 6 + nbytes:
                    return exc(ILLEGAL_VALUE)
                if not self.check("hr", addr, qty):
                    return exc(ILLEGAL_ADDRESS)
                vals = list(struct.unpack(">%dH" % qty, pdu[6:6 + nbytes]))
                rc = self.site.on_write("hr", addr, vals)
                if rc:
                    return exc(rc)
                m.hr[addr:addr + qty] = vals
                log.info("modbus: %s FC16 HR %d..%d <- %s", peer[0], addr, addr + qty - 1, vals)
                return bytes([fc]) + struct.pack(">HH", addr, qty)
            if fc == 17:
                data = bytes([0x01, 0xFF if self.site.running else 0x00]) + self.site.server_id.encode()
                return bytes([fc, len(data)]) + data
            if fc == 43:
                return self.read_device_id(pdu)
        except struct.error:
            return exc(ILLEGAL_VALUE)
        return exc(ILLEGAL_FUNCTION)

    def read_device_id(self, pdu):
        fc = pdu[0]
        if len(pdu) < 4 or pdu[1] != 0x0E:
            return bytes([fc | 0x80, ILLEGAL_FUNCTION])
        code, obj = pdu[2], pdu[3]
        ids = self.site.device_id
        if not ids:
            return bytes([fc | 0x80, ILLEGAL_FUNCTION])
        if code == 4:
            if obj not in ids:
                return bytes([fc | 0x80, ILLEGAL_ADDRESS])
            objs = [obj]
        elif code in (1, 2, 3):
            last = {1: 0x02, 2: 0x7F, 3: 0xFF}[code]
            first = obj if obj in ids and obj <= last else 0
            objs = [o for o in sorted(ids) if first <= o <= last]
        else:
            return bytes([fc | 0x80, ILLEGAL_VALUE])
        body = b""
        for o in objs:
            v = ids[o].encode()[:240]
            body += bytes([o, len(v)]) + v
        # conformity level 0x82: regular identification, individual access supported
        return bytes([fc, 0x0E, code, 0x82, 0x00, 0x00, len(objs)]) + body


# ---------------------------------------------------------------------------
#  PCOM/TCP server (ASCII) - Unitronics profile
# ---------------------------------------------------------------------------
PCOM_ASCII = 101


def pcom_checksum(payload: bytes) -> bytes:
    return b"%02X" % (sum(payload) % 256)


class PcomServer:
    MAX_ADDR = 4096

    def __init__(self, site):
        self.site = site

    async def handle(self, reader, writer):
        peer = writer.get_extra_info("peername")
        log.info("pcom: connection from %s", peer)
        try:
            while True:
                hdr = await reader.readexactly(6)
                tid, proto, _reserved, length = struct.unpack("<HBBH", hdr)
                if proto != PCOM_ASCII or length == 0 or length > 1024:
                    log.info("pcom: unsupported frame (protocol %d) from %s", proto, peer)
                    break
                body = await reader.readexactly(length)
                reply = self.process(body, peer)
                if reply is None:
                    continue
                writer.write(struct.pack("<HBBH", tid, PCOM_ASCII, 0, len(reply)) + reply)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    def process(self, body, peer):
        # /<unit:2><command><data><checksum:2>\r
        if len(body) < 6 or body[:1] != b"/" or body[-1:] != b"\r":
            return None
        payload, csum = body[1:-3], body[-3:-1]
        if pcom_checksum(payload) != csum.upper():
            log.info("pcom: bad checksum from %s", peer)
            return None
        unit, rest = payload[:2], payload[2:].decode("ascii", "replace")
        cmd, data = self.dispatch(rest, peer)
        out = unit + cmd.encode() + data.encode()
        return b"/A" + out + pcom_checksum(out) + b"\r"

    def dispatch(self, rest, peer):
        m, site = self.site.m, self.site
        try:
            if rest.startswith("ID"):
                return "ID", "%s OS 4.12 (03.028.00) %s" % (site.PCOM_MODEL, "RUN" if site.running else "STOP")
            if rest.startswith("CCR"):
                site.pcom_run()
                return "CC", ""
            if rest.startswith("CCS"):
                site.pcom_stop()
                return "CC", ""
            op, args = rest[:2], rest[2:]
            if op in ("RW", "RB"):
                addr, count = int(args[0:4], 16), int(args[4:6], 16)
                if count == 0 or addr + count > self.MAX_ADDR:
                    return "ER", "02"
                if op == "RW":
                    return op, "".join("%04X" % v for v in m.hr[addr:addr + count])
                return op, "".join(str(b & 1) for b in m.co[addr:addr + count])
            if op in ("SW", "SB"):
                addr, count = int(args[0:4], 16), int(args[4:6], 16)
                if count == 0 or addr + count > self.MAX_ADDR:
                    return "ER", "02"
                vals_s = args[6:]
                if op == "SW":
                    if len(vals_s) < count * 4:
                        return "ER", "03"
                    vals = [int(vals_s[i * 4:i * 4 + 4], 16) for i in range(count)]
                    if site.on_write("hr", addr, vals):
                        return "ER", "04"
                    m.hr[addr:addr + count] = vals
                    log.info("pcom: %s SW MI %d..%d <- %s", peer[0], addr, addr + count - 1, vals)
                else:
                    if len(vals_s) < count:
                        return "ER", "03"
                    vals = [1 if c == "1" else 0 for c in vals_s[:count]]
                    if site.on_write("co", addr, vals):
                        return "ER", "04"
                    m.co[addr:addr + count] = vals
                    log.info("pcom: %s SB MB %d..%d <- %s", peer[0], addr, addr + count - 1, vals)
                return op, ""
        except ValueError:
            return "ER", "03"
        return "ER", "01"


# ---------------------------------------------------------------------------
async def scan_loop(site, period):
    last = time.monotonic()
    while True:
        await asyncio.sleep(period)
        now = time.monotonic()
        try:
            site.scan(min(now - last, 1.0))
        except Exception:  # a PLC task fault must not kill the runtime
            log.exception("scan fault")
        last = now


async def main_async(cfg):
    site = SITES[cfg["site"]](cfg)
    servers = []
    mb = ModbusServer(site, cfg.get("unit_ids", [0, 1, 255]))
    servers.append(await asyncio.start_server(mb.handle, cfg.get("bind", "0.0.0.0"), cfg.get("modbus_port", 502)))
    log.info("%s (%s) Modbus/TCP listening on %s", cfg["site"], site.profile, cfg.get("modbus_port", 502))
    if cfg.get("pcom_port") and isinstance(site, ChemFeedSite):
        pc = PcomServer(site)
        servers.append(await asyncio.start_server(pc.handle, cfg.get("bind", "0.0.0.0"), cfg["pcom_port"]))
        log.info("PCOM/TCP listening on %s", cfg["pcom_port"])
    await scan_loop(site, cfg.get("scan_ms", 100) / 1000.0)


def main():
    ap = argparse.ArgumentParser(description="WWP field controller runtime")
    ap.add_argument("-c", "--config", default="/etc/wwplc/controller.json")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    with open(args.config) as fh:
        cfg = json.load(fh)
    asyncio.run(main_async(cfg))


if __name__ == "__main__":
    main()
