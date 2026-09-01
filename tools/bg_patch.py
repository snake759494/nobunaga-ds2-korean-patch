# -*- coding: utf-8 -*-
"""Apply the static title-screen background fix from issue #4.

The lower title screen is GrpBG block 123.  It is an 8bpp, 256x192 CSK
background whose tile map uses each of its 768 visible tiles once.  The clean
reference supplied with the issue is quantised to that block's existing
palette and written back into the tile pixels; the palette, map, dimensions,
and all other GrpBG blocks remain unchanged.
"""
from __future__ import annotations

import struct
from pathlib import Path

from PIL import Image

import bg_csk


TITLE_BOTTOM_BLOCK = 123
SCREEN_WIDTH = 256
SCREEN_HEIGHT = 192
PALETTE_OFFSET = 0x80
MAP_OFFSET = 0x280
CHAR_OFFSET = 0xA80
VISIBLE_TILES = (SCREEN_WIDTH // 8) * (SCREEN_HEIGHT // 8)


def _palette(payload: bytes) -> list[tuple[int, int, int]]:
    return [
        (
            (value & 0x1F) * 255 // 31,
            ((value >> 5) & 0x1F) * 255 // 31,
            ((value >> 10) & 0x1F) * 255 // 31,
        )
        for value in struct.unpack_from("<256H", payload, PALETTE_OFFSET)
    ]


def _reference_rows(path: str | Path) -> list[list[tuple[int, int, int]]]:
    image = Image.open(path).convert("RGB")
    if image.size != (SCREEN_WIDTH, SCREEN_HEIGHT):
        image = image.resize((SCREEN_WIDTH, SCREEN_HEIGHT), Image.Resampling.BOX)
    pixels = list(image.getdata())
    return [pixels[y * SCREEN_WIDTH:(y + 1) * SCREEN_WIDTH]
            for y in range(SCREEN_HEIGHT)]


def quantise_reference(payload: bytes, path: str | Path) -> bytes:
    """Return one palette index per reference pixel using RGB555 distance."""
    palette = _palette(payload)
    rows = _reference_rows(path)
    result = bytearray(SCREEN_WIDTH * SCREEN_HEIGHT)
    for y, row in enumerate(rows):
        for x, colour in enumerate(row):
            result[y * SCREEN_WIDTH + x] = min(
                range(len(palette)),
                key=lambda i: sum((palette[i][c] - colour[c]) ** 2
                                  for c in range(3)),
            )
    return bytes(result)


def screen_indices(payload: bytes) -> bytes:
    """Render the visible 32x24 tile map as palette indices."""
    pixels = bytearray(SCREEN_WIDTH * SCREEN_HEIGHT)
    for ty in range(SCREEN_HEIGHT // 8):
        for tx in range(SCREEN_WIDTH // 8):
            entry = struct.unpack_from(
                "<H", payload, MAP_OFFSET + 2 * (ty * 32 + tx)
            )[0]
            tile = entry & 0x3FF
            flip_x = bool(entry & 0x400)
            flip_y = bool(entry & 0x800)
            source = CHAR_OFFSET + tile * 64
            for y in range(8):
                source_y = 7 - y if flip_y else y
                for x in range(8):
                    source_x = 7 - x if flip_x else x
                    pixels[(ty * 8 + y) * SCREEN_WIDTH + tx * 8 + x] = \
                        payload[source + source_y * 8 + source_x]
    return bytes(pixels)


def _visible_tile_ids(payload: bytes) -> list[int]:
    return [
        struct.unpack_from("<H", payload, MAP_OFFSET + 2 * i)[0] & 0x3FF
        for i in range(VISIBLE_TILES)
    ]


def patch_title_bottom(dat: bytes, info: bytes, reference: str | Path):
    """Return ``(patched_dat, stats)`` for the title bottom background."""
    count = struct.unpack_from("<I", info, 0)[0]
    if TITLE_BOTTOM_BLOCK >= count:
        raise ValueError("GrpBGInfo has no title bottom block 123")
    block_offset, block_size = struct.unpack_from(
        "<II", info, 8 + TITLE_BOTTOM_BLOCK * 8
    )
    block = dat[block_offset:block_offset + block_size]
    payload, _ = bg_csk.decode_block(block)
    if len(payload) < CHAR_OFFSET + VISIBLE_TILES * 64:
        raise ValueError("title bottom CSK payload is not a 256x192 8bpp screen")
    tile_ids = _visible_tile_ids(payload)
    if tile_ids != list(range(VISIBLE_TILES)):
        raise ValueError("title bottom visible map is not one-to-one")

    target = quantise_reference(payload, reference)
    new_payload = bytearray(payload)
    for ty in range(SCREEN_HEIGHT // 8):
        for tx in range(SCREEN_WIDTH // 8):
            entry = struct.unpack_from(
                "<H", payload, MAP_OFFSET + 2 * (ty * 32 + tx)
            )[0]
            tile = entry & 0x3FF
            flip_x = bool(entry & 0x400)
            flip_y = bool(entry & 0x800)
            destination = CHAR_OFFSET + tile * 64
            for y in range(8):
                source_y = 7 - y if flip_y else y
                for x in range(8):
                    source_x = 7 - x if flip_x else x
                    new_payload[destination + source_y * 8 + source_x] = \
                        target[(ty * 8 + y) * SCREEN_WIDTH + tx * 8 + x]

    patched_block = bg_csk.encode_block(bytes(new_payload), block_size, block)
    patched_dat = bytearray(dat)
    patched_dat[block_offset:block_offset + block_size] = patched_block
    return bytes(patched_dat), {
        "block": TITLE_BOTTOM_BLOCK,
        "offset": block_offset,
        "size": block_size,
        "changed_payload_bytes": sum(a != b for a, b in zip(payload, new_payload)),
        "compressed_size": struct.unpack_from("<I", patched_block, 8)[0],
    }
