"""Run manually with pytest. No test opens a real serial port."""
import io
import math
import struct

import numpy as np
import pytest
from pydantic import ValidationError

from qsim8_backend.circuit import Circuit, compile_circuit, compare, instruction, reference
from qsim8_backend import protocol as p


def circuit(n=2, gates=None, basis=0):
    return Circuit(num_qubits=n, initial_basis=basis, gates=gates or [])


def test_instruction_golden_bytes():
    # H q0: opcode 1, target 0, control sentinel 15, both params zero.
    assert instruction('H', 0).hex() == '010f0000000000000000000000000000'
    # CNOT control q0 -> target q1 has low word 0x1a.
    assert instruction('CNOT', 1, 0).hex() == '1a000000000000000000000000000000'
    w = int.from_bytes(instruction('RY', 7, theta=math.pi), 'little')
    assert ((w >> 44) & 0xffffffff) == 1073741824
    assert (w >> 76) == 0


def test_swap_order_and_basis():
    c = circuit(gates=[{'gate':'SWAP','layer':0,'control':0,'target':1}], basis=1)
    code, stats = compile_circuit(c)
    assert code == instruction('CNOT',1,0) + instruction('CNOT',0,1) + instruction('CNOT',1,0)
    assert stats['native_instructions'] == 3
    np.testing.assert_allclose(reference(c), [0,0,1,0], atol=1e-14)


def test_bell_and_phase():
    c = circuit(gates=[{'gate':'H','layer':0,'target':0}, {'gate':'CNOT','layer':1,'control':0,'target':1}])
    np.testing.assert_allclose(reference(c), [1/math.sqrt(2),0,0,1/math.sqrt(2)], atol=1e-14)
    phase = circuit(1, [{'gate':'H','layer':0,'target':0}, {'gate':'S','layer':1,'target':0}])
    np.testing.assert_allclose(reference(phase), [1/math.sqrt(2),1j/math.sqrt(2)], atol=1e-14)


def test_max_depth_and_swaps():
    c = circuit(8, [{'gate':'SWAP','layer':layer,'control':q,'target':q+1} for layer in range(20) for q in range(0,8,2)])
    code, summary = compile_circuit(c)
    assert len(code) == 240 * 16
    assert summary['logical_depth'] == 20


@pytest.mark.parametrize('body', [
    {'num_qubits':9}, {'num_qubits':1, 'initial_basis':2},
    {'num_qubits':1, 'gates':[{'gate':'H','target':0,'layer':20}]},
    {'num_qubits':2, 'gates':[{'gate':'CNOT','target':0,'control':0,'layer':0}]},
    {'num_qubits':1, 'gates':[{'gate':'RX','target':0,'layer':0,'theta':float('nan')}]},
    {'num_qubits':1, 'gates':[{'gate':'H','target':0,'layer':0,'theta':1}]},
    {'num_qubits':2, 'gates':[{'gate':'H','target':0,'layer':0},{'gate':'CNOT','control':0,'target':1,'layer':0}]},
])
def test_reject_bad_circuits(body):
    with pytest.raises(ValidationError):
        Circuit.model_validate(body)


class Fragmented(io.BytesIO):
    def read(self, size=-1):
        return super().read(min(size,3))


def test_crc_known_vector_and_fragmented_frames():
    import zlib
    assert zlib.crc32(b'123456789') == 0xcbf43926
    stream = Fragmented(b'boot noise\r\n' + p.frame(p.HELLO_REPLY,4,b'old') + p.frame(p.HELLO_REPLY,5,b'answer'))
    assert p.receive(stream,5) == (p.HELLO_REPLY,b'answer')


def test_corruption_rejected():
    packet=bytearray(p.frame(p.RUN_REPLY,2,b'answer')); packet[-5] ^= 1
    with pytest.raises(ValueError,match='CRC'):
        p.receive(io.BytesIO(packet),2)


def test_zero_vector_fails_even_with_good_shape():
    m=compare(np.zeros(2,dtype=complex),np.array([1,0],dtype=complex))
    assert not m['pass'] and m['fidelity'] == 0


def test_transport_decodes_real_hardware_packet(monkeypatch):
    from qsim8_backend.transport import Board
    fake=Board(); fake.info={'port':'TEST'}
    payload=struct.pack('<HHIQiiii',1,2,1000000,25,0,0,1073741824,0)
    monkeypatch.setattr(fake,'_exchange',lambda *args:(p.RUN_REPLY,payload))
    actual,timing,info=fake.run(1,0,instruction('X',0))
    np.testing.assert_allclose(actual,[0,1])
    assert timing['accelerator_call_us']==25 and info['port']=='TEST'
