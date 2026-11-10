"""In-process transport: Q8PK frames between the Qiskit backend and the C/C++ core.

The class has the same interface as qsim8_backend.transport.Board (connect, status,
run, disconnect, last_exchange), so QSim8Backend can use it through its explicit
``board=`` injection point.  Every request and reply is a complete Q8PK v1 frame
with CRC32; the reply is parsed by the project's own protocol.receive().
"""
import ctypes
import io
import os
import struct
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from qsim8_backend import protocol as p  # noqa: E402

LIB_NAME = 'q8core.dll' if os.name == 'nt' else 'libq8core.so'


class _Stream(io.BytesIO):
    """Byte channel seen by protocol.receive(): read() returns what is available."""


class LocalCoreTransport:
    def __init__(self, library=None):
        path = Path(library) if library else HERE / 'build' / LIB_NAME
        if not path.is_file():
            path = HERE / LIB_NAME
        self.lib = ctypes.CDLL(str(path))
        self.lib.q8_service.argtypes = [ctypes.c_char_p, ctypes.c_uint32, ctypes.c_char_p,
                                        ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
        self.lib.q8_service.restype = ctypes.c_int
        self.out = ctypes.create_string_buffer(20 + 16 + 256 * 8 + 64)
        self.sequence = 0
        self.info = None
        self.last_error = None
        self.last_exchange = None
        self.last_breakdown = None

    def _exchange(self, kind, payload=b''):
        t0 = time.perf_counter()
        self.sequence = (self.sequence + 1) & 0xffffffff
        packet = p.frame(kind, self.sequence, payload)
        t1 = time.perf_counter()
        n = ctypes.c_uint32(0)
        rc = self.lib.q8_service(packet, len(packet), self.out, len(self.out), ctypes.byref(n))
        if rc != 0:
            raise RuntimeError(f'Core service misuse code {rc}.')
        reply = self.out.raw[:n.value]
        t2 = time.perf_counter()
        kind_rx, data = p.receive(_Stream(reply), self.sequence, timeout=2)
        t3 = time.perf_counter()
        self.last_exchange = {'request_id': self.sequence, 'request_type': kind,
                              'tx_bytes': len(packet), 'rx_bytes': len(reply),
                              'response_type': kind_rx, 'crc_validated': True}
        self.last_breakdown = {'frame_us': (t1 - t0) * 1e6, 'service_us': (t2 - t1) * 1e6,
                               'parse_us': (t3 - t2) * 1e6,
                               'tx_bytes': len(packet), 'rx_bytes': len(reply)}
        return kind_rx, data

    def connect(self, port='LOCAL'):
        kind, payload = self._exchange(p.HELLO)
        if kind != p.HELLO_REPLY or len(payload) != 12:
            raise RuntimeError('Invalid HELLO reply.')
        nq, layers, count, word_bytes, build = struct.unpack('<HHHHI', payload)
        if (nq, layers, count, word_bytes, build) != (8, 20, 256, 16, 0x00010000):
            raise RuntimeError('Core capabilities do not match the backend.')
        self.info = {'port': port, 'max_qubits': nq, 'max_layers': layers,
                     'max_instructions': count, 'firmware': f'{build:08x}', 'channel': 'in-process'}
        return self.info.copy()

    def disconnect(self):
        self.info = None

    def status(self):
        return {'connected': self.info is not None, 'board': self.info, 'last_error': self.last_error}

    def run(self, num_qubits, initial_basis, instructions):
        start = time.perf_counter()
        kind, data = self._exchange(p.RUN, struct.pack('<HH', num_qubits, initial_basis) + instructions)
        if kind != p.RUN_REPLY or len(data) < 16:
            raise RuntimeError('Invalid RUN reply.')
        t_dec = time.perf_counter()
        nq, count, hz, ticks = struct.unpack_from('<HHIQ', data)
        if nq != num_qubits or count != 1 << nq or len(data) != 16 + count * 8 or hz == 0:
            raise RuntimeError('Invalid state-vector reply.')
        raw = np.frombuffer(data, dtype='<i4', offset=16).reshape(count, 2)
        values = raw[:, 0].astype(float) / (1 << 30) + 1j * raw[:, 1].astype(float) / (1 << 30)
        end = time.perf_counter()
        self.last_breakdown['decode_us'] = (end - t_dec) * 1e6
        timing = {'roundtrip_ms': (end - start) * 1000, 'accelerator_call_us': ticks / hz * 1e6,
                  'timer_ticks': ticks, 'timer_hz': hz, **self.last_breakdown}
        return values, timing, self.info.copy()
