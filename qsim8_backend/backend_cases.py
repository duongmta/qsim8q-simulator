"""QuantumCircuit versions of the established 15-case acceptance suite."""
from qiskit import QuantumCircuit

from .acceptance import cases


def acceptance_circuits(include_stress=False):
    """Keep the existing input states and operations, including native SWAP input.

    BackendV2 starts in |0...0>; basis preparation is therefore explicit X gates.
    This adds one executed X to SWAP_5Q compared with the web/UART suite.
    """
    result = []
    for name, n, basis, ops in cases():
        circuit = QuantumCircuit(n, name=name)
        for q in range(n):
            if basis & (1 << q):
                circuit.x(q)
        for op in ops:
            gate = op[0]
            if gate in {'RX', 'RY', 'RZ'}:
                getattr(circuit, gate.lower())(op[2], op[1])
            elif gate == 'CNOT':
                circuit.cx(op[1], op[2])
            elif gate in {'CZ', 'SWAP'}:
                getattr(circuit, gate.lower())(op[1], op[2])
            else:
                getattr(circuit, gate.lower())(op[1])
        circuit.metadata = {'suite': 'mandatory', 'original_initial_basis': basis,
                            'basis_preparation': 'explicit_x_gates'}
        result.append(circuit)
    if include_stress:
        # These are product-limit experiments, not additions to the mandatory 15.
        for n in (1, 8):
            circuit = QuantumCircuit(n, name=f'STRESS_DENSE_{n}Q_20L')
            for layer in range(20):
                for q in range(n):
                    if layer % 3 == 0:
                        circuit.h(q)
                    elif layer % 3 == 1:
                        circuit.t(q)
                    else:
                        circuit.rx(0.13 * (q + 1), q)
            circuit.metadata = {'suite': 'stress', 'original_initial_basis': 0,
                                'basis_preparation': 'explicit_x_gates'}
            result.append(circuit)
        circuit = QuantumCircuit(8, name='STRESS_SWAP_8Q_20L')
        for _layer in range(20):
            for q in range(0, 8, 2):
                circuit.swap(q, q + 1)
        circuit.metadata = {'suite': 'stress', 'original_initial_basis': 0,
                            'basis_preparation': 'explicit_x_gates'}
        result.append(circuit)
    return result
