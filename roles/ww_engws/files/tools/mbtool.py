#!/usr/bin/env python3
"""
mbtool - Modbus/TCP engineering CLI for the Cedar Ridge field controllers.

Thin command-line wrapper over the local mbclient.py library. Talks to any of
the Cedar Ridge controllers on tcp/502:
    ww-plc01  Cedar River Intake PS-1     (Modicon M340)
    ww-plc02  WTP Chemical Feed           (Unitronics V570, Modbus gateway)
    ww-rtu03  Hilltop Booster PS-3        (SCADAPack 474)

Modbus addresses are 0-based protocol addresses (HR 0 == 40001).

Stdlib only (imports the sibling mbclient.py).

Usage:
    mbtool.py <host> rc  <addr> [count]        read coils            (FC01)
    mbtool.py <host> rd  <addr> [count]        read discrete inputs  (FC02)
    mbtool.py <host> rh  <addr> [count]        read holding regs     (FC03)
    mbtool.py <host> ri  <addr> [count]        read input regs       (FC04)
    mbtool.py <host> wc  <addr> <0|1>          write single coil     (FC05)
    mbtool.py <host> wh  <addr> <val>          write single register (FC06)
    mbtool.py <host> wcs <addr> <0|1> [...]    write multiple coils  (FC15)
    mbtool.py <host> whs <addr> <val> [...]    write multiple regs   (FC16)
    mbtool.py <host> srvid                     report server id      (FC17)
    mbtool.py <host> devid [--code N] [--obj N]  read device id      (FC43/0x0E)

    -p/--port 502   -u/--unit 1   -t/--timeout 2.0
    --text          ASCII-decode register reads (rh/ri)

Examples:
    mbtool.py 10.2.50.10 devid                  # M340 identity (FC43)
    mbtool.py 10.2.50.10 devid --code 4 --obj 6 # UserApplicationName object
    mbtool.py 10.2.50.10 srvid                  # FC17 report server id
    mbtool.py 10.2.50.10 ri 0 12                # intake input registers
    mbtool.py 10.2.50.20 rh 900 24 --text       # V570 panel message
    mbtool.py 10.2.50.30 rh 20 1                # rtu03 MAINT_KEY register
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mbclient import ModbusClient, ModbusError, regs_to_text  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Modbus/TCP engineering CLI for the Cedar Ridge field controllers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    ap.add_argument("host")
    ap.add_argument("command",
                    choices=["rc", "rd", "rh", "ri", "wc", "wh", "wcs", "whs",
                             "srvid", "devid"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("-p", "--port", type=int, default=502)
    ap.add_argument("-u", "--unit", type=int, default=1)
    ap.add_argument("-t", "--timeout", type=float, default=2.0)
    ap.add_argument("--text", action="store_true", help="ASCII-decode register reads")
    ap.add_argument("--code", type=int, default=1, help="FC43 read device id code (1-4)")
    ap.add_argument("--obj", type=int, default=0, help="FC43 starting object id")
    args = ap.parse_args(argv)

    def pint(s):
        return int(s, 0)

    try:
        with ModbusClient(args.host, args.port, args.unit, args.timeout) as c:
            cmd = args.command
            if cmd in ("rc", "rd", "rh", "ri"):
                if not args.args:
                    ap.error("%s needs <addr> [count]" % cmd)
                addr = pint(args.args[0])
                qty = pint(args.args[1]) if len(args.args) > 1 else 1
                if cmd == "rc":
                    vals, label = c.read_coils(addr, qty), "COIL"
                elif cmd == "rd":
                    vals, label = c.read_discrete_inputs(addr, qty), "DI"
                elif cmd == "rh":
                    vals, label = c.read_holding_registers(addr, qty), "HR"
                else:
                    vals, label = c.read_input_registers(addr, qty), "IR"
                if args.text and cmd in ("rh", "ri"):
                    print(regs_to_text(vals))
                elif label in ("COIL", "DI"):
                    for i, v in enumerate(vals):
                        print("%-4s %-5d = %d" % (label, addr + i, v))
                else:
                    for i, v in enumerate(vals):
                        print("%-4s %-5d = %6d  0x%04X" % (label, addr + i, v, v))
            elif cmd == "wc":
                if len(args.args) != 2:
                    ap.error("wc needs <addr> <0|1>")
                c.write_coil(pint(args.args[0]), pint(args.args[1]))
                print("OK: coil %s <- %s" % (args.args[0], args.args[1]))
            elif cmd == "wh":
                if len(args.args) != 2:
                    ap.error("wh needs <addr> <val>")
                c.write_register(pint(args.args[0]), pint(args.args[1]))
                print("OK: HR %s <- %s" % (args.args[0], args.args[1]))
            elif cmd == "wcs":
                if len(args.args) < 2:
                    ap.error("wcs needs <addr> <0|1> [...]")
                addr = pint(args.args[0])
                c.write_coils(addr, [pint(v) for v in args.args[1:]])
                print("OK: wrote %d coils at %d" % (len(args.args) - 1, addr))
            elif cmd == "whs":
                if len(args.args) < 2:
                    ap.error("whs needs <addr> <val> [...]")
                addr = pint(args.args[0])
                c.write_registers(addr, [pint(v) for v in args.args[1:]])
                print("OK: wrote %d registers at %d" % (len(args.args) - 1, addr))
            elif cmd == "srvid":
                data = c.report_server_id()
                # FC17: byte0 = slave id, byte1 = run indicator (0xFF run / 0x00 stop),
                # remaining bytes = ASCII server id string.
                if len(data) >= 2:
                    run = "RUN" if data[1] == 0xFF else "STOP"
                    text = data[2:].decode("ascii", "replace")
                    print("%s  [%s]" % (text, run))
                else:
                    print(data.decode("ascii", "replace"))
            elif cmd == "devid":
                objs = c.read_device_identification(args.code, args.obj)
                names = {0: "VendorName", 1: "ProductCode", 2: "MajorMinorRevision",
                         3: "VendorUrl", 4: "ProductName", 5: "ModelName",
                         6: "UserApplicationName"}
                for oid in sorted(objs):
                    print("  [0x%02X] %-20s %s" % (oid, names.get(oid, "obj"), objs[oid]))
    except (ModbusError, ValueError, OSError, ConnectionError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
