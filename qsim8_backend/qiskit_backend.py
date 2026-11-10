"""Direct QuantumCircuit -> Q8PK UART -> Zybo HLS -> Qiskit Result.

Constructing/transpiling/compiling never opens COM. run() lazily connects after
validation. UART errors propagate; no reference simulator or HTTP is called.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import re
import threading
import time
import uuid

import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit import Parameter
from qiskit.circuit.library import (
    HGate, XGate, YGate, ZGate, SGate, TGate, RXGate, RYGate, RZGate, CXGate, CZGate,
    SwapGate,
)
from qiskit.providers import BackendV2, Options
from qiskit.result import Result
from qiskit.transpiler import Target

from .qiskit_adapter import compile_quantum_circuit
from .qiskit_job import QSim8Job
from .transport import Board


class QSim8Backend(BackendV2):
    """Eight-qubit statevector simulator executed on a Zybo FPGA.

    One circuit per run; no shots, measurement, reset, noise or dynamic circuits.
    ``board`` is for explicit dependency injection in software tests; results from
    substitutes are marked ``injected_transport``, never serial hardware evidence.
    """

    def __init__(self, port='COM14', *, board=None):
        if not isinstance(port, str) or not re.fullmatch(r'COM[1-9][0-9]{0,3}', port.upper()):
            raise ValueError('port must be a Windows COM port such as COM14.')
        super().__init__(name='qsim8_zybo', backend_version='2.0.0',
                         description='Zybo Q2.30 statevector simulator over Q8PK UART')
        self.port = port.upper()
        self._board = Board() if board is None else board
        self._injected = board is not None
        self._run_lock = threading.RLock()
        self._needs_reconnect = False
        self._target = Target(description='1..8 logical qubits, all-to-all supported gates', num_qubits=8)
        theta = Parameter('theta')
        # Global properties mean any valid qubit pair. No physical mapping or
        # padding of a one-qubit experiment to an eight-qubit statevector is needed.
        for gate in (HGate(), XGate(), YGate(), ZGate(), SGate(), TGate(),
                     RXGate(theta), RYGate(theta), RZGate(theta), CXGate(), CZGate(),
                     SwapGate()):
            self._target.add_instruction(gate)

    @property
    def target(self):
        return self._target

    @property
    def max_circuits(self):
        return 1

    @classmethod
    def _default_options(cls):
        return Options()  # Statevector only. Unsupported options are errors.

    def compile(self, circuit):
        """Pure validation/lowering; may be used before connecting a board."""
        return compile_quantum_circuit(circuit)

    def connect(self):
        with self._run_lock:
            info = self._board.connect(self.port)
            self._needs_reconnect = False
            return info

    def close(self):
        with self._run_lock:
            self._board.disconnect()

    disconnect = close

    def diagnostics(self):
        """Return a read-only snapshot useful after a failed UART transaction."""
        with self._run_lock:
            return {
                'backend_name': self.name,
                'backend_version': self.backend_version,
                'configured_port': self.port,
                'needs_explicit_reconnect': self._needs_reconnect,
                'execution_source': 'injected_transport' if self._injected else 'serial_qsim8',
                'transport_class': type(self._board).__name__,
                'transport_status': deepcopy(self._board.status()),
                'last_exchange': deepcopy(getattr(self._board, 'last_exchange', None)),
            }

    def __enter__(self):
        return self  # Connection remains lazy until run() or explicit connect().

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def run(self, run_input, **options):
        if options or dict(self.options):
            raise ValueError('QSim8Q accepts no run options: shots/noise/measurement are unsupported.')
        if isinstance(run_input, (list, tuple)):
            if len(run_input) != 1:
                raise ValueError('QSim8Q accepts exactly one circuit per run().')
            run_input = run_input[0]
        if not isinstance(run_input, QuantumCircuit):
            raise TypeError('run() expects a QuantumCircuit or a one-element list.')
        # Copy before submission so later caller mutations cannot alter job metadata.
        circuit = run_input.copy()
        start = time.perf_counter()
        compiled = self.compile(circuit)
        compile_ms = (time.perf_counter() - start) * 1000
        job_id = str(uuid.uuid4())
        connection_ms = 0.0
        with self._run_lock:
            if self._needs_reconnect:
                raise RuntimeError('Previous UART run failed. Recover the board if needed, then call connect().')
            if not self._board.status()['connected']:
                connection_start = time.perf_counter()
                self.connect()
                connection_ms = (time.perf_counter() - connection_start) * 1000
            try:
                raw_state, timing, info = self._board.run(circuit.num_qubits, 0, compiled.instructions)
                raw_state = np.asarray(raw_state, dtype=np.complex128)
                if raw_state.shape != (1 << circuit.num_qubits,) or not np.all(np.isfinite(raw_state)):
                    raise RuntimeError('Invalid statevector returned by transport.')
                transaction = deepcopy(getattr(self._board, 'last_exchange', None))
            except Exception:
                self._needs_reconnect = True
                self._board.disconnect()
                raise

        # Qiskit may introduce a global phase during transpilation. Firmware ABI
        # has no scalar-phase field. Preserve raw FPGA data and explicitly record
        # this one scalar multiplication on PC; never silently drop the phase.
        state = raw_state * np.exp(1j * compiled.global_phase)
        raw_q30 = np.column_stack((raw_state.real, raw_state.imag)) * (1 << 30)
        metadata = {
            'schema_version': 1,
            'execution_source': 'injected_transport' if self._injected else 'serial_qsim8',
            'transport_class': type(self._board).__name__,
            'created_utc': datetime.now(timezone.utc).isoformat(),
            'summary': compiled.summary,
            'timing': {**timing, 'compile_ms': compile_ms, 'connection_ms': connection_ms,
                       'backend_run_ms': (time.perf_counter() - start) * 1000},
            'board': deepcopy(info),
            'instruction_hex': compiled.instructions.hex(),
            'instruction_sha256': hashlib.sha256(compiled.instructions).hexdigest(),
            'raw_state_q30': np.rint(raw_q30).astype(np.int64).tolist(),
            'global_phase': compiled.global_phase,
            'phase_correction': 'host_scalar' if compiled.global_phase else 'none',
            'bit_order': 'q0 is least significant; basis strings q(n-1)...q0',
            'transaction': transaction,
        }
        result = Result.from_dict({
            'backend_name': self.name, 'backend_version': self.backend_version,
            'job_id': job_id, 'qobj_id': None, 'success': True, 'status': 'COMPLETED',
            'time_taken': (time.perf_counter() - start),
            'results': [{
                'shots': 0, 'success': True, 'status': 'DONE',
                'header': {'name': circuit.name, 'n_qubits': circuit.num_qubits,
                           'metadata': deepcopy(circuit.metadata)},
                'data': {'statevector': state, 'raw_statevector': raw_state.copy()},
                'metadata': {'qsim8': metadata},
                'time_taken': timing['roundtrip_ms'] / 1000,
            }],
        })
        return QSim8Job(self, job_id, result)
