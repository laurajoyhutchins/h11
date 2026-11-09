"""ChunkedWriter contract oracles, independent of ChunkedReader."""
from __future__ import annotations
import unittest
from h11._events import Data, EndOfMessage
from h11._writers import ChunkedWriter
from fixtures import wire_chunk

class ChunkWriterContract(unittest.TestCase):
    def test_exact_wire_framing_and_empty_data(self) -> None:
        for size in (0, 1, 2, 3, 15, 16, 31, 255, 256):
            with self.subTest(size=size):
                body = bytes((i * 31 + 7) % 256 for i in range(size))
                written: list[bytes] = []
                writer = ChunkedWriter()
                writer(Data(data=body), written.append)
                writer(EndOfMessage(), written.append)
                self.assertEqual(b"".join(written), wire_chunk(body) + b"0\r\n\r\n")

    def test_multiple_data_events_remain_distinct_chunks(self) -> None:
        parts = [b"abc", b"", b"defg"]
        writer = ChunkedWriter()
        written: list[bytes] = []
        for part in parts:
            writer(Data(data=part), written.append)
        writer(EndOfMessage(), written.append)
        self.assertEqual(b"".join(written), b"3\r\nabc\r\n4\r\ndefg\r\n0\r\n\r\n")

    def test_trailer_encoding(self) -> None:
        writer = ChunkedWriter()
        written: list[bytes] = []
        writer(EndOfMessage(headers=[(b"X-Check", b"yes")]), written.append)
        self.assertEqual(b"".join(written), b"0\r\nX-Check: yes\r\n\r\n")
