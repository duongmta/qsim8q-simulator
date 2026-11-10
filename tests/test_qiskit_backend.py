"""BackendV2 regression tests.  Every board object is fake; no COM is opened."""
import json
import math

import numpy as np
import pytest
from qiskit import QuantumCircuit, transpile
from qiskit.circuit import Gate, Parameter
from qiskit.circuit.library import CXGate
from qiskit.quantum_info import Statevector
from qiskit.providers import JobStatus

from qsim8_backend import backend_acceptance
from qsim8_backend.backend_cases import acceptance_circuits
from qsim8_backend.circuit import instruction, reference as internal_reference
from qsim8_backend.qiskit_adapter import compile_quantum_circuit
from qsim8_backend.qiskit_backend import QSim8Backend


class FakeBoard:
    """Small transport double that records whether execution was attempted."""

    def __init__(self, state=None, *, connected=False, fail=None):
        self.connected = connected
        self.state = state
        self.fail = fail
        self.connect_calls = 0
        self.run_calls = 0
        self.disconnect_calls = 0
        self.last_exchange = None
        self.info = None

    def status(self):
        return {'connected': self.connected, 'board': self.info, 'last_error': None}

    def connect(self, port):
        self.connect_calls += 1
        self.connected = True
        self.info = {'port': port, 'max_qubits': 8, 'max_layers': 20,
                     'max_instructions': 256, 'firmware': '00010000'}
        return self.info.copy()

    def disconnect(self):
        self.disconnect_calls += 1
        self.connected = False
        self.info = None

    def run(self, num_qubits, initial_basis, instructions):
        self.run_calls += 1
        if self.fail is not None:
            raise self.fail
        assert initial_basis == 0
        value = self.state
        if callable(value):
            value = value(num_qubits, instructions)
        if value is None:
            value = np.r_[np.array([1 + 0j]), np.zeros((1 << num_qubits) - 1)]
        self.last_exchange = {
            'request_id': self.run_calls, 'request_type': 2,
            'tx_frame_hex': '5138504b', 'response_type': 0x82,
            'received_payload_hex': '0000', 'crc_validated': True,
        }
        timing = {'roundtrip_ms': 2.5, 'accelerator_call_us': 17.0,
                  'timer_ticks': 17, 'timer_hz': 1_000_000}
        return np.asarray(value, dtype=np.complex128), timing, self.info.copy()


def test_adapter_encodes_supported_operations_and_swap_order():
    qc = QuantumCircuit(3)
    qc.h(0)
    qc.rx(0.5, 1)
    qc.cx(0, 2)
    qc.swap(1, 2)
    compiled = compile_quantum_circuit(qc)
    expected = (
        instruction('H', 0)
        + instruction('RX', 1, theta=0.5)
        + instruction('CNOT', 2, 0)
        + instruction('CNOT', 2, 1)
        + instruction('CNOT', 1, 2)
        + instruction('CNOT', 2, 1)
    )
    assert compiled.instructions == expected
    assert compiled.summary['native_instructions'] == 6
    assert compiled.summary['scheduled_depth'] == 3


def test_transpile_uses_backend_target_without_touching_transport():
    board = FakeBoard()
    backend = QSim8Backend(board=board)
    qc = QuantumCircuit(2)
    qc.h(0)
    qc.swap(0, 1)
    lowered = transpile(qc, backend=backend, optimization_level=0,
                        seed_transpiler=1729)
    assert set(lowered.count_ops()).issubset({'h', 'swap'})
    assert backend.compile(lowered).summary['native_instructions'] == 4
    assert board.connect_calls == board.run_calls == 0


def test_dense_20_layer_swap_circuit_stays_within_256_native_instructions():
    board = FakeBoard()
    backend = QSim8Backend(board=board)
    qc = QuantumCircuit(8)
    for _ in range(20):
        for q in range(0, 8, 2):
            qc.swap(q, q + 1)
    lowered = transpile(qc, backend=backend, optimization_level=0,
                        seed_transpiler=1729)
    compiled = backend.compile(lowered)
    assert lowered.count_ops() == {'swap': 80}
    assert compiled.summary['gate_count'] == 80
    assert compiled.summary['scheduled_depth'] == 20
    assert compiled.summary['native_instructions'] == 240
    assert len(compiled.instructions) == 240 * 16
    assert board.connect_calls == board.run_calls == 0
    stress = acceptance_circuits(include_stress=True)
    assert len(stress) == 18
    assert stress[-1].name == 'STRESS_SWAP_8Q_20L'


@pytest.mark.parametrize('make_circuit, match', [
    (lambda: QuantumCircuit(9), '1..8'),
    (lambda: QuantumCircuit(1, 1), 'classical bits'),
    (lambda: _with_reset(), 'Unsupported instruction'),
    (lambda: _with_unbound_parameter(), 'Bind all parameters'),
    (lambda: _with_spoofed_h(), 'Unsupported instruction'),
    (lambda: _with_open_control(), 'Unsupported instruction'),
    (lambda: _with_depth(21), '20 logical layers'),
])
def test_validation_rejects_unsupported_semantics(make_circuit, match):
    with pytest.raises((TypeError, ValueError), match=match):
        compile_quantum_circuit(make_circuit())


def _with_reset():
    qc = QuantumCircuit(1)
    qc.reset(0)
    return qc


def _with_unbound_parameter():
    qc = QuantumCircuit(1)
    qc.rx(Parameter('theta'), 0)
    return qc


def _with_spoofed_h():
    qc = QuantumCircuit(1)
    qc.append(Gate('h', 1, []), [0])
    return qc


def _with_open_control():
    qc = QuantumCircuit(2)
    qc.append(CXGate(ctrl_state=0), [0, 1])
    return qc


def _with_depth(depth):
    qc = QuantumCircuit(1)
    for _ in range(depth):
        qc.h(0)
    return qc


def test_invalid_run_is_rejected_before_connecting_or_writing():
    board = FakeBoard()
    backend = QSim8Backend(board=board)
    measured = QuantumCircuit(1, 1)
    measured.measure(0, 0)
    with pytest.raises(ValueError, match='classical bits'):
        backend.run(measured)
    with pytest.raises(ValueError, match='exactly one'):
        backend.run([QuantumCircuit(1), QuantumCircuit(1)])
    with pytest.raises(ValueError, match='no run options'):
        backend.run(QuantumCircuit(1), shots=100)
    assert board.connect_calls == board.run_calls == 0


def test_result_contains_statevector_raw_q30_and_explicit_global_phase():
    board = FakeBoard(state=[1 + 0j, 0j])
    backend = QSim8Backend(port='com14', board=board)
    qc = QuantumCircuit(1, name='phase_case')
    qc.global_phase = math.pi / 2
    job = backend.run(qc)
    result = job.result()
    np.testing.assert_allclose(result.get_statevector(qc), [1j, 0j], atol=1e-14)
    np.testing.assert_allclose(result.data(0)['raw_statevector'], [1, 0], atol=1e-14)
    meta = result.results[0].metadata['qsim8']
    assert job.status() is JobStatus.DONE
    assert board.connect_calls == board.run_calls == 1
    assert meta['execution_source'] == 'injected_transport'
    assert meta['phase_correction'] == 'host_scalar'
    assert meta['raw_state_q30'] == [[1 << 30, 0], [0, 0]]
    assert meta['transaction']['crc_validated'] is True
    assert meta['bit_order'].startswith('q0 is least significant')


def test_failed_transaction_requires_explicit_reconnect():
    board = FakeBoard(connected=True, fail=TimeoutError('UART timeout'))
    backend = QSim8Backend(board=board)
    with pytest.raises(TimeoutError, match='UART timeout'):
        backend.run(QuantumCircuit(1))
    assert board.disconnect_calls == 1
    diagnostics = backend.diagnostics()
    assert diagnostics['needs_explicit_reconnect'] is True
    assert diagnostics['transport_status']['connected'] is False
    assert diagnostics['execution_source'] == 'injected_transport'
    board.fail = None
    with pytest.raises(RuntimeError, match=r'call connect\(\)'):
        backend.run(QuantumCircuit(1))
    backend.connect()
    assert backend.run(QuantumCircuit(1)).result().success


def test_established_suite_has_exactly_15_compilable_mandatory_cases():
    circuits = acceptance_circuits()
    assert len(circuits) == 15
    assert {qc.metadata['suite'] for qc in circuits} == {'mandatory'}
    assert {qc.num_qubits for qc in circuits} == set(range(1, 9))
    for qc in circuits:
        compiled = compile_quantum_circuit(qc)
        assert compiled.summary['native_instructions'] <= 256


def test_adapter_preserves_statevector_for_all_15_established_cases():
    for qc in acceptance_circuits():
        compiled = compile_quantum_circuit(qc)
        actual = internal_reference(compiled.circuit) * np.exp(1j * compiled.global_phase)
        expected = np.asarray(Statevector.from_instruction(qc).data)
        np.testing.assert_allclose(actual, expected, atol=1e-12, err_msg=qc.name)


def test_reference_only_runner_never_calls_connect_or_run(tmp_path, monkeypatch):
    board = FakeBoard()
    backend = QSim8Backend(board=board)
    monkeypatch.setattr(backend_acceptance, '_backend_factory', lambda port=None: backend)
    code = backend_acceptance.main([
        '--reference-only', '--reference', 'statevector', '--repeats', '1',
        '--warmup', '0', '--output', str(tmp_path),
    ])
    manifests = list(tmp_path.glob('*/manifest.json'))
    assert code == 0 and len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding='utf-8'))
    assert manifest['status'] == 'REFERENCE_ONLY'
    assert manifest['hardware_acceptance_complete'] is False
    assert len(manifest['tests']) == 15
    assert board.connect_calls == board.run_calls == 0


def test_hardware_runner_contract_produces_all_15_rows_without_real_uart(
        tmp_path, monkeypatch):
    """Exercise the report branch at the backend/transport boundary.

    The fake returns the mathematical state associated with each exact encoded
    instruction stream.  It never opens COM and its output remains in tmp_path.
    """
    backend = QSim8Backend(port='COM14')
    lookup = {}
    for qc in acceptance_circuits():
        lowered = transpile(qc, backend=backend, optimization_level=0,
                            seed_transpiler=1729)
        code = backend.compile(lowered)
        state = np.asarray(Statevector.from_instruction(lowered).data,
                           dtype=np.complex128)
        raw = state * np.exp(-1j * code.global_phase)
        lookup[(qc.num_qubits, code.instructions)] = raw

    board = FakeBoard(state=lambda n, payload: lookup[(n, payload)])
    backend._board = board
    # This test emulates the serial contract at its boundary.  Production code
    # itself prevents an explicitly injected board from making this claim.
    backend._injected = False
    monkeypatch.setattr(backend_acceptance, '_backend_factory', lambda port=None: backend)
    code = backend_acceptance.main([
        '--hardware', '--port', 'COM14', '--reference', 'statevector',
        '--repeats', '1', '--warmup', '0', '--output', str(tmp_path),
    ])
    manifest_path, = tmp_path.glob('*/manifest.json')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert code == 0
    assert manifest['status'] == 'PASS'
    assert manifest['mandatory_hardware_passed'] == 15
    assert manifest['hardware_acceptance_complete'] is True
    assert manifest['thesis_aer_acceptance_complete'] is False
    assert all(row['status'] == 'PASS' for row in manifest['tests'])
    assert board.connect_calls == 1 and board.run_calls == 15


def test_hardware_runner_preserves_failure_diagnostics(tmp_path, monkeypatch):
    board = FakeBoard()
    backend = QSim8Backend(board=board)

    def fail_connect():
        raise TimeoutError('HELLO timeout from fake transport')

    monkeypatch.setattr(backend, 'connect', fail_connect)
    monkeypatch.setattr(backend_acceptance, '_backend_factory', lambda port=None: backend)
    code = backend_acceptance.main([
        '--hardware', '--port', 'COM14', '--reference', 'statevector',
        '--repeats', '1', '--warmup', '0', '--output', str(tmp_path),
    ])
    manifest_path, = tmp_path.glob('*/manifest.json')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert code == 1
    assert manifest['status'] == 'INCOMPLETE'
    assert 'HELLO timeout' in manifest['error']
    assert manifest['failure_diagnostics']['configured_port'] == 'COM14'
    assert manifest['failure_diagnostics']['transport_status']['connected'] is False


def test_optional_stress_failure_does_not_erase_mandatory_15_pass(tmp_path):
    good_metrics = {'max_error': 0.0, 'fidelity': 1.0, 'norm_error': 0.0,
                    'total_probability': 1.0, 'pass': True}
    bad_metrics = {**good_metrics, 'max_error': 0.2, 'pass': False}

    def row(index, suite, status, metrics):
        return {
            'name': f'case_{index}', 'suite': suite, 'status': status,
            'num_qubits': 1, 'depth_original': 1, 'summary': {},
            'measured': [{'metrics': metrics, 'reference_original_ms': 1.0,
                          'reference_compiled_ms': 1.0}],
        }

    manifest = {
        'mode': 'hardware', 'configuration': {'reference': 'aer', 'repeats': 1,
                                               'warmup': 0},
        'expected_case_count': 16, 'error': None,
        'tests': [row(i, 'mandatory', 'PASS', good_metrics) for i in range(15)]
                 + [row(15, 'stress', 'FAIL', bad_metrics)],
    }
    backend_acceptance._write_reports(tmp_path, manifest)
    assert manifest['status'] == 'FAIL'
    assert manifest['mandatory_hardware_passed'] == 15
    assert manifest['hardware_acceptance_complete'] is True
    assert manifest['thesis_aer_acceptance_complete'] is True
    assert manifest['stress_all_passed'] is False
