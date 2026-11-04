"""
mbclient - minimal Modbus/TCP client (stdlib only).

    from mbclient import ModbusClient
    with ModbusClient("10.2.50.10") as c:
        c.read_input_registers(0, 4)
        c.write_register(15, 500)
"""

import socket
import struct
import threading


class ModbusError(Exception):
    CODES = {1: "ILLEGAL FUNCTION", 2: "ILLEGAL DATA ADDRESS", 3: "ILLEGAL DATA VALUE",
             4: "SERVER DEVICE FAILURE", 11: "GATEWAY TARGET FAILED TO RESPOND"}

    def __init__(self, fc, code):
        self.fc, self.code = fc, code
        super().__init__("FC%02d exception %d (%s)" % (fc, code, self.CODES.get(code, "?")))


class ModbusClient:
    def __init__(self, host, port=502, unit=1, timeout=2.0):
        self.host, self.port, self.unit, self.timeout = host, port, unit, timeout
        self.sock = None
        self.tid = 0
        self.lock = threading.Lock()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()

    def connect(self):
        if self.sock is None:
            self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def _recv(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("connection closed by %s" % self.host)
            buf += chunk
        return buf

    def request(self, pdu):
        with self.lock:
            try:
                self.connect()
                self.tid = (self.tid + 1) & 0xFFFF
                self.sock.sendall(struct.pack(">HHHB", self.tid, 0, len(pdu) + 1, self.unit) + pdu)
                tid, _pid, length, _uid = struct.unpack(">HHHB", self._recv(7))
                resp = self._recv(length - 1)
            except (OSError, ConnectionError):
                self.close()
                raise
        if resp[0] & 0x80:
            raise ModbusError(resp[0] & 0x7F, resp[1])
        return resp

    # -- reads ----------------------------------------------------------------
    def _bits(self, fc, addr, qty):
        resp = self.request(struct.pack(">BHH", fc, addr, qty))
        data = resp[2:]
        return [(data[i // 8] >> (i % 8)) & 1 for i in range(qty)]

    def _regs(self, fc, addr, qty):
        resp = self.request(struct.pack(">BHH", fc, addr, qty))
        return list(struct.unpack(">%dH" % qty, resp[2:2 + qty * 2]))

    def read_coils(self, addr, qty=1):
        return self._bits(1, addr, qty)

    def read_discrete_inputs(self, addr, qty=1):
        return self._bits(2, addr, qty)

    def read_holding_registers(self, addr, qty=1):
        return self._regs(3, addr, qty)

    def read_input_registers(self, addr, qty=1):
        return self._regs(4, addr, qty)

    # -- writes ---------------------------------------------------------------
    def write_coil(self, addr, value):
        self.request(struct.pack(">BHH", 5, addr, 0xFF00 if value else 0))

    def write_register(self, addr, value):
        self.request(struct.pack(">BHH", 6, addr, value & 0xFFFF))

    def write_coils(self, addr, values):
        data = bytearray((len(values) + 7) // 8)
        for i, v in enumerate(values):
            if v:
                data[i // 8] |= 1 << (i % 8)
        self.request(struct.pack(">BHHB", 15, addr, len(values), len(data)) + bytes(data))

    def write_registers(self, addr, values):
        self.request(struct.pack(">BHHB", 16, addr, len(values), len(values) * 2) +
                     struct.pack(">%dH" % len(values), *[v & 0xFFFF for v in values]))

    # -- identification -------------------------------------------------------
    def report_server_id(self):
        resp = self.request(b"\x11")
        return resp[2:2 + resp[1]]

    def read_device_identification(self, read_code=1, object_id=0):
        resp = self.request(bytes([0x2B, 0x0E, read_code, object_id]))
        count, pos, out = resp[6], 7, {}
        for _ in range(count):
            oid, ln = resp[pos], resp[pos + 1]
            out[oid] = resp[pos + 2:pos + 2 + ln].decode("ascii", "replace")
            pos += 2 + ln
        return out


def regs_to_text(regs):
    raw = b"".join(struct.pack(">H", r) for r in regs)
    return raw.split(b"\x00", 1)[0].decode("ascii", "replace")


def text_to_regs(text, count):
    raw = text.encode("ascii", "replace")[:count * 2].ljust(count * 2, b"\x00")
    return [(raw[2 * i] << 8) | raw[2 * i + 1] for i in range(count)]
