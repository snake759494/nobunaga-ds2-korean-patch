# -*- coding: utf-8 -*-
"""Reader/writer for the CSK blocks used by /bg/GrpBG.dat.

The resource starts with a 16-byte CSK header.  The first little-endian word
is the decompressed size and the stream starts at offset 0x10.  Commands are
the same two-byte LZ form used by the ARM9 routine at 0x020853ec:

* a control byte below 0xc0 is a backwards copy;
* a control byte at or above 0xc0 is a literal run.

This module deliberately keeps each block at its original Info-table size.
That lets the ROM assembler patch one background without moving any FAT entry.
It is also used by the static verifier, so a future edit cannot silently ship
an archive that the game's decoder would read differently.
"""
from __future__ import annotations

import struct


HEADER_SIZE = 0x10
COPY_CONTROL_LIMIT = 0xC0
MAX_DISTANCE = 0x1800       # the control byte must remain below 0xc0
MAX_COPY = 0x100 + 10 - 1   # extended length: extra byte + 10
MAX_LITERAL = 64             # 0xfe is the 63-byte extended form; 0xff is 64


def decode_block(block: bytes) -> tuple[bytes, int]:
    """Return ``(decoded_payload, stream_end)`` for one compressed block."""
    if len(block) < HEADER_SIZE:
        raise ValueError("CSK block is shorter than its header")
    target = struct.unpack_from("<I", block, 0)[0]
    out = bytearray()
    p = HEADER_SIZE
    while len(out) < target:
        if p >= len(block):
            raise ValueError("CSK stream ends before its output size")
        control = block[p]
        p += 1
        if control < COPY_CONTROL_LIMIT:
            if p >= len(block):
                raise ValueError("truncated CSK copy command")
            low = block[p]
            p += 1
            word = (control << 8) | low
            # ARM's ``and ..., ..., word, asr #3`` keeps the 13 bits *after*
            # the shift; masking before shifting would silently throw away
            # the high distance bits and only works for unusually short runs.
            distance = ((word >> 3) & 0x1FFF) + 1
            length = (low & 7) + 3
            if length == 10:
                if p >= len(block):
                    raise ValueError("truncated CSK extended copy")
                length = block[p] + 10
                p += 1
            if distance > len(out):
                raise ValueError("CSK copy points before output")
            source = len(out) - distance
            if len(out) + length > target:
                raise ValueError("CSK copy exceeds output size")
            for _ in range(length):
                out.append(out[source])
                source += 1
        else:
            length = (control & 0x3F) + 1
            if length == 0x3F:
                if p >= len(block):
                    raise ValueError("truncated CSK extended literal")
                length = block[p] + 0x3F
                p += 1
            if len(out) + length > target or p + length > len(block):
                raise ValueError("CSK literal exceeds output size")
            out.extend(block[p:p + length])
            p += length
    return bytes(out), p


def _best_match(data: bytes, pos: int, chains: dict[bytes, list[int]]) -> tuple[int, int]:
    """Find a usable match using a bounded hash chain of three-byte keys."""
    if pos + 3 > len(data):
        return 0, 0
    key = data[pos:pos + 3]
    best_len = 0
    best_dist = 0
    # Old candidates are less useful than recent candidates and make the
    # encoder quadratic on the large background blocks.  A small bounded tail
    # is enough to preserve the original archive's compression ratio.
    for candidate in reversed(chains.get(key, ())[-32:]):
        distance = pos - candidate
        if distance <= 0:
            continue
        if distance > MAX_DISTANCE:
            break
        limit = min(MAX_COPY, len(data) - pos)
        n = 3
        while n < limit and data[pos + n] == data[candidate + n]:
            n += 1
        if n > best_len:
            best_len, best_dist = n, distance
            if n == limit:
                break
    return best_len, best_dist


def encode_stream(data: bytes) -> bytes:
    """Encode a payload with the CSK command grammar."""
    result = bytearray()
    chains: dict[bytes, list[int]] = {}
    pos = 0
    literal_start = 0

    def add_position(at: int) -> None:
        if at + 3 <= len(data):
            key = data[at:at + 3]
            bucket = chains.setdefault(key, [])
            bucket.append(at)
            if len(bucket) > 64:
                del bucket[:-64]

    def emit_literals(start: int, end: int) -> None:
        at = start
        while at < end:
            length = min(MAX_LITERAL, end - at)
            if length == 63:
                result.extend((0xFE, 0))
            elif length < 63:
                result.append(0xC0 + length - 1)
            else:
                result.append(0xFF)
            result.extend(data[at:at + length])
            at += length

    while pos < len(data):
        length, distance = _best_match(data, pos, chains)
        if length < 3:
            add_position(pos)
            pos += 1
            continue

        emit_literals(literal_start, pos)
        length_code = length - 3 if length < 10 else 7
        word = ((distance - 1) << 3) | length_code
        result.extend(((word >> 8) & 0xFF, word & 0xFF))
        if length >= 10:
            result.append(length - 10)
        for at in range(pos, pos + length):
            add_position(at)
        pos += length
        literal_start = pos

    emit_literals(literal_start, len(data))
    return bytes(result)


def encode_block(payload: bytes, capacity: int, template: bytes) -> bytes:
    """Re-encode one payload into a fixed-size block.

    ``template`` supplies the non-stream header fields and the padding shape.
    The stream-end field at +8 is updated because the ARM9 loader uses it as a
    useful consistency marker even though the decompression loop itself only
    needs the output-size word.
    """
    stream = encode_stream(payload)
    if HEADER_SIZE + len(stream) > capacity:
        raise ValueError(
            f"CSK block grew from {capacity} bytes to {HEADER_SIZE + len(stream)}"
        )
    out = bytearray(template[:capacity])
    if len(out) != capacity:
        raise ValueError("CSK template size does not match Info table")
    struct.pack_into("<I", out, 0, len(payload))
    struct.pack_into("<I", out, 8, HEADER_SIZE + len(stream))
    out[HEADER_SIZE:] = b"\0" * (capacity - HEADER_SIZE)
    out[HEADER_SIZE:HEADER_SIZE + len(stream)] = stream
    return bytes(out)


def archive_blocks(dat: bytes, info: bytes):
    """Yield ``(index, offset, size, compressed, decoded)`` for an archive."""
    count = struct.unpack_from("<I", info, 0)[0]
    for index in range(count):
        offset, size = struct.unpack_from("<II", info, 8 + index * 8)
        block = dat[offset:offset + size]
        payload, stream_end = decode_block(block)
        yield index, offset, size, block, payload
