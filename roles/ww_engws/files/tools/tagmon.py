#!/usr/bin/env python3
"""
tagmon - live tag monitor for the Cedar Ridge field controllers (Modbus/TCP).

Polls a chosen site once per interval and prints its key process tags, scaled
to engineering units. Handy during commissioning / fault-finding. Ctrl-C quits.

Stdlib only (imports the sibling mbclient.py).

Usage:
    tagmon.py <host> <site> [-i interval_s] [-u unit] [-p port]
      site = intake | chemfeed | booster

Examples:
    tagmon.py 10.2.50.10 intake
    tagmon.py 10.2.50.20 chemfeed -i 2
    tagmon.py 10.2.50.30 booster
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mbclient import ModbusClient, ModbusError  # noqa: E402


def read_intake(c):
    ir = c.read_input_registers(0, 12)
    di = c.read_discrete_inputs(0, 10)
    hr = c.read_holding_registers(0, 3)
    return [
        ("WW_LEVEL", "%.2f ft" % (ir[0] / 100.0)),
        ("RIVER_INFLOW", "%.2f MGD" % (ir[1] / 100.0)),
        ("PUMP_FLOW", "%.2f MGD" % (ir[2] / 100.0)),
        ("HEADER_PRESS", "%.1f psi" % (ir[6] / 10.0)),
        ("P101/2/3 MODE", "%d/%d/%d" % (hr[0], hr[1], hr[2])),
        ("P101/2/3 RUN", "%d/%d/%d" % (di[0], di[1], di[2])),
        ("P101/2/3 FAULT", "%d/%d/%d" % (di[3], di[4], di[5])),
        ("WW_LL", str(di[9])),
    ]


def read_chemfeed(c):
    hr = c.read_holding_registers(0, 13)
    co = c.read_coils(0, 4)
    di = c.read_discrete_inputs(0, 4)
    return [
        ("PLANT_FLOW", "%.2f MGD" % (hr[0] / 100.0)),
        ("NAOH_DOSE_SP", "%d ppm" % hr[1]),
        ("NAOH_DOSE_PV", "%d ppm" % hr[2]),
        ("FINISHED_PH", "%.2f" % (hr[3] / 100.0)),
        ("CL2_RESIDUAL", "%.2f mg/L" % (hr[6] / 100.0)),
        ("PH_HI/HIHI_SP", "%.2f / %.2f" % (hr[10] / 100.0, hr[11] / 100.0)),
        ("DOSE_MODE", str(hr[12])),
        ("NAOH_EN/CUTOUT_EN", "%d / %d" % (co[0], co[2])),
        ("PH_HI/HIHI_ALM", "%d / %d" % (di[1], di[2])),
        ("PLC_RUN", str(di[3])),
    ]


def read_booster(c):
    ir = c.read_input_registers(0, 8)
    hr = c.read_holding_registers(0, 4) + c.read_holding_registers(13, 2) + c.read_holding_registers(21, 1)
    co = c.read_coils(10, 3)
    di = c.read_discrete_inputs(0, 8)
    return [
        ("SUCTION_PRESS", "%.1f psi" % (ir[0] / 10.0)),
        ("DISCH_PRESS", "%.1f psi" % (ir[1] / 10.0)),
        ("FLOW", "%d gpm" % ir[2]),
        ("FCV301_POS", "%.1f %%" % (ir[3] / 10.0)),
        ("TANK_LEVEL", "%.2f ft" % (ir[4] / 100.0)),
        ("PEAK_TRANSIENT_60S", "%.1f psi" % (ir[6] / 10.0)),
        ("FCV301_SLEW", "%.1f %%/s" % (hr[3] / 10.0)),
        ("HP_TRIP/HL/SAV_EN", "%d/%d/%d" % (co[0], co[1], co[2])),
        ("MAINT_MODE", str(hr[6])),
        ("P301/2 RUN", "%d/%d" % (di[0], di[1])),
        ("MAIN_BREAK", str(di[7])),
    ]


READERS = {"intake": read_intake, "chemfeed": read_chemfeed, "booster": read_booster}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Live Modbus tag monitor for the Cedar Ridge field controllers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    ap.add_argument("host")
    ap.add_argument("site", choices=list(READERS))
    ap.add_argument("-i", "--interval", type=float, default=2.0)
    ap.add_argument("-u", "--unit", type=int, default=1)
    ap.add_argument("-p", "--port", type=int, default=502)
    ap.add_argument("-t", "--timeout", type=float, default=2.0)
    ap.add_argument("-n", "--count", type=int, default=0,
                    help="number of polls then exit (0 = forever)")
    args = ap.parse_args(argv)

    reader = READERS[args.site]
    polls = 0
    try:
        with ModbusClient(args.host, args.port, args.unit, args.timeout) as c:
            while True:
                try:
                    rows = reader(c)
                    stamp = time.strftime("%H:%M:%S")
                    print("== %s  %s @ %s ==" % (stamp, args.site, args.host))
                    for tag, val in rows:
                        print("  %-20s %s" % (tag, val))
                    print("")
                except ModbusError as e:
                    print("modbus error: %s" % e, file=sys.stderr)
                polls += 1
                if args.count and polls >= args.count:
                    break
                time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    except (OSError, ConnectionError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
