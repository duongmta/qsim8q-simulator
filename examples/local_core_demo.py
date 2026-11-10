"""Run the packaged Q2.30 C++ core through Qiskit without a board or COM port."""

from __future__ import annotations

import argparse

import numpy as np
from qiskit import QuantumCircuit, transpile
from qiskit.quantum_info import Statevector

from experiments.cd3_python_core.local_transport import LocalCoreTransport
from qsim8_backend import QSim8Backend
from qsim8_backend.circuit import compare


def make_circuit(name: str) -> QuantumCircuit:
    if name == "bell":
        circuit = QuantumCircuit(2, name="bell")
        circuit.h(0)
        circuit.cx(0, 1)
        return circuit
    circuit = QuantumCircuit(8, name="ghz8")
    circuit.h(0)
    for qubit in range(7):
        circuit.cx(qubit, qubit + 1)
    return circuit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--circuit", choices=("bell", "ghz8"), default="bell")
    args = parser.parse_args()

    circuit = make_circuit(args.circuit)
    reference = np.asarray(Statevector.from_instruction(circuit).data)
    # The port is dormant when a local transport is injected.
    with QSim8Backend(port="COM99", board=LocalCoreTransport()) as backend:
        compiled = transpile(circuit, backend=backend, optimization_level=0,
                             seed_transpiler=1729)
        result = backend.run(compiled).result()
        actual = np.asarray(result.get_statevector(compiled), dtype=np.complex128)
        source = result.results[0].metadata["qsim8"]["execution_source"]

    metrics = compare(actual, reference)
    print(f"Circuit: {args.circuit}; qubits: {circuit.num_qubits}")
    print(f"Execution source: {source}")
    print(f"Emax={metrics['max_error']:.6e}; fidelity={metrics['fidelity']:.12f}; "
          f"Enorm={metrics['norm_error']:.6e}")
    significant = [(index, complex(value)) for index, value in enumerate(actual)
                   if abs(value) > 1e-9]
    print("Nonzero amplitudes:", significant)
    print("LOCAL_CORE_DEMO=" + ("PASS" if metrics["pass"] else "FAIL"))
    return 0 if source == "injected_transport" and metrics["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
