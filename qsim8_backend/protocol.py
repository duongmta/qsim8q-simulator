"""Q8PK v1: explicit little-endian fields and CRC32/ISO-HDLC."""
import struct
import time
import zlib

MAGIC = b'Q8PK'
VERSION = 1
HELLO, RUN, HELLO_REPLY, RUN_REPLY, ERROR = 1, 2, 0x81, 0x82, 0xff
HEADER = struct.Struct('<4sBBHII')  # magic, version, type, reserved, id, payload bytes
MAX_PAYLOAD = 4100


def frame(kind: int, request_id: int, payload: bytes = b'') -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise ValueError('Payload too large')
    header = HEADER.pack(MAGIC, VERSION, kind, 0, request_id, len(payload))
    return header + payload + struct.pack('<I', zlib.crc32(header[4:] + payload))


def read_exact(stream, size: int, deadline: float, trace=None) -> bytes:
    out = bytearray()
    while len(out) < size:
        if time.monotonic() >= deadline:
            raise TimeoutError('Hết thời gian nhận UART.')
        chunk = stream.read(size - len(out))
        if trace is not None:
            trace['bytes'] += len(chunk)
            trace['prefix'].extend(chunk[:max(0, 32 - len(trace['prefix']))])
        out.extend(chunk)
    return bytes(out)


def receive(stream, request_id: int, timeout: float = 12) -> tuple[int, bytes]:
    deadline = time.monotonic() + timeout
    trace = {'bytes': 0, 'prefix': bytearray()}
    phase = 'magic Q8PK'

    def read(size):
        try:
            return read_exact(stream, size, deadline, trace)
        except TimeoutError as exc:
            if trace['bytes'] == 0:
                detail = ('RX=0 byte: COM đã mở nhưng chưa nhận byte trả lời. '
                          'Kiểm tra đúng COM, ARM đã tới UART_READY và đang chạy.')
            else:
                detail = (f"RX={trace['bytes']} byte, đang chờ {phase}; "
                          f"32 byte đầu (hex): {trace['prefix'].hex(' ')}. "
                          'Kiểm tra đúng firmware QSim8Q, baud 115200 và bỏ breakpoint UART.')
            raise TimeoutError(f'UART timeout ({timeout:g}s). {detail}') from exc

    while time.monotonic() < deadline:
        phase = 'magic Q8PK'
        window = b''
        while window != MAGIC:
            window = (window + read(1))[-4:]
        phase = 'header'
        tail = read(HEADER.size - 4)
        magic, version, kind, reserved, rid, size = HEADER.unpack(MAGIC + tail)
        if version != VERSION or reserved or size > MAX_PAYLOAD:
            raise ValueError('Header UART không đúng Q8PK v1.')
        phase = f'payload {size} byte'
        payload = read(size)
        phase = 'CRC'
        crc, = struct.unpack('<I', read(4))
        if zlib.crc32(tail + payload) != crc:
            raise ValueError('CRC UART không khớp. Không sử dụng kết quả này.')
        if rid != request_id:
            continue  # Ignore a delayed response from an earlier request.
        if kind == ERROR:
            code = struct.unpack_from('<I', payload)[0] if len(payload) >= 4 else 0
            message = payload[4:].decode('ascii', errors='replace')
            raise RuntimeError(f'Firmware error {code}: {message}')
        return kind, payload
    raise TimeoutError('Không nhận được phản hồi khớp request ID.')
