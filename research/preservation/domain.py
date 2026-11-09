"""Deterministic finite corpus for an h11 chunked-writer contract experiment.

The finite input domain is an explicit boundary of the result, not a proxy
for all possible HTTP bodies, writer callbacks, or Python contexts.
"""
from __future__ import annotations

import hashlib
import json
import random


def corpus() -> list[dict]:
    sizes = (0, 1, 2, 3, 15, 16, 17, 31, 32, 63,
             64, 127, 128, 255, 256, 257, 4095, 4096)
    rng = random.Random(731237)
    cases: list[dict] = []

    def insert(parts: list[bytes], trailers: list[tuple[bytes, bytes]]) -> None:
        n = len(cases)
        cases.append({
            "id": f"trace-{n:03}",
            "payloads": [p.hex() for p in parts],
            "trailers": [[k.hex(), v.hex()] for k, v in trailers],
        })

    for size in sizes:
        payload = bytes((i * 37 + size * 11) % 256 for i in range(size))
        insert([payload], [])
        insert([b"", payload, b""], [(b"x-contract", b"yes")])
        mid = size // 2
        insert([payload[:mid], payload[mid:]],
               [(b"etag", b"verified"), (b"x-id", b"42")])
    for _ in range(54):
        lengths = [rng.randrange(0, 260) for _ in range(rng.randrange(0, 5))]
        chunks = [bytes(rng.randrange(256) for _ in range(n)) for n in lengths]
        insert(chunks, [(b"x-case", b"random")] if rng.randrange(2) else [])
    assert len(cases) == 108
    return cases


def digest(rows: object) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()
