"""Reader/writer composition tests, only run after joining both implementations."""
from __future__ import annotations
import random
import unittest
from h11._events import Data, EndOfMessage
from h11._readers import ChunkedReader
from h11._receivebuffer import ReceiveBuffer
from h11._writers import ChunkedWriter
from reader_oracles import drain_valid

class CodecCompositionContract(unittest.TestCase):
    """Composition is tested only after both independently checked codecs exist."""

    def test_writer_to_reader_roundtrip(self) -> None:
        rng = random.Random(281108)
        for size in (0, 1, 2, 3, 15, 16, 31, 127, 255, 256):
            body = rng.randbytes(size)
            for trial in range(20):
                with self.subTest(size=size, trial=trial):
                    cuts = [body[: size // 2], b"", body[size // 2 :]]
                    writer = ChunkedWriter()
                    writes: list[bytes] = []
                    for part in cuts:
                        writer(Data(data=part), writes.append)
                    writer(EndOfMessage(), writes.append)
                    buf = ReceiveBuffer()
                    buf += b"".join(writes)
                    events, end = drain_valid(ChunkedReader(), buf)
                    self.assertEqual(b"".join(bytes(e.data) for e in events), body)
                    self.assertIsNotNone(end)
