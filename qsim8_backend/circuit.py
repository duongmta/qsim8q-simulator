"""Canonical circuit model. Layers are logical columns, not FPGA clock cycles."""
import math
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector

MAX_QUBITS, MAX_LAYERS, MAX_INSTRUCTIONS = 8, 20, 256
GATES = ('H', 'X', 'Y', 'Z', 'S', 'T', 'RX', 'RY', 'RZ', 'CNOT', 'CZ', 'SWAP')
OPCODES = {name: i + 1 for i, name in enumerate(GATES[:-1])}
ROTATIONS = {'RX', 'RY', 'RZ'}
TWO_QUBIT = {'CNOT', 'CZ', 'SWAP'}


class Gate(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    gate: Literal['H', 'X', 'Y', 'Z', 'S', 'T', 'RX', 'RY', 'RZ', 'CNOT', 'CZ', 'SWAP']
    layer: int = Field(ge=0, lt=MAX_LAYERS, strict=True)
    target: int = Field(ge=0, lt=MAX_QUBITS, strict=True)
    control: int | None = Field(default=None, ge=0, lt=MAX_QUBITS, strict=True)
    theta: float | None = None

    @model_validator(mode='after')
    def operands(self):
        if self.gate in TWO_QUBIT:
            if self.control is None or self.control == self.target:
                raise ValueError('Cổng hai qubit cần hai qubit khác nhau.')
        elif self.control is not None:
            raise ValueError('Cổng một qubit không có control.')
        if self.gate in ROTATIONS:
            if self.theta is None or not math.isfinite(self.theta) or abs(self.theta) > 1000:
                raise ValueError('Góc phải hữu hạn và nằm trong [-1000, 1000] radian.')
        elif self.theta is not None:
            raise ValueError('Chỉ RX, RY, RZ có góc theta.')
        return self


class Circuit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    num_qubits: int = Field(ge=1, le=MAX_QUBITS, strict=True)
    initial_basis: int = Field(default=0, ge=0, le=255, strict=True)
    gates: list[Gate] = Field(default_factory=list, max_length=160)

    @model_validator(mode='after')
    def layout(self):
        if self.initial_basis >= (1 << self.num_qubits):
            raise ValueError('Trạng thái ban đầu vượt số qubit.')
        occupied = set()
        for g in self.gates:
            for q in (g.target, g.control):
                if q is None:
                    continue
                if q >= self.num_qubits:
                    raise ValueError('Cổng nằm ngoài số qubit đang chọn.')
                if (g.layer, q) in occupied:
                    raise ValueError('Hai cổng dùng chung một qubit trong cùng một lớp.')
                occupied.add((g.layer, q))
        return self


def q30(value: float) -> int:
    # Python round and AP_RND_CONV both use round-to-nearest, ties-to-even.
    return max(-(1 << 31), min((1 << 31) - 1, round(value * (1 << 30))))


def instruction(name: str, target: int, control: int | None = None,
                theta: float | None = None) -> bytes:
    p0 = p1 = 0
    if name in ROTATIONS:
        p0, p1 = q30(math.cos(theta / 2)), q30(math.sin(theta / 2))
    word = (OPCODES[name] | (target << 4) | ((15 if control is None else control) << 8)
            | ((p0 & 0xffffffff) << 12) | ((p1 & 0xffffffff) << 44))
    return word.to_bytes(16, 'little')


def compile_circuit(c: Circuit) -> tuple[bytes, dict]:
    native = []
    for g in sorted(c.gates, key=lambda g: (g.layer, g.target)):
        if g.gate == 'SWAP':
            a, b = g.control, g.target
            native.extend([instruction('CNOT', b, a), instruction('CNOT', a, b),
                           instruction('CNOT', b, a)])
        else:
            native.append(instruction(g.gate, g.target, g.control, g.theta))
    if len(native) > MAX_INSTRUCTIONS:
        raise ValueError('Mạch sau phân rã vượt 256 lệnh.')
    # Actual dependency depth can be less than the occupied UI column span.
    depths = [0] * c.num_qubits
    for g in sorted(c.gates, key=lambda g: (g.layer, g.target)):
        qs = [g.target] + ([] if g.control is None else [g.control])
        d = max(depths[q] for q in qs) + 1
        for q in qs:
            depths[q] = d
    return b''.join(native), {
        'num_qubits': c.num_qubits, 'gate_count': len(c.gates),
        'column_span': max((g.layer + 1 for g in c.gates), default=0),
        'logical_depth': max(depths), 'native_instructions': len(native),
    }


def reference(c: Circuit) -> np.ndarray:
    qc = QuantumCircuit(c.num_qubits)
    for q in range(c.num_qubits):
        if c.initial_basis & (1 << q):
            qc.x(q)
    for g in sorted(c.gates, key=lambda g: (g.layer, g.target)):
        if g.gate in ROTATIONS:
            getattr(qc, g.gate.lower())(g.theta, g.target)
        elif g.gate == 'CNOT':
            qc.cx(g.control, g.target)
        elif g.gate in TWO_QUBIT:
            getattr(qc, g.gate.lower())(g.control, g.target)
        else:
            getattr(qc, g.gate.lower())(g.target)
    # Reference executes original SWAP directly, independently of the 3-CX encoder.
    return np.asarray(Statevector.from_instruction(qc).data, dtype=np.complex128)


def compare(actual: np.ndarray, expected: np.ndarray) -> dict:
    if actual.shape != expected.shape or not np.all(np.isfinite(actual)):
        raise ValueError('State-vector trả về sai kích thước hoặc có số không hữu hạn.')
    norm = float(np.vdot(actual, actual).real)
    ref_norm = float(np.vdot(expected, expected).real)
    error = float(np.max(np.abs(actual - expected)))
    fidelity = float(np.clip(abs(np.vdot(expected, actual)) ** 2 / (norm * ref_norm), 0, 1)) if norm > 0 else 0.0
    norm_error = abs(norm - 1.0)
    return {'max_error': error, 'fidelity': fidelity, 'norm_error': norm_error,
            'total_probability': norm, 'pass': error <= 1e-2 and fidelity >= 0.99 and norm_error <= 1e-2,
            'limits': {'max_error': 1e-2, 'fidelity_min': 0.99, 'norm_error': 1e-2}}


def state_rows(state: np.ndarray, num_qubits: int) -> list[dict]:
    return [{'index': i, 'basis': format(i, f'0{num_qubits}b'), 'real': float(z.real),
             'imag': float(z.imag), 'probability': float(abs(z) ** 2),
             'phase': float(np.angle(z)) if abs(z) > 1e-12 else None}
            for i, z in enumerate(state)]
