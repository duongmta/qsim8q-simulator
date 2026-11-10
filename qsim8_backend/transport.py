"""Only explicit connect/run API calls open or write a serial port."""
import struct
import logging
import threading
import time

import numpy as np
import serial
from serial.tools import list_ports

from . import protocol as p
log = logging.getLogger('uvicorn.error')


class Board:
    def __init__(self):
        self.lock = threading.Lock()
        self.serial = None
        self.info = None
        self.sequence = 0
        self.last_error = None
        self.last_exchange = None

    @staticmethod
    def ports():
        return [{'device': x.device, 'description': x.description} for x in list_ports.comports()]

    def _exchange(self, kind, payload=b''):
        if self.serial is None or not self.serial.is_open:
            raise RuntimeError('Chưa kết nối Zybo. Nạp firmware rồi bấm Kết nối.')
        self.sequence = (self.sequence + 1) & 0xffffffff
        packet = p.frame(kind, self.sequence, payload)
        self.last_exchange = {'request_id': self.sequence, 'request_type': kind,
                              'tx_frame_hex': packet.hex(), 'crc_validated': False}
        log.info('Q8 UART TX type=0x%02x id=%d bytes=%d prefix=%s',
                 kind, self.sequence, len(packet), packet[:20].hex(' '))
        written = self.serial.write(packet)
        if written != len(packet):
            raise RuntimeError('Không gửi đủ gói UART.')
        self.serial.flush()
        try:
            reply = p.receive(self.serial, self.sequence, timeout=4 if kind == p.HELLO else 12)
        except TimeoutError as exc:
            command = 'HELLO' if kind == p.HELLO else 'RUN'
            raise TimeoutError(f'{command}: {exc}') from exc
        log.info('Q8 UART RX type=0x%02x id=%d payload=%d', reply[0], self.sequence, len(reply[1]))
        # receive() has checked header, request ID and CRC. This is the decoded
        # payload, not a fabricated capture of an entire RX frame.
        self.last_exchange.update(response_type=reply[0], received_payload_hex=reply[1].hex(),
                                  crc_validated=True)
        return reply

    def _close(self):
        if self.serial:
            self.serial.close()
        self.serial = self.info = None

    def connect(self, port: str):
        with self.lock:
            self._close()
            self.last_error = None
            try:
                # UART has no RTS/CTS flow control. DTR/RTS defaults are not a
                # substitute for receiving a valid Q8PK HELLO response.
                link = serial.Serial(
                    port=port,
                    baudrate=115200,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=0.25,
                    write_timeout=3,
                    rtscts=False,
                    dsrdtr=False,
                    xonxoff=False,
                )
                self.serial = link

                # Give the Windows/FTDI VCP path a brief moment to settle after open,
                # then clear stale bytes before sending the binary HELLO frame.
                time.sleep(0.10)
                link.reset_input_buffer()
                link.reset_output_buffer()

                kind, payload = self._exchange(p.HELLO)
                if kind != p.HELLO_REPLY or len(payload) != 12:
                    raise RuntimeError('Bo không trả HELLO QSim8Q. Không dùng firmware HGate1Q.')
                nq, layers, count, word_bytes, build = struct.unpack('<HHHHI', payload)
                if (nq, layers, count, word_bytes, build) != (8, 20, 256, 16, 0x00010000):
                    raise RuntimeError('Firmware không tương thích bản phần mềm này.')
                self.info = {'port': port, 'max_qubits': nq, 'max_layers': layers,
                             'max_instructions': count, 'firmware': f'{build:08x}'}
                return self.info.copy()
            except Exception as exc:
                self.last_error = f'{port}: {exc}'
                log.error('Q8 connect failed: %s', self.last_error)
                self._close()
                raise

    def disconnect(self):
        with self.lock:
            self._close()

    def status(self):
        with self.lock:
            return {'connected': self.info is not None, 'board': self.info,
                    'last_error': self.last_error}

    def run(self, num_qubits: int, initial_basis: int, instructions: bytes):
        with self.lock:
            start = time.perf_counter()
            try:
                kind, data = self._exchange(p.RUN, struct.pack('<HH', num_qubits, initial_basis) + instructions)
                # Prefix: nq u16, amplitude count u16, PS timer frequency u32, elapsed PS ticks u64.
                if kind != p.RUN_REPLY or len(data) < 16:
                    raise RuntimeError('Phản hồi RUN không hợp lệ.')
                nq, count, hz, ticks = struct.unpack_from('<HHIQ', data)
                if nq != num_qubits or count != 1 << nq or len(data) != 16 + count * 8 or hz == 0:
                    raise RuntimeError('State-vector hoặc thông tin timer không hợp lệ.')
                raw = np.frombuffer(data, dtype='<i4', offset=16).reshape(count, 2)
                values = raw[:, 0].astype(float) / (1 << 30) + 1j * raw[:, 1].astype(float) / (1 << 30)
                return values, {'roundtrip_ms': (time.perf_counter() - start) * 1000,
                                'accelerator_call_us': ticks / hz * 1e6,
                                'timer_ticks': ticks, 'timer_hz': hz}, self.info.copy()
            except Exception as exc:
                # The user must explicitly reconnect after an uncertain transaction.
                self.last_error = str(exc)
                log.error('Q8 run failed: %s', exc)
                self._close()
                raise
