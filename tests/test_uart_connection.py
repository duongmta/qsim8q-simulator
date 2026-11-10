"""Shared UART regression tests. All serial objects are fake; no board."""
import io
import struct
import pytest

from qsim8_backend import protocol as p
from qsim8_backend import transport

def clock(monkeypatch):
    ticks = iter(i * 0.01 for i in range(10000))
    monkeypatch.setattr(p.time, 'monotonic', lambda: next(ticks))


def test_silence_reports_zero_bytes(monkeypatch):
    clock(monkeypatch)
    with pytest.raises(TimeoutError, match='RX=0 byte'):
        p.receive(io.BytesIO(), 1, timeout=0.2)


def test_partial_magic_identifies_incomplete_header(monkeypatch):
    clock(monkeypatch)
    with pytest.raises(TimeoutError, match='RX=4 byte, đang chờ header'):
        p.receive(io.BytesIO(b'Q8PK'), 1, timeout=0.5)


def test_ascii_firmware_is_distinguishable_from_silence(monkeypatch):
    clock(monkeypatch)
    with pytest.raises(TimeoutError, match='RX=5 byte, đang chờ magic Q8PK'):
        p.receive(io.BytesIO(b'ZYBO\n'), 1, timeout=0.5)


class FakeSerial:
    def __init__(self, echo=False):
        self.is_open = True
        self.sent = []
        self.buffer = io.BytesIO()
        self.echo = echo

    def reset_input_buffer(self):
        self.buffer = io.BytesIO()

    def reset_output_buffer(self):
        pass

    def write(self, packet):
        self.sent.append(packet)
        kind, payload = p.receive(io.BytesIO(packet), 1)
        assert kind == p.HELLO and payload == b''
        assert len(packet) == 20  # The old magic-only diagnostic sent just four.
        caps = struct.pack('<HHHHI', 8, 20, 256, 16, 0x10000)
        self.buffer = io.BytesIO(packet if self.echo else p.frame(p.HELLO_REPLY, 1, caps))
        return len(packet)

    def flush(self):
        pass

    def read(self, size):
        return self.buffer.read(min(size, 3))

    def close(self):
        self.is_open = False


def test_connect_requires_complete_valid_hello_and_closes(monkeypatch):
    link = FakeSerial()
    monkeypatch.setattr(transport.serial, 'Serial', lambda **kwargs: link)
    monkeypatch.setattr(transport.time, 'sleep', lambda _: None)
    board = transport.Board()
    assert board.connect('COM14')['firmware'] == '00010000'
    assert board.status()['connected']
    assert len(link.sent) == 1
    assert board.last_exchange['request_type'] == p.HELLO
    assert board.last_exchange['response_type'] == p.HELLO_REPLY
    assert board.last_exchange['tx_frame_hex'].startswith(p.MAGIC.hex())
    assert board.last_exchange['crc_validated'] is True
    board.disconnect()
    assert not link.is_open and not board.status()['connected']


def test_uart_echo_does_not_count_as_firmware_reply(monkeypatch):
    link = FakeSerial(echo=True)
    monkeypatch.setattr(transport.serial, 'Serial', lambda **kwargs: link)
    monkeypatch.setattr(transport.time, 'sleep', lambda _: None)
    board = transport.Board()
    with pytest.raises(RuntimeError, match='HELLO'):
        board.connect('COM14')
    assert not link.is_open
    assert 'COM14' in board.status()['last_error']
    assert not board.status()['connected']
