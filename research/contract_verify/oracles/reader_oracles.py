"""ChunkedReader contract oracles, independent of ChunkedWriter."""
from __future__ import annotations
import random
import unittest
from h11._events import Data, EndOfMessage
from h11._readers import ChunkedReader
from h11._receivebuffer import ReceiveBuffer
from h11._util import LocalProtocolError, RemoteProtocolError
from fixtures import wire_chunk

def drain(reader: ChunkedReader, buf: ReceiveBuffer) -> tuple[list[Data], EndOfMessage | None]:
    parts: list[Data] = []
    for _ in range(4096):
        result = reader(buf)
        if result is None:
            return parts, None
        if isinstance(result, Data):
            parts.append(result)
            continue
        if isinstance(result, EndOfMessage):
            return parts, result
        raise AssertionError(f"Unexpected reader event: {result!r}")
    raise AssertionError("Reader exceeded bounded event budget")

def drain_valid(reader: ChunkedReader, buf: ReceiveBuffer) -> tuple[list[Data], EndOfMessage | None]:
    """A rejected valid wire vector is a contract assertion, not a harness error."""
    try:
        return drain(reader, buf)
    except LocalProtocolError as exc:
        raise AssertionError(f"Valid chunked wire rejected: {exc}") from exc


class ChunkReaderContract(unittest.TestCase):
    def test_chunk_sizes_and_exact_payload(self) -> None:
        for size in (1, 2, 3, 15, 16, 31, 255, 256):
            with self.subTest(size=size):
                body = bytes((i * 67 + 11) % 256 for i in range(size))
                buf = ReceiveBuffer()
                buf += wire_chunk(body) + b"0\r\n\r\n"
                events, end = drain_valid(ChunkedReader(), buf)
                self.assertEqual(b"".join(bytes(e.data) for e in events), body)
                self.assertIsNotNone(end)
                self.assertEqual(end.headers, [])
                self.assertEqual(len(events), 1)
                self.assertTrue(events[0].chunk_start and events[0].chunk_end)

    def test_chunked_input_fragmentation_invariance(self) -> None:
        rng = random.Random(260108)
        for size in (1, 3, 16, 31, 255):
            body = rng.randbytes(size)
            wire = wire_chunk(body) + b"0\r\n\r\n"
            for trial in range(30):
                with self.subTest(size=size, trial=trial):
                    reader = ChunkedReader()
                    buf = ReceiveBuffer()
                    offset = 0
                    data: list[bytes] = []
                    got_eom = None
                    while offset < len(wire):
                        step = rng.randint(1, min(7, len(wire) - offset))
                        buf += wire[offset : offset + step]
                        offset += step
                        parts, end = drain_valid(reader, buf)
                        data.extend(bytes(p.data) for p in parts)
                        if end is not None:
                            self.assertIsNone(got_eom)
                            got_eom = end
                    self.assertEqual(b"".join(data), body)
                    self.assertIsNotNone(got_eom)

    def test_zero_chunk_and_trailers(self) -> None:
        buf = ReceiveBuffer()
        buf += b"0\r\nX-Check: yes\r\n\r\n"
        parts, end = drain_valid(ChunkedReader(), buf)
        self.assertEqual(parts, [])
        self.assertIsNotNone(end)
        self.assertEqual(list(end.headers), [(b"x-check", b"yes")])

    def test_invalid_chunk_header_and_footer_are_rejected(self) -> None:
        for wire in (b"z\r\nabc\r\n", b"3\r\nabcXX0\r\n\r\n"):
            with self.subTest(wire=wire):
                buf = ReceiveBuffer()
                buf += wire
                with self.assertRaises(LocalProtocolError):
                    drain(ChunkedReader(), buf)

    def test_premature_eof_is_rejected(self) -> None:
        with self.assertRaises(RemoteProtocolError):
            ChunkedReader().read_eof()
