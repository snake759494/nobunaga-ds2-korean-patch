# -*- coding: utf-8 -*-
"""Draw Korean banner captions into the CSK backgrounds of /bg/GrpBG.dat.

Some headers are not sprites at all: the start-menu banner and its siblings
are painted into the background image, so the sprite patcher never sees them.
Each entry in ``data/reference/bg_labels.json`` names a block, the plate
rectangle inside its frame, and the Korean to put there.

The plate is restored row by row from a clean reference column at the edge of
the frame - the Japanese sits on a soft glow that cannot be reconstructed, so
the row is flattened to the plate colour - and the Korean is then drawn in the
same light ink with a black outline, the way the original letters are drawn.

Writing happens in palette-index space and only through tiles the visible map
uses exactly once, so a caption can never leak into another part of the
screen.  The block is re-encoded into its original capacity, which keeps every
GrpBGInfo offset and the resource size untouched.
"""
from __future__ import annotations

import json
import os
import struct

from PIL import Image, ImageDraw, ImageFont

import bg_csk
import bg_patch

SCREEN_WIDTH = bg_patch.SCREEN_WIDTH
SCREEN_HEIGHT = bg_patch.SCREEN_HEIGHT
MAP_OFFSET = bg_patch.MAP_OFFSET
CHAR_OFFSET = bg_patch.CHAR_OFFSET
VISIBLE_TILES = bg_patch.VISIBLE_TILES

SIZES = (24, 12)          # Galmuri11 is only pixel exact at multiples of 12
_fonts: dict[int, ImageFont.FreeTypeFont] = {}


def font(path, size):
    key = (path, size)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(path, size)
    return _fonts[key]


def render(path, text, size):
    """bilevel glyph mask plus a one pixel outline around it"""
    f = font(path, size)
    w = f.getmask(text, mode='1').size[0]
    img = Image.new('L', (max(w, 1) + 2, size + 4), 0)
    d = ImageDraw.Draw(img)
    d.fontmode = '1'
    d.text((1, 2), text, font=f, fill=255)
    px = img.load()
    fill = {(x, y) for y in range(img.height) for x in range(img.width) if px[x, y]}
    edge = set()
    for x, y in fill:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                p = (x + dx, y + dy)
                if 0 <= p[0] < img.width and 0 <= p[1] < img.height and p not in fill:
                    edge.add(p)
    # trim to the ink so the caption centres on what is actually drawn
    xs = [p[0] for p in fill] or [0]
    ys = [p[1] for p in fill] or [0]
    return (min(xs), min(ys), max(xs), max(ys)), fill, edge


def _map_entry(payload, tx, ty):
    return struct.unpack_from('<H', payload, MAP_OFFSET + 2 * (ty * 32 + tx))[0]


def _tile_uses(payload):
    uses: dict[int, int] = {}
    for i in range(VISIBLE_TILES):
        tile = struct.unpack_from('<H', payload, MAP_OFFSET + 2 * i)[0] & 0x3FF
        uses[tile] = uses.get(tile, 0) + 1
    return uses


def _write_pixel(payload, x, y, value):
    entry = _map_entry(payload, x // 8, y // 8)
    tile = entry & 0x3FF
    sx = 7 - (x % 8) if entry & 0x400 else x % 8
    sy = 7 - (y % 8) if entry & 0x800 else y % 8
    payload[CHAR_OFFSET + tile * 64 + sy * 8 + sx] = value


def _ink_pair(palette, entry):
    """White letters and a black outline, taken from this block's own palette.

    Every block carries its own 256 colours, so a fixed index would be a
    different colour in each background.  The entries nearest pure white and
    pure black are what the original letters use too.
    """
    if 'ink' in entry and 'outline' in entry:
        return int(entry['ink']), int(entry['outline'])
    def near(target):
        return min(range(len(palette)),
                   key=lambda i: sum((palette[i][c] - target[c]) ** 2 for c in range(3)))
    return near((255, 255, 255)), near((0, 0, 0))


def patch_block(payload: bytearray, entry: dict, font_path: str):
    """Repaint one banner.  Returns a stats dict."""
    x0, y0, w, h = entry['plate']
    uses = _tile_uses(bytes(payload))
    for ty in range(y0 // 8, (y0 + h - 1) // 8 + 1):
        for tx in range(x0 // 8, (x0 + w - 1) // 8 + 1):
            tile = _map_entry(bytes(payload), tx, ty) & 0x3FF
            if uses.get(tile, 0) != 1:
                raise ValueError(
                    f'block {entry["block"]}: tile {tile} under the plate is '
                    f'used {uses.get(tile, 0)} times in the visible map')

    palette = bg_patch._palette(bytes(payload))
    pixels = bytearray(bg_patch.screen_indices(bytes(payload)))
    ref = entry.get('ref_col', x0)
    for y in range(y0, y0 + h):                      # flatten the plate
        value = pixels[y * SCREEN_WIDTH + ref]
        for x in range(x0, x0 + w):
            pixels[y * SCREEN_WIDTH + x] = value

    size = int(entry.get('size', 12))
    if size not in SIZES:
        size = 12
    (ix0, iy0, ix1, iy1), fill, edge = render(font_path, entry['kr'], size)
    tw, th = ix1 - ix0 + 1, iy1 - iy0 + 1
    if tw > w or th > h:
        raise ValueError(f'block {entry["block"]}: "{entry["kr"]}" does not fit the plate')
    ox = x0 + (w - tw) // 2 - ix0
    oy = y0 + (h - th) // 2 - iy0
    ink, outline = _ink_pair(palette, entry)
    for x, y in edge:
        X, Y = ox + x, oy + y
        if x0 <= X < x0 + w and y0 <= Y < y0 + h:
            pixels[Y * SCREEN_WIDTH + X] = outline
    for x, y in fill:
        X, Y = ox + x, oy + y
        if x0 <= X < x0 + w and y0 <= Y < y0 + h:
            pixels[Y * SCREEN_WIDTH + X] = ink

    original = bg_patch.screen_indices(bytes(payload))
    changed = 0
    for y in range(y0, y0 + h):
        for x in range(x0, x0 + w):
            value = pixels[y * SCREEN_WIDTH + x]
            if value != original[y * SCREEN_WIDTH + x]:
                changed += 1
            _write_pixel(payload, x, y, value)
    return {'block': entry['block'], 'kr': entry['kr'], 'changed_pixels': changed}


def manifest(data_dir):
    path = os.path.join(data_dir, 'reference', 'bg_labels.json')
    if not os.path.exists(path):
        return []
    return json.load(open(path, encoding='utf-8'))


def patch_banners(dat: bytes, info: bytes, data_dir: str, font_path: str):
    """Return ``(patched_dat, stats)`` for every banner in the manifest."""
    entries = manifest(data_dir)
    if not entries:
        return dat, []
    count = struct.unpack_from('<I', info, 0)[0]
    out = bytearray(dat)
    stats = []
    for entry in entries:
        block = int(entry['block'])
        if block >= count:
            raise ValueError(f'GrpBGInfo has no block {block}')
        offset, size = struct.unpack_from('<II', info, 8 + block * 8)
        payload, _ = bg_csk.decode_block(bytes(out[offset:offset + size]))
        if len(payload) < CHAR_OFFSET + VISIBLE_TILES * 64:
            raise ValueError(f'block {block} is not a 256x192 8bpp screen')
        buf = bytearray(payload)
        stat = patch_block(buf, entry, font_path)
        encoded = bg_csk.encode_block(bytes(buf), size, bytes(out[offset:offset + size]))
        out[offset:offset + size] = encoded
        stat['compressed_size'] = struct.unpack_from('<I', encoded, 8)[0]
        stat['capacity'] = size
        stats.append(stat)
    return bytes(out), stats
