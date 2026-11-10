"""Direct Qiskit BackendV2 and UART transport for QSim8Q Zybo."""

__all__ = ['QSim8Backend']


def __getattr__(name):
    """Keep the public BackendV2 import lazy for tools that only need protocol code."""
    if name == 'QSim8Backend':
        from .qiskit_backend import QSim8Backend
        return QSim8Backend
    raise AttributeError(name)
