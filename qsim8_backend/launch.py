"""Check that the local QSim8Q simulator's Python dependencies are usable."""

import argparse
import importlib.metadata
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-env', action='store_true')
    args = parser.parse_args(argv)
    if not args.check_env:
        parser.error('Use --check-env, RunLocalDemo.cmd or RunLocalValidation.cmd.')

    import numpy as np
    from qiskit import QuantumCircuit
    from qiskit.quantum_info import Statevector
    from . import QSim8Backend

    if int(np.__version__.split('.')[0]) < 2:
        raise RuntimeError('QSim8Q requires NumPy 2.x with this Qiskit version.')
    probe = QuantumCircuit(1)
    probe.h(0)
    Statevector.from_instruction(probe)
    print('PYTHON:', sys.executable)
    print('PACKAGE_ROOT:', ROOT)
    for package in ('qiskit', 'qiskit-aer', 'numpy', 'pydantic', 'pyserial'):
        print(package, importlib.metadata.version(package))
    print('BACKEND:', QSim8Backend().name)
    print('BACKEND_ENV_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
