"""Validate QuantumCircuit and lower it to the existing QSim8Q instruction ABI.

No execution, serial I/O, transpilation or reference simulation occurs here.
"""
from dataclasses import dataclass
import math

from qiskit import QuantumCircuit
from qiskit.circuit import Barrier
from qiskit.circuit.library import (
    HGate, XGate, YGate, ZGate, SGate, TGate, RXGate, RYGate, RZGate,
    CXGate, CZGate, SwapGate,
)

from .circuit import Circuit, MAX_QUBITS, MAX_LAYERS, compile_circuit


STANDARD_GATES = {
    'h': HGate, 'x': XGate, 'y': YGate, 'z': ZGate, 's': SGate, 't': TGate,
    'rx': RXGate, 'ry': RYGate, 'rz': RZGate, 'cx': CXGate, 'cz': CZGate,
    'swap': SwapGate,
}


@dataclass(frozen=True)
class CompiledCircuit:
    instructions: bytes
    summary: dict
    global_phase: float
    circuit: Circuit


def compile_quantum_circuit(qc: QuantumCircuit) -> CompiledCircuit:
    if not isinstance(qc, QuantumCircuit):
        raise TypeError('Expected a qiskit.QuantumCircuit.')
    if not 1 <= qc.num_qubits <= MAX_QUBITS:
        raise ValueError('QSim8Q supports 1..8 qubits.')
    if qc.parameters:
        raise ValueError('Bind all parameters with assign_parameters() before run().')
    if qc.num_clbits:
        raise ValueError('Statevector backend does not accept classical bits/measurement.')
    phase = float(qc.global_phase)
    if not math.isfinite(phase):
        raise ValueError('Circuit global phase must be finite.')

    # Per-wire dependency scheduling preserves order on every used qubit.
    # Independent gates may share a logical layer, as in the web circuit model.
    depths = [0] * qc.num_qubits
    gates = []
    barriers = 0
    for item in qc.data:
        op = item.operation
        qs = [qc.find_bit(q).index for q in item.qubits]
        if item.clbits or getattr(op, 'condition', None) is not None:
            raise ValueError('Classically controlled instructions are unsupported.')
        if op.base_class is Barrier:
            barriers += 1
            if qs:
                level = max(depths[q] for q in qs)
                for q in qs:
                    depths[q] = level
            continue
        expected_class = STANDARD_GATES.get(op.name)
        # Names alone are insufficient: a custom gate called "h" may represent
        # a completely different matrix, and open-controlled CX has other semantics.
        if expected_class is None or op.base_class is not expected_class:
            raise ValueError(f'Unsupported instruction {op.name!r}; transpile for QSim8Q first.')
        two = op.name in {'cx', 'cz', 'swap'}
        if len(qs) != (2 if two else 1) or len(set(qs)) != len(qs):
            raise ValueError(f'Invalid operands for {op.name}.')
        if op.name in {'cx', 'cz'} and op.ctrl_state != 1:
            raise ValueError('Only closed controls (control=1) are native; transpile first.')
        layer = max(depths[q] for q in qs)
        if layer >= MAX_LAYERS:
            raise ValueError('Circuit exceeds 20 logical layers after transpilation.')
        row = {'gate': 'CNOT' if op.name == 'cx' else op.name.upper(),
               'layer': layer, 'target': qs[-1]}
        if two:
            row['control'] = qs[0]
        if op.name in {'rx', 'ry', 'rz'}:
            row['theta'] = float(op.params[0])
        gates.append(row)
        for q in qs:
            depths[q] = layer + 1

    circuit = Circuit(num_qubits=qc.num_qubits, initial_basis=0, gates=gates)
    instructions, summary = compile_circuit(circuit)
    summary.update(scheduled_depth=max(depths), ignored_barriers=barriers,
                   input_operations=len(qc.data), initial_basis=0)
    return CompiledCircuit(instructions, summary, phase, circuit)
