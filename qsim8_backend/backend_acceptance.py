"""Reproducible Qiskit BackendV2 acceptance; no UART unless --hardware is given.

Examples (run in the project root):
  python -m qsim8_backend.backend_acceptance --reference-only
  python -m qsim8_backend.backend_acceptance --hardware --port COM14 --stress

Aer is the thesis reference. --reference statevector is an explicit diagnostic
alternative; neither reference-only nor Statevector mode claims Aer acceptance.
"""
import argparse
import csv
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from qiskit import qasm3, transpile
from qiskit.quantum_info import Statevector

from .backend_cases import acceptance_circuits
from .circuit import compare

ROOT = Path(__file__).resolve().parents[1]
SEED_TRANSPILER = 1729
MANDATORY_CASES = 15
THESIS_RELATIVE = Path('Chỉnh sửa thuyết minh') / '1. TMDT_Dương - Sửa_bổ sung theo HĐ.docx'
EXPECTED_THESIS_SHA256 = '16575ab86b35580529fb539303d609e98842e0478388375b43d7c88a32d7a988'


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _json_default(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f'Cannot serialize {type(value).__name__}')


def _state_pairs(state):
    return [[float(x.real), float(x.imag)] for x in state]


def _versions():
    packages = {}
    for name in ('qiskit', 'qiskit-aer', 'numpy', 'pyserial', 'pydantic'):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {
        'python': sys.version,
        'platform': platform.platform(),
        'machine': platform.machine(),
        'processor': platform.processor() or None,
        'logical_cpu_count': os.cpu_count(),
        'packages': packages,
    }


def _provenance():
    names = [
        'qsim8_backend/backend_acceptance.py', 'qsim8_backend/backend_cases.py',
        'qsim8_backend/qiskit_backend.py', 'qsim8_backend/qiskit_adapter.py',
        'qsim8_backend/qiskit_job.py', 'qsim8_backend/circuit.py',
        'qsim8_backend/protocol.py', 'qsim8_backend/transport.py',
        'tests/test_qiskit_backend.py', 'requirements.txt', 'pyproject.toml',
        'hls/qsim8.cpp', 'hls/qsim8.hpp', 'hls/qsim8_tb.cpp', 'hls/hls_config.cfg',
        'firmware/main.c', 'firmware/protocol.h',
        'build/hls_gui/qsim8/qsim8/hls/syn/report/qsim8_csynth.rpt',
        'build/hls_gui/qsim8/qsim8/hls/sim/report/qsim8_cosim.rpt',
        'build/qsim8_zybo.xsa',
        'build/vivado/qsim8_zybo.runs/impl_1/system_wrapper.bit',
        'build/vivado/qsim8_zybo.runs/impl_1/system_wrapper_utilization_placed.rpt',
        'build/vivado/qsim8_zybo.runs/impl_1/system_wrapper_timing_summary_routed.rpt',
        'build/vitis/qsim8_app/build/qsim8_app.elf',
        'build/vitis/qsim8_platform/export/qsim8_platform/sw/boot/fsbl.elf',
    ]
    files = []
    for name in names:
        path = ROOT / name
        files.append({'path': name, 'exists': path.is_file(),
                      'sha256': _sha256(path) if path.is_file() else None})
    thesis = ROOT.parent / THESIS_RELATIVE
    thesis_hash = _sha256(thesis) if thesis.is_file() else None
    return {
        'project_root': str(ROOT), 'files': files,
        'artifact_hash_scope': 'Local files only; hashes do not prove which bitstream/ELF is currently loaded on the board.',
        'thesis': {'path': str(thesis), 'sha256': thesis_hash,
                   'expected_sha256': EXPECTED_THESIS_SHA256,
                   'matches_reviewed_version': thesis_hash == EXPECTED_THESIS_SHA256,
                   'criteria': 'section 15.2.3 and product table: at least 15 cases, 15/15 pass'},
    }


def _backend_factory(port=None):
    from .qiskit_backend import QSim8Backend
    # Reference-only mode still needs the BackendV2 Target for transpilation,
    # but must never open a serial port.  The concrete port value is therefore
    # just dormant configuration until --hardware is selected.
    return QSim8Backend(port=port or 'COM14')


def _make_reference(engine):
    if engine == 'statevector':
        def evaluate(circuit):
            start = time.perf_counter()
            state = np.asarray(Statevector.from_instruction(circuit).data, dtype=np.complex128)
            return state, (time.perf_counter() - start) * 1000
        return evaluate
    # Deliberately no fallback: a missing Aer installation invalidates this run.
    try:
        from qiskit_aer import AerSimulator
    except ImportError as exc:
        raise RuntimeError('Aer reference requested but qiskit-aer is unavailable. Install requirements.txt or explicitly select --reference statevector for diagnostics.') from exc
    simulator = AerSimulator(method='statevector', precision='double', max_parallel_threads=1)

    def evaluate(circuit):
        saved = circuit.copy()
        saved.save_statevector()
        start = time.perf_counter()
        state = np.asarray(simulator.run(saved).result().get_statevector(saved), dtype=np.complex128)
        return state, (time.perf_counter() - start) * 1000
    return evaluate


def _stats(values):
    if not values:
        return None
    return {'count': len(values), 'median': float(np.median(values)),
            'p95': float(np.percentile(values, 95)),
            'min': float(min(values)), 'max': float(max(values))}


def _timing_summary(row):
    measured = row.get('measured', [])
    result = {'reference_original_ms': _stats([r['reference_original_ms'] for r in measured]),
              'reference_compiled_ms': _stats([r['reference_compiled_ms'] for r in measured])}
    for field in ('accelerator_call_us', 'roundtrip_ms'):
        result[field] = _stats([r['qsim8']['timing'][field] for r in measured
                               if field in r.get('qsim8', {}).get('timing', {})])
    result['backend_run_ms'] = _stats([r['backend_run_ms'] for r in measured if 'backend_run_ms' in r])
    return result


def _status(manifest):
    rows = manifest['tests']
    mandatory = [r for r in rows if r['suite'] == 'mandatory']
    stress = [r for r in rows if r['suite'] == 'stress']
    repetitions = manifest['configuration']['repeats']
    complete = (manifest['error'] is None and len(mandatory) == MANDATORY_CASES
                and len(rows) == manifest['expected_case_count']
                and all(len(r.get('measured', [])) == repetitions for r in rows))
    if not complete:
        return 'INCOMPLETE', 0, 0
    if manifest['mode'] == 'reference_only':
        return 'REFERENCE_ONLY', 0, 0
    passed = sum(r['status'] == 'PASS' for r in mandatory)
    stress_passed = sum(r['status'] == 'PASS' for r in stress)
    return ('PASS' if passed == MANDATORY_CASES and stress_passed == len(stress) else 'FAIL',
            passed, stress_passed)


def _write_reports(folder, manifest):
    status, passed, stress_passed = _status(manifest)
    stress_count = sum(row['suite'] == 'stress' for row in manifest['tests'])
    hardware_suite_complete = manifest['mode'] == 'hardware' and status in {'PASS', 'FAIL'}
    mandatory_complete = hardware_suite_complete and passed == MANDATORY_CASES
    manifest['status'] = status
    manifest['mandatory_hardware_passed'] = passed
    manifest['stress_hardware_passed'] = stress_passed
    manifest['stress_cases_selected'] = stress_count
    manifest['stress_all_passed'] = hardware_suite_complete and stress_passed == stress_count
    # The thesis denominator is the mandatory 15.  Optional stress failures
    # remain a non-zero overall run but do not rewrite a genuine 15/15 result.
    manifest['hardware_acceptance_complete'] = mandatory_complete
    manifest['thesis_aer_acceptance_complete'] = (
        mandatory_complete and manifest['configuration']['reference'] == 'aer'
    )
    json_path = folder / 'manifest.json'
    json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=_json_default, allow_nan=False), encoding='utf-8')
    fields = ['case', 'suite', 'status', 'num_qubits', 'depth_original', 'depth_compiled',
              'native_instructions', 'measured_repeats', 'max_error_worst', 'fidelity_min',
              'norm_error_worst', 'reference_median_ms', 'accelerator_median_us', 'roundtrip_median_ms']
    with (folder / 'summary.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in manifest['tests']:
            metrics = [r['metrics'] for r in row.get('measured', []) if 'metrics' in r]
            timing = _timing_summary(row)
            writer.writerow({
                'case': row['name'], 'suite': row['suite'], 'status': row['status'],
                'num_qubits': row['num_qubits'], 'depth_original': row['depth_original'],
                'depth_compiled': row.get('depth_compiled'),
                'native_instructions': row.get('summary', {}).get('native_instructions'),
                'measured_repeats': len(row.get('measured', [])),
                'max_error_worst': max((m['max_error'] for m in metrics), default=None),
                'fidelity_min': min((m['fidelity'] for m in metrics), default=None),
                'norm_error_worst': max((m['norm_error'] for m in metrics), default=None),
                'reference_median_ms': (timing['reference_original_ms'] or {}).get('median'),
                'accelerator_median_us': (timing['accelerator_call_us'] or {}).get('median'),
                'roundtrip_median_ms': (timing['roundtrip_ms'] or {}).get('median'),
            })
    lines = [
        '# QSim8Q BackendV2 — báo cáo chạy nghiệm thu', '',
        f"- Trạng thái: **{status}**; chế độ: `{manifest['mode']}`.",
        f"- Tham chiếu: `{manifest['configuration']['reference']}`; số lần đo/ca: {manifest['configuration']['repeats']}; warm-up/ca: {manifest['configuration']['warmup']}.",
        f'- Số ca phần cứng đạt đủ số lần đo: **{passed}/{MANDATORY_CASES}**.',
        f"- Hoàn tất nghiệm thu phần cứng với Aer: **{manifest['thesis_aer_acceptance_complete']}**.",
        f"- Stress tùy chọn đạt: **{stress_passed}/{stress_count}**; "
        f"tất cả stress đạt: **{manifest['stress_all_passed']}**.",
        '', 'REFERENCE_ONLY chỉ xác minh luồng Qiskit và tạo tham chiếu; không phải kết quả FPGA.',
        'INCOMPLETE nghĩa là chưa đủ ca/lần đo hoặc có lỗi; không được công bố đạt 15/15.',
        '', '| Ca | Nhóm | Trạng thái | Lần đo đã lưu |', '|---|---|---|---:|',
    ]
    for row in manifest['tests']:
        lines.append(f"| {row['name']} | {row['suite']} | {row['status']} | {len(row.get('measured', []))} |")
    lines.extend([
        '', '## Diễn giải và khả năng tái lập', '',
        '- Tiêu chí từng lần chạy: Emax ≤ 1e-2, fidelity ≥ 0.99, |norm² − 1| ≤ 1e-2, đúng 2^n biên độ.',
        '- Dùng nguyên 15 đầu vào của qsim8_backend/acceptance.py. SWAP_5Q chuẩn bị |00001⟩ bằng X(0), nên thêm một lệnh thực thi so với giao diện dùng initial_basis=1.',
        '- Mạch được transpile với optimization_level=0 và seed=1729. So sánh riêng tham chiếu mạch gốc và mạch đã transpile để phát hiện thay đổi thứ tự qubit/ngữ nghĩa.',
        '- Aer: method=statevector, precision=double, max_parallel_threads=1. Thời gian tham chiếu là wall time gọi mô phỏng/nhận state-vector, không gồm tạo bản sao và save_statevector.',
        '- accelerator_call_us do ARM đo quanh lời gọi IP; gồm điều khiển/polling AXI, không phải số chu kỳ PL thuần túy. roundtrip_ms gồm UART. backend_run_ms gồm toàn bộ backend.run().',
        '- Lưu mọi lần warm-up và đo riêng. Median/p95 chỉ dùng các lần đo; không kết luận tăng tốc từ các tải rất nhỏ.',
        '- raw_state_q30 giữ biên độ thô từ UART. Nếu mạch có global phase, phase_correction=host_scalar công khai phép nhân vô hướng trên host; dữ liệu thô vẫn giữ nguyên.',
        '- QASM là bản mạch để đọc/tái lập; global_phase được lưu riêng trong manifest vì định dạng/exporter có thể bỏ thông tin pha toàn cục.',
        '- Hash .bit/.xsa/.elf chỉ xác định file tại máy tính; cần thêm log nạp/ILA để chứng minh artifact thực sự đang chạy trong PL.',
        '- Stress 20 lớp là kiểm tra giới hạn sản phẩm riêng, không thay đổi mẫu số 15 ca bắt buộc.',
    ])
    if manifest['error']:
        lines.extend(['', '## Lỗi', '', '```text', manifest['error'], '```'])
        if manifest.get('failure_diagnostics'):
            lines.extend([
                '', 'Chi tiết trạng thái transport và frame cuối được lưu trong '
                '`manifest.json` tại trường `failure_diagnostics`.',
            ])
    (folder / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return json_path


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--hardware', action='store_true', help='Explicitly connect to and execute on Zybo')
    mode.add_argument('--reference-only', action='store_true', help='Default: no UART access or FPGA acceptance claim')
    parser.add_argument('--port', help='Required with --hardware, e.g. COM14')
    parser.add_argument('--reference', choices=('aer', 'statevector'), default='aer')
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--warmup', type=int, default=1)
    parser.add_argument('--output', type=Path, default=ROOT / 'results' / 'backend_v2')
    parser.add_argument('--stress', action='store_true')
    return parser


def main(argv=None):
    parser = _parser()
    invocation_args = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(invocation_args)
    if args.hardware and not args.port:
        parser.error('--hardware requires --port COM14 (or the actual port)')
    if args.repeats < 1 or args.warmup < 0:
        parser.error('--repeats must be positive and --warmup must be non-negative')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = args.output.resolve() / f"{stamp}_{'hardware' if args.hardware else 'reference'}"
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'circuits').mkdir()
    manifest = {
        'schema_version': 'qsim8.backend_acceptance.v1', 'started_utc': _utc(),
        'finished_utc': None, 'mode': 'hardware' if args.hardware else 'reference_only',
        'invocation': {
            'executable': sys.executable,
            'module': 'qsim8_backend.backend_acceptance',
            'arguments': invocation_args,
            'working_directory': str(Path.cwd().resolve()),
        },
        'configuration': {'port': args.port if args.hardware else None,
                          'reference': args.reference, 'repeats': args.repeats,
                          'warmup': args.warmup, 'stress': args.stress,
                          'transpile_optimization_level': 0, 'seed_transpiler': SEED_TRANSPILER,
                          'aer_method': 'statevector' if args.reference == 'aer' else None,
                          'aer_precision': 'double' if args.reference == 'aer' else None,
                          'aer_max_parallel_threads': 1 if args.reference == 'aer' else None},
        'criteria': {'max_error': 1e-2, 'fidelity_min': 0.99, 'norm_error': 1e-2,
                     'mandatory_cases': MANDATORY_CASES, 'amplitude_count': '2**num_qubits'},
        'environment': _versions(), 'provenance': {},
        'expected_case_count': 18 if args.stress else 15, 'tests': [],
        'error': None, 'failure_diagnostics': None,
    }
    backend = None
    active_row = None
    try:
        manifest['provenance'] = _provenance()
        evaluate = _make_reference(args.reference)
        backend = _backend_factory(args.port if args.hardware else None)
        circuits = acceptance_circuits(args.stress)
        if args.hardware:
            backend.connect()
        for circuit in circuits:
            active_row = {
                'name': circuit.name, 'suite': circuit.metadata['suite'],
                'num_qubits': circuit.num_qubits, 'depth_original': circuit.depth(),
                'original_initial_basis': circuit.metadata['original_initial_basis'],
                'basis_preparation': 'explicit_x_gates',
                'status': 'INCOMPLETE', 'warmup': [], 'measured': [],
            }
            manifest['tests'].append(active_row)
            compiled_qc = transpile(circuit, backend=backend, optimization_level=0,
                                    seed_transpiler=SEED_TRANSPILER)
            code = backend.compile(compiled_qc)
            active_row.update(
                depth_compiled=compiled_qc.depth(), summary=code.summary,
                global_phase=float(code.global_phase),
                global_phase_original=float(circuit.global_phase),
                instruction_hex=code.instructions.hex(),
                instruction_sha256=hashlib.sha256(code.instructions).hexdigest())
            for tag, qc in [('original', circuit), ('compiled', compiled_qc)]:
                relative = Path('circuits') / f'{circuit.name}_{tag}.qasm'
                (folder / relative).write_text(qasm3.dumps(qc), encoding='utf-8')
                active_row[f'qasm_{tag}'] = relative.as_posix()
            for index in range(args.warmup + args.repeats):
                is_warmup = index < args.warmup
                expected, original_ms = evaluate(circuit)
                expected_compiled, compiled_ms = evaluate(compiled_qc)
                transpile_error = float(np.max(np.abs(expected - expected_compiled))) if expected.shape == expected_compiled.shape else None
                if transpile_error is None or not np.isfinite(transpile_error) or transpile_error > 1e-10:
                    raise RuntimeError(f'Transpilation changed state-vector/qubit order: {transpile_error}')
                record = {'index': index if is_warmup else index - args.warmup,
                          'started_utc': _utc(), 'reference_original_ms': original_ms,
                          'reference_compiled_ms': compiled_ms,
                          'transpile_max_error': transpile_error,
                          'reference_statevector': _state_pairs(expected),
                          'compiled_reference_statevector': _state_pairs(expected_compiled)}
                active_row['warmup' if is_warmup else 'measured'].append(record)
                if args.hardware:
                    start = time.perf_counter()
                    job = backend.run(compiled_qc)
                    result = job.result()
                    record['backend_run_ms'] = (time.perf_counter() - start) * 1000
                    actual = np.asarray(result.get_statevector(compiled_qc), dtype=np.complex128)
                    record['hardware_statevector'] = _state_pairs(actual)
                    metadata = getattr(result.results[0], 'metadata', {})
                    record['qsim8'] = metadata.get('qsim8', {})
                    if record['qsim8'].get('execution_source') != 'serial_qsim8':
                        raise RuntimeError('Missing serial_qsim8 execution provenance; cannot claim hardware acceptance.')
                    record['metrics'] = compare(actual, expected)
                    record['job_id'] = job.job_id()
                    if is_warmup and not record['metrics']['pass']:
                        raise RuntimeError('Hardware warm-up failed accuracy thresholds.')
            active_row['timing_summary'] = _timing_summary(active_row)
            active_row['status'] = ('PASS' if all(r['metrics']['pass'] for r in active_row['measured']) else 'FAIL') if args.hardware else 'REFERENCE_ONLY'
            print(active_row['name'], active_row['status'], flush=True)
            # Persist between cases as well as in finally to preserve completed data.
            _write_reports(folder, manifest)
        active_row = None
    except (Exception, KeyboardInterrupt) as exc:
        manifest['error'] = f'{type(exc).__name__}: {exc}'
        if backend is not None and hasattr(backend, 'diagnostics'):
            try:
                manifest['failure_diagnostics'] = backend.diagnostics()
            except Exception as diagnostic_error:
                manifest['failure_diagnostics'] = {
                    'collection_error': f'{type(diagnostic_error).__name__}: {diagnostic_error}'
                }
        if active_row is not None:
            active_row['status'] = 'ERROR'
            active_row['error'] = manifest['error']
        print('ACCEPTANCE_ERROR:', manifest['error'], flush=True)
    finally:
        if backend is not None:
            try:
                backend.close()
            except Exception as exc:
                manifest['error'] = (manifest['error'] or '') + f' Close failed: {exc}'
        manifest['finished_utc'] = _utc()
        path = _write_reports(folder, manifest)
        print('Saved:', path, flush=True)
    if manifest['mode'] == 'reference_only' and manifest['status'] == 'REFERENCE_ONLY':
        print('REFERENCE_ONLY: no FPGA acceptance has been performed.')
        return 0
    print(f"HARDWARE_ACCEPTANCE: {manifest['mandatory_hardware_passed']}/15; {manifest['status']}")
    return 0 if manifest['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
