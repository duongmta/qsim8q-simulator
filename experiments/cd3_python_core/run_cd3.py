"""Chuyen de 3 experiments: Qiskit BackendV2 <-> Q8PK frames <-> C/C++ core.

Run from the project root (RunChuyenDe3.cmd does this):
    .venv\\Scripts\\python.exe experiments\\cd3_python_core\\run_cd3.py
No serial port, board or FPGA tool is used. All results go to
results/chuyen_de_3/<UTC stamp>/.
"""
import csv
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import struct
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402
from qiskit import QuantumCircuit, transpile  # noqa: E402
from qiskit.circuit import Gate, Parameter  # noqa: E402
from qiskit.circuit.library import CXGate  # noqa: E402
from qiskit.quantum_info import Statevector  # noqa: E402
from qiskit_aer import AerSimulator  # noqa: E402

from qsim8_backend import protocol as p  # noqa: E402
from qsim8_backend.backend_cases import acceptance_circuits  # noqa: E402
from qsim8_backend.benchmark_scaling import scaling_circuits  # noqa: E402
from qsim8_backend.circuit import compare, instruction  # noqa: E402
from qsim8_backend.qiskit_backend import QSim8Backend  # noqa: E402
from local_transport import LocalCoreTransport  # noqa: E402

SEED = 1729
OUT = ROOT / 'results' / 'chuyen_de_3' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
OUT.mkdir(parents=True, exist_ok=True)
LOG = open(OUT / 'run.log', 'w', encoding='utf-8')


def log(*a):
    text = ' '.join(str(x) for x in a)
    print(text, flush=True)
    LOG.write(text + '\n'); LOG.flush()


def med(v):
    return float(np.median(v)) if len(v) else None


def p95(v):
    return float(np.percentile(v, 95)) if len(v) else None


class CountingTransport(LocalCoreTransport):
    """Counts how many times the core service is actually invoked."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.run_calls = 0

    def run(self, *a, **k):
        self.run_calls += 1
        return super().run(*a, **k)


def make_backend():
    transport = CountingTransport()
    backend = QSim8Backend(port='COM99', board=transport)  # port is dormant config only
    backend.connect()
    return backend, transport


AER = AerSimulator(method='statevector', precision='double', max_parallel_threads=1)


def aer_state(circuit):
    saved = circuit.copy()
    saved.save_statevector()
    t0 = time.perf_counter()
    state = np.asarray(AER.run(saved).result().get_statevector(saved), dtype=np.complex128)
    return state, (time.perf_counter() - t0) * 1000


def counts_from_instructions(code, n):
    reads = writes = mults = 0
    one_q = two_q = 0
    pairs = 1 << (n - 1)
    for k in range(len(code) // 16):
        w = int.from_bytes(code[16 * k:16 * k + 16], 'little')
        op = w & 15
        if op in (10, 11):
            two_q += 1
            active = pairs // 2
            if op == 10:
                reads += 2 * active; writes += 2 * active
            else:
                reads += active; writes += active
        else:
            one_q += 1
            reads += 2 * pairs; writes += 2 * pairs
            mults += {1: 4, 6: 2, 7: 8, 8: 8, 9: 8}.get(op, 0) * pairs
    return {'one_q': one_q, 'two_q': two_q, 'state_reads': reads, 'state_writes': writes,
            'real_mults': mults}


def run_case(backend, transport, circuit, repeats, warmup):
    t0 = time.perf_counter()
    compiled = transpile(circuit, backend=backend, optimization_level=0, seed_transpiler=SEED)
    transpile_ms = (time.perf_counter() - t0) * 1000
    ref_orig = np.asarray(Statevector.from_instruction(circuit).data)
    ref_comp = np.asarray(Statevector.from_instruction(compiled).data)
    transpile_err = float(np.max(np.abs(ref_orig - ref_comp)))
    code = backend.compile(compiled)
    rows = []
    for i in range(warmup + repeats):
        expected, aer_ms = aer_state(circuit)
        t1 = time.perf_counter()
        result = backend.run(compiled).result()
        wall_ms = (time.perf_counter() - t1) * 1000
        actual = np.asarray(result.get_statevector(compiled), dtype=np.complex128)
        meta = result.results[0].metadata['qsim8']
        tm = meta['timing']
        m = compare(actual, expected)
        if i >= warmup:
            rows.append({'aer_ms': aer_ms, 'wall_ms': wall_ms, 'metrics': m, 'timing': tm,
                         'raw_sha': hashlib.sha256(json.dumps(meta['raw_state_q30']).encode()).hexdigest(),
                         'source': meta['execution_source']})
    s = code.summary
    tms = [r['timing'] for r in rows]
    out = {
        'name': circuit.name, 'num_qubits': circuit.num_qubits,
        'depth_original': circuit.depth(), 'depth_compiled': compiled.depth(),
        'input_operations': s['input_operations'], 'native_instructions': s['native_instructions'],
        'logical_depth': s['logical_depth'], 'global_phase': float(code.global_phase),
        'transpile_state_error': transpile_err,
        'tx_bytes': tms[0]['tx_bytes'], 'rx_bytes': tms[0]['rx_bytes'],
        'max_error': max(r['metrics']['max_error'] for r in rows),
        'fidelity_min': min(r['metrics']['fidelity'] for r in rows),
        'norm_error': max(r['metrics']['norm_error'] for r in rows),
        'pass_all': all(r['metrics']['pass'] for r in rows),
        'deterministic_raw': len({r['raw_sha'] for r in rows}) == 1,
        'source': rows[0]['source'],
        'transpile_ms': transpile_ms,
        'compile_ms_med': med([t['compile_ms'] for t in tms]),
        'frame_us_med': med([t['frame_us'] for t in tms]),
        'service_us_med': med([t['service_us'] for t in tms]),
        'core_us_med': med([t['accelerator_call_us'] for t in tms]),
        'parse_us_med': med([t['parse_us'] for t in tms]),
        'decode_us_med': med([t['decode_us'] for t in tms]),
        'roundtrip_ms_med': med([t['roundtrip_ms'] for t in tms]),
        'backend_run_ms_med': med([t['backend_run_ms'] for t in tms]),
        'backend_run_ms_p95': p95([t['backend_run_ms'] for t in tms]),
        'wall_ms_med': med([r['wall_ms'] for r in rows]),
        'aer_ms_med': med([r['aer_ms'] for r in rows]),
        'repeats': repeats, 'warmup': warmup,
        'instruction_sha256': hashlib.sha256(code.instructions).hexdigest(),
    }
    out.update(counts_from_instructions(code.instructions, circuit.num_qubits))
    return out


def write_csv(name, rows):
    if not rows:
        return
    keys = list(rows[0].keys())
    for r in rows[1:]:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(OUT / name, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def section_environment():
    pk = {}
    for name in ('qiskit', 'qiskit-aer', 'numpy', 'pydantic', 'pytest'):
        try:
            pk[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pk[name] = None
    build_log = HERE / 'build' / 'compiler.txt'
    env = {'python': sys.version, 'platform': platform.platform(), 'processor': platform.processor(),
           'logical_cpu_count': os.cpu_count(), 'packages': pk,
           'compiler': build_log.read_text(encoding='utf-8', errors='replace') if build_log.exists() else None,
           'core_library': str(next((HERE / 'build').glob('*core*'), '')),
           'sources_sha256': {}}
    for rel in ('hls/qsim8.cpp', 'hls/qsim8.hpp', 'experiments/cd3_python_core/protocol.h', 'qsim8_backend/qiskit_backend.py',
                'qsim8_backend/qiskit_adapter.py', 'qsim8_backend/circuit.py', 'qsim8_backend/protocol.py',
                'experiments/cd3_python_core/core_service.cpp', 'experiments/cd3_python_core/local_transport.py',
                'experiments/cd3_python_core/run_cd3.py'):
        path = ROOT / rel
        env['sources_sha256'][rel] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    (OUT / 'environment.json').write_text(json.dumps(env, indent=2, ensure_ascii=False), encoding='utf-8')
    log('ENV', env['platform'], env['processor'], pk)


def section_pytest():
    cmd = [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '--basetemp', str(OUT / 'pytest_tmp'), 'tests']
    t0 = time.perf_counter()
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
    (OUT / 'pytest.txt').write_text(r.stdout + '\n' + r.stderr, encoding='utf-8')
    tail = [ln for ln in r.stdout.splitlines() if ln.strip()][-3:]
    log('PYTEST rc=', r.returncode, 'time_s=', round(time.perf_counter() - t0, 1), '|', ' / '.join(tail))


def section_acceptance():
    backend, transport = make_backend()
    rows = []
    for c in acceptance_circuits(include_stress=True):
        row = run_case(backend, transport, c, repeats=5, warmup=1)
        row['suite'] = c.metadata['suite']
        rows.append(row)
        log('CASE', row['name'], row['suite'], 'PASS' if row['pass_all'] else 'FAIL',
            f"Emax={row['max_error']:.3e} F={row['fidelity_min']:.12f} En={row['norm_error']:.3e}")
    write_csv('acceptance.csv', rows)
    (OUT / 'acceptance.json').write_text(json.dumps(rows, indent=1), encoding='utf-8')
    mand = [r for r in rows if r['suite'] == 'mandatory']
    log('ACCEPTANCE mandatory', sum(r['pass_all'] for r in mand), '/', len(mand),
        'stress', sum(r['pass_all'] for r in rows if r['suite'] == 'stress'))


def section_scaling():
    backend, transport = make_backend()
    rows = []
    for c in scaling_circuits():
        row = run_case(backend, transport, c, repeats=20, warmup=2)
        row['target_depth'] = c.metadata['target_depth']
        rows.append(row)
        log('SCALE', row['name'], f"m={row['native_instructions']} tx={row['tx_bytes']} rx={row['rx_bytes']}",
            f"run={row['backend_run_ms_med']:.3f}ms core={row['core_us_med']:.1f}us aer={row['aer_ms_med']:.3f}ms",
            'PASS' if row['pass_all'] else 'FAIL')
    write_csv('scaling.csv', rows)
    (OUT / 'scaling.json').write_text(json.dumps(rows, indent=1), encoding='utf-8')


def section_rejection():
    rows = []

    def expect(name, layer, build, action):
        backend, transport = make_backend()
        before = transport.run_calls
        try:
            obj = build()
            action(backend, obj)
            outcome, msg = 'ACCEPTED', ''
        except Exception as exc:  # noqa: BLE001
            outcome, msg = type(exc).__name__, str(exc).splitlines()[0][:160]
        rows.append({'case': name, 'layer': layer, 'outcome': outcome, 'message': msg,
                     'core_called': transport.run_calls != before,
                     'pass': outcome != 'ACCEPTED' and transport.run_calls == before})
        log('REJECT', name, outcome, 'core_called=', transport.run_calls != before, msg[:90])

    def qc_measure():
        q = QuantumCircuit(1, 1); q.h(0); q.measure(0, 0); return q

    def qc_reset():
        q = QuantumCircuit(1); q.reset(0); return q

    def qc_ccx():
        q = QuantumCircuit(3); q.ccx(0, 1, 2); return q

    def qc_param():
        q = QuantumCircuit(1); q.rx(Parameter('a'), 0); return q

    def qc_nine():
        q = QuantumCircuit(9); q.h(0); return q

    def qc_open_ctrl():
        q = QuantumCircuit(2); q.append(CXGate(ctrl_state=0), [0, 1]); return q

    def qc_fake_h():
        q = QuantumCircuit(1); q.append(Gate('h', 1, []), [0]); return q

    def qc_deep():
        q = QuantumCircuit(1)
        for _ in range(21):
            q.h(0)
        return q

    def qc_if():
        q = QuantumCircuit(1, 1)
        q.h(0); q.measure(0, 0)
        with q.if_test((q.clbits[0], 1)):
            q.x(0)
        return q

    run = lambda b, q: b.run(q)  # noqa: E731
    expect('Phép đo (measure)', 'backend', qc_measure, run)
    expect('Reset', 'backend', qc_reset, run)
    expect('Cổng ngoài tập hỗ trợ (CCX) chưa transpile', 'backend', qc_ccx, run)
    expect('Tham số chưa gán giá trị', 'backend', qc_param, run)
    expect('9 qubit', 'backend', qc_nine, run)
    expect('CX điều khiển mở (ctrl_state=0)', 'backend', qc_open_ctrl, run)
    expect('Cổng tự định nghĩa trùng tên "h"', 'backend', qc_fake_h, run)
    expect('Độ sâu 21 lớp', 'backend', qc_deep, run)
    expect('Lệnh điều kiện cổ điển (if_test)', 'backend', qc_if, run)
    expect('Tùy chọn shots=1024', 'backend', lambda: QuantumCircuit(1), lambda b, q: b.run(q, shots=1024))
    expect('Hai mạch trong một lần run', 'backend', lambda: [QuantumCircuit(1), QuantumCircuit(1)],
           lambda b, q: b.run(q))

    # Core-level checks: malformed frames/payloads sent directly through the channel.
    core = LocalCoreTransport(); core.connect()
    good = instruction('H', 0)

    def raw_frame(kind, payload, *, crc_ok=True, version=1):
        header = p.HEADER.pack(p.MAGIC, p.VERSION, kind, 0, 77, len(payload))
        pkt = bytearray(header + payload + struct.pack('<I', __import__('zlib').crc32(header[4:] + payload)))
        if version != 1:
            pkt[4] = version
            body = bytes(pkt[4:-4]); pkt[-4:] = struct.pack('<I', __import__('zlib').crc32(body))
        if not crc_ok:
            pkt[-1] ^= 0xFF
        return bytes(pkt)

    def word(op, t, c=15, p0=0, p1=0, reserved=0):
        w = op | (t << 4) | (c << 8) | ((p0 & 0xffffffff) << 12) | ((p1 & 0xffffffff) << 44) | (reserved << 76)
        return w.to_bytes(16, 'little')

    def run_payload(nq, basis, code):
        return struct.pack('<HH', nq, basis) + code

    cases = [
        ('CRC sai (1 byte cuối bị đảo)', raw_frame(p.RUN, run_payload(1, 0, good), crc_ok=False)),
        ('Phiên bản giao thức sai', raw_frame(p.RUN, run_payload(1, 0, good), version=2)),
        ('Độ dài payload không chia hết 16', raw_frame(p.RUN, run_payload(1, 0, good)[:-3])),
        ('Số qubit = 9', raw_frame(p.RUN, run_payload(9, 0, good))),
        ('Trạng thái đầu vượt 2^n', raw_frame(p.RUN, run_payload(2, 4, good))),
        ('257 lệnh', raw_frame(p.RUN, run_payload(1, 0, good * 257)[:4 + 16 * 257])),
        ('Opcode 12 (không tồn tại)', raw_frame(p.RUN, run_payload(2, 0, word(12, 0)))),
        ('Qubit đích ≥ n', raw_frame(p.RUN, run_payload(2, 0, word(1, 2)))),
        ('CNOT điều khiển trùng đích', raw_frame(p.RUN, run_payload(2, 0, word(10, 1, 1)))),
        ('Cổng một qubit có trường control', raw_frame(p.RUN, run_payload(2, 0, word(1, 0, 1)))),
        ('Hệ số quay không chuẩn hóa', raw_frame(p.RUN, run_payload(1, 0, word(7, 0, 15, 1 << 30, 1 << 30)))),
        ('Bit dự phòng khác 0', raw_frame(p.RUN, run_payload(1, 0, word(1, 0, reserved=1)))),
        ('Lệnh không xác định (type 0x07)', raw_frame(0x07, b'')),
    ]
    for name, frame in cases:
        n = __import__('ctypes').c_uint32(0)
        core.lib.q8_service(frame, len(frame), core.out, len(core.out), __import__('ctypes').byref(n))
        reply = core.out.raw[:n.value]
        kind = reply[5] if len(reply) > 5 else None
        size = struct.unpack_from('<I', reply, 12)[0] if len(reply) >= 16 else 0
        code = struct.unpack_from('<I', reply, 16)[0] if kind == p.ERROR and size >= 4 else None
        msg = reply[20:16 + size].decode('ascii', 'replace') if kind == p.ERROR else ''
        rows.append({'case': name, 'layer': 'core', 'outcome': f'ERROR code {code}' if kind == p.ERROR else f'type 0x{kind:02x}',
                     'message': msg, 'core_called': kind != p.ERROR, 'pass': kind == p.ERROR})
        log('REJECT-CORE', name, rows[-1]['outcome'], msg)
    write_csv('rejection.csv', rows)
    log('REJECTION', sum(r['pass'] for r in rows), '/', len(rows))


def section_roundtrip_identity():
    """Packed payload -> core -> reply: check sizes against the analytical formulas."""
    core = LocalCoreTransport(); core.connect()
    rows = []
    for n in range(1, 9):
        for m in (0, 1, 16, 64, 256):
            code = instruction('X', 0) * m
            _, t, _ = core.run(n, 0, code)
            rows.append({'n': n, 'm': m, 'tx_bytes': t['tx_bytes'], 'rx_bytes': t['rx_bytes'],
                         'tx_formula': 24 + 16 * m, 'rx_formula': 36 + 8 * (1 << n)})
    ok = all(r['tx_bytes'] == r['tx_formula'] and r['rx_bytes'] == r['rx_formula'] for r in rows)
    write_csv('frame_sizes.csv', rows)
    log('FRAME_SIZES', 'match formulas' if ok else 'MISMATCH', len(rows))


def main():
    status = {}
    for name, fn in [('environment', section_environment), ('frame_sizes', section_roundtrip_identity),
                     ('rejection', section_rejection), ('acceptance', section_acceptance),
                     ('scaling', section_scaling), ('pytest', section_pytest)]:
        t0 = time.perf_counter()
        try:
            fn(); status[name] = 'OK'
        except Exception:  # noqa: BLE001
            status[name] = 'ERROR'
            log('SECTION_ERROR', name, traceback.format_exc())
        log('SECTION', name, status[name], f'{time.perf_counter() - t0:.1f}s')
    (OUT / 'status.json').write_text(json.dumps(status, indent=1), encoding='utf-8')
    log('OUTPUT', OUT)
    return 0 if all(v == 'OK' for v in status.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
