"""Bounded chunked-codec composition tests against the checked-out h11 package."""
from __future__ import annotations

import pytest
from h11 import Data, EndOfMessage
from h11._readers import ChunkedReader
from h11._receivebuffer import ReceiveBuffer
from h11._util import LocalProtocolError
from h11._writers import ChunkedWriter

SEGMENTS = (1, 2, 3, 7, 64, 1024)
FIXTURES = (
    ((), ()),
    ((b"a",), ()),
    ((b"abc", b"", b"defghi"), ((b"x-note", b"done"),)),
    ((b"\x00\r\n\xff", b"Z" * 100), ((b"etag", b"xyz"), (b"x-k", b"v"))),
)
SUFFIX = b"GET /next HTTP/1.1\r\nHost: example.com\r\n\r\n"


def encode(payloads: tuple[bytes, ...],
           trailers: tuple[tuple[bytes, bytes], ...]) -> bytes:
    writer = ChunkedWriter()
    out: list[bytes] = []
    for payload in payloads:
        writer(Data(data=payload), out.append)
    writer(EndOfMessage(headers=list(trailers)), out.append)
    return b"".join(out)


def decode(raw: bytes, segment: int) -> tuple[bytes, list[tuple[bytes, bytes]], bytes]:
    reader = ChunkedReader()
    buffer = ReceiveBuffer()
    observed: list[bytes] = []
    for offset in range(0, len(raw), segment):
        buffer += raw[offset:offset + segment]
        while True:
            event = reader(buffer)
            if event is None:
                break
            if isinstance(event, Data):
                observed.append(bytes(event.data))
            elif isinstance(event, EndOfMessage):
                # Include buffered bytes and transport bytes not yet delivered.
                suffix = bytes(buffer) + raw[offset + segment:]
                return b"".join(observed), list(event.headers), suffix
            else:
                raise AssertionError("unexpected event")
    raise AssertionError("valid message failed to terminate")


@pytest.mark.parametrize("segment", SEGMENTS)
@pytest.mark.parametrize("fixture", FIXTURES, ids=["empty", "single", "trailers", "binary"])
def test_codec_composition_preserves_payload_trailers_and_suffix(
    segment: int, fixture: tuple[tuple[bytes, ...], tuple[tuple[bytes, bytes], ...]]
) -> None:
    payloads, trailers = fixture
    body, parsed, suffix = decode(encode(payloads, trailers) + SUFFIX, segment)
    assert body == b"".join(payloads)
    assert parsed == list(trailers)
    assert suffix == SUFFIX


@pytest.mark.parametrize("segment", SEGMENTS)
def test_corrupt_chunk_footer_rejected(segment: int) -> None:
    wire = b"1\r\nxZZ0\r\n\r\n"
    with pytest.raises(LocalProtocolError):
        decode(wire, segment)
