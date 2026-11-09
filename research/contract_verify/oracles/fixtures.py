"""Independent wire fixture generator shared by contract oracles."""

def wire_chunk(body: bytes) -> bytes:
    if not body:
        return b""
    return format(len(body), "x").encode("ascii") + b"\r\n" + body + b"\r\n"
