#!/usr/bin/env python3
"""
pcom_client - Unitronics PCOM/TCP (ASCII, protocol 101) client.

Hydra Controls engineering utility for the Cedar Ridge WTP chemical-feed
controller (Unitronics Vision V570, ww-plc02). PCOM/TCP listens on tcp/20256
and is the ONLY path that reaches memory integers MI 3000-4095 and the PLC
RUN/STOP control -- the Modbus/TCP gateway on 502 only exposes MI/MB 0-999.

    In particular:
      * the commissioning note in MI 3000-3023 is NOT on the Modbus map,
        so `pcom_client.py <host> rw 3000 24 --text` is the only way to read it;
      * `pcom_client.py <host> stop` (PCOM CCS) is the only way to place the
        chemical-feed PLC in STOP; `run` (CCR) returns it to RUN.

Wire format (matches the V570 PCOM/TCP ASCII profile exactly):

    TCP header : <tid u16 LE><protocol=101 u8><reserved=0 u8><length u16 LE>
    body       : '/' <unit:2 hex> <CMD> <data> <checksum:2 hex upper> '\\r'
    checksum   : sum(bytes of unit..data) % 256, two upper-case hex digits

Replies arrive as  '/A' <unit:2> <CMD> <data> <checksum:2> '\\r'  with the same
checksum rule computed over everything between '/A' and the checksum.

Stdlib only.

Usage:
    pcom_client.py <host> id
    pcom_client.py <host> rw <addr> <count> [--text]   # read MI words (hex)
    pcom_client.py <host> sw <addr> <val> [<val> ...]   # write MI words
    pcom_client.py <host> rb <addr> <count>             # read MB bits
    pcom_client.py <host> sb <addr> <bit> [<bit> ...]   # write MB bits (0/1)
    pcom_client.py <host> run                           # CCR - PLC to RUN
    pcom_client.py <host> stop                          # CCS - PLC to STOP

    -p / --port   PCOM/TCP port (default 20256)
    -u / --unit   unit id, 2 hex digits (default 00)
    -t / --timeout socket timeout seconds (default 3.0)

Examples:
    pcom_client.py 10.2.50.20 id
    pcom_client.py 10.2.50.20 rw 3000 24 --text     # commissioning note
    pcom_client.py 10.2.50.20 rw 0 13               # PLANT_FLOW .. DOSE_MODE
    pcom_client.py 10.2.50.20 sw 1 300              # NAOH_DOSE_SP = 300 ppm
    pcom_client.py 10.2.50.20 sb 2 0                # clear PH_HIHI_CUTOUT_EN
    pcom_client.py 10.2.50.20 stop                  # freeze chemical feed
"""

import argparse
import socket
import struct
import sys

PCOM_ASCII = 101
DEFAULT_PORT = 20256
MAX_ADDR = 4096


class PcomError(Exception):
    CODES = {
        "01": "unknown / unsupported command",
        "02": "illegal address or count",
        "03": "malformed data",
        "04": "write rejected by controller",
    }

    def __init__(self, code):
        self.code = code
        super().__init__("PCOM error %s (%s)" % (code, self.CODES.get(code, "?")))


def checksum(payload: bytes) -> bytes:
    """sum of bytes modulo 256, two upper-case hex digits (as the V570 expects)."""
    return b"%02X" % (sum(payload) % 256)


class PcomClient:
    def __init__(self, host, port=DEFAULT_PORT, unit="00", timeout=3.0):
        self.host = host
        self.port = port
        self.unit = ("%2s" % unit).replace(" ", "0")[:2].upper().encode("ascii")
        self.timeout = timeout
        self.sock = None
        self.tid = 0

    def __enter__(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        return self

    def __exit__(self, *exc):
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def _recv(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("connection closed by %s" % self.host)
            buf += chunk
        return buf

    def transact(self, cmd, data=""):
        """Send one PCOM command (ASCII) and return (reply_cmd, reply_data)."""
        self.tid = (self.tid + 1) & 0xFFFF
        inner = self.unit + cmd.encode("ascii") + data.encode("ascii")
        body = b"/" + inner + checksum(inner) + b"\r"
        self.sock.sendall(struct.pack("<HBBH", self.tid, PCOM_ASCII, 0, len(body)) + body)

        hdr = self._recv(6)
        _tid, proto, _resv, length = struct.unpack("<HBBH", hdr)
        if proto != PCOM_ASCII:
            raise PcomError("01")
        reply = self._recv(length)
        if len(reply) < 5 or reply[:2] != b"/A" or reply[-1:] != b"\r":
            raise ValueError("malformed PCOM reply: %r" % reply)
        payload, csum = reply[2:-3], reply[-3:-1]
        if checksum(payload) != csum.upper():
            raise ValueError("bad reply checksum: %r" % reply)
        # payload = <unit:2><cmd:2><data>
        rcmd = payload[2:4].decode("ascii", "replace")
        rdata = payload[4:].decode("ascii", "replace")
        if rcmd == "ER":
            raise PcomError(rdata[:2])
        return rcmd, rdata

    # -- high level ops -----------------------------------------------------
    def id(self):
        return self.transact("ID")[1]

    def read_words(self, addr, count):
        if count < 1 or addr + count > MAX_ADDR:
            raise ValueError("addr/count out of range (0..%d)" % MAX_ADDR)
        data = self.transact("RW", "%04X%02X" % (addr, count))[1]
        return [int(data[i * 4:i * 4 + 4], 16) for i in range(count)]

    def write_words(self, addr, vals):
        if not vals or addr + len(vals) > MAX_ADDR:
            raise ValueError("addr/count out of range (0..%d)" % MAX_ADDR)
        body = "%04X%02X" % (addr, len(vals)) + "".join("%04X" % (v & 0xFFFF) for v in vals)
        self.transact("SW", body)

    def read_bits(self, addr, count):
        if count < 1 or addr + count > MAX_ADDR:
            raise ValueError("addr/count out of range (0..%d)" % MAX_ADDR)
        data = self.transact("RB", "%04X%02X" % (addr, count))[1]
        return [1 if c == "1" else 0 for c in data[:count]]

    def write_bits(self, addr, bits):
        if not bits or addr + len(bits) > MAX_ADDR:
            raise ValueError("addr/count out of range (0..%d)" % MAX_ADDR)
        body = "%04X%02X" % (addr, len(bits)) + "".join("1" if b else "0" for b in bits)
        self.transact("SB", body)

    def run(self):
        self.transact("CCR")

    def stop(self):
        self.transact("CCS")


def words_to_text(words):
    """Two ASCII chars per word, high byte first, NUL-terminated (V570 convention)."""
    raw = b"".join(struct.pack(">H", w & 0xFFFF) for w in words)
    return raw.split(b"\x00", 1)[0].decode("ascii", "replace")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Unitronics PCOM/TCP (protocol 101) client for the Cedar Ridge "
                    "chemical-feed V570. The only path to MI 3000+ and PLC RUN/STOP.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    ap.add_argument("host")
    ap.add_argument("command", choices=["id", "rw", "sw", "rb", "sb", "run", "stop"])
    ap.add_argument("args", nargs="*", help="command arguments (see examples)")
    ap.add_argument("-p", "--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("-u", "--unit", default="00", help="unit id, 2 hex digits")
    ap.add_argument("-t", "--timeout", type=float, default=3.0)
    ap.add_argument("--text", action="store_true", help="ASCII-decode rw/sw words")
    args = ap.parse_args(argv)

    def pint(s):
        return int(s, 0)

    try:
        with PcomClient(args.host, args.port, args.unit, args.timeout) as c:
            if args.command == "id":
                print(c.id())
            elif args.command == "rw":
                if len(args.args) != 2:
                    ap.error("rw needs <addr> <count>")
                addr, count = pint(args.args[0]), pint(args.args[1])
                words = c.read_words(addr, count)
                if args.text:
                    print(words_to_text(words))
                else:
                    for i, w in enumerate(words):
                        print("MI %-5d = %5d  0x%04X" % (addr + i, w, w))
            elif args.command == "sw":
                if len(args.args) < 2:
                    ap.error("sw needs <addr> <val> [<val> ...]")
                addr = pint(args.args[0])
                vals = [pint(v) for v in args.args[1:]]
                c.write_words(addr, vals)
                print("OK: wrote %d word(s) at MI %d" % (len(vals), addr))
            elif args.command == "rb":
                if len(args.args) != 2:
                    ap.error("rb needs <addr> <count>")
                addr, count = pint(args.args[0]), pint(args.args[1])
                bits = c.read_bits(addr, count)
                for i, b in enumerate(bits):
                    print("MB %-5d = %d" % (addr + i, b))
            elif args.command == "sb":
                if len(args.args) < 2:
                    ap.error("sb needs <addr> <bit> [<bit> ...]")
                addr = pint(args.args[0])
                bits = [pint(v) for v in args.args[1:]]
                c.write_bits(addr, bits)
                print("OK: wrote %d bit(s) at MB %d" % (len(bits), addr))
            elif args.command == "run":
                c.run()
                print("OK: PLC placed in RUN (CCR)")
            elif args.command == "stop":
                c.stop()
                print("OK: PLC placed in STOP (CCS)")
    except (PcomError, ValueError, OSError, ConnectionError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
