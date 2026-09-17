# -*- coding: utf-8 -*-
"""Compact before/after showcase strips for the release notes.

Unlike make_preview.py (which dumps every changed cell, one sheet per file),
this renders a hand-picked set of cells into a few wide, readable panels that
can be embedded straight into a GitHub release body.

Usage: python make_showcase.py <picks.json> <outdir>

picks.json: [{"title": "전략 메뉴", "slug": "menu",
              "cells": [["SenryakuMainShita", 0], ...]}, ...]
"""
import os, sys, json
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ncer
import label_tools as lt
import os as _os, sys as _sys
_sys.path[:0] = [_os.path.dirname(_os.path.abspath(__file__)),
                _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..')]
from nobu2_paths import ROM_IN, ROM_OUT, WORK, FONT, DATA

SCALE = 3
GAP = 10
PAD = 14
BG = (22, 22, 26)
FG = (232, 232, 236)
DIM = (150, 150, 158)
ACC = (150, 235, 160)
ARROW = (120, 120, 130)
UI_FONT = FONT

_cache = {}
def load(name, patched):
    key = (name, patched)
    if key not in _cache:
        d = 'fs_gfx' if patched else 'fs'
        _cache[key] = ncer.load(os.path.join(WORK, d, 'obj', name + '.dat'))
    return _cache[key]

def font(size):
    return ImageFont.truetype(UI_FONT, size)

def cell_rgba(info, idx, scale=SCALE):
    """like label_tools.cell_image, but palette index 0 stays TRANSPARENT.
    The dump tools paint it magenta so it is visible; in a release note that
    just looks broken, so composite it over the page background instead."""
    r = lt.cell_pixels(info, idx)
    if r is None: return None
    W, H, src = r
    vals, pal = info['vals'], info['pal']
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    px = img.load()
    for y in range(H):
        for x in range(W):
            s = src[y][x]
            if s is None: continue
            v = vals[s[0]*64 + s[1]]
            if v == 0: continue
            pi = lt.pal_index(info, s[2] if len(s) > 2 else 0, v)
            c = pal[pi] if pal and pi < len(pal) else ((v*16,)*3)
            px[x, y] = (c[0], c[1], c[2], 255)
    return img.resize((W*scale, H*scale), Image.NEAREST)

def flatten(im):
    bg = Image.new('RGB', im.size, BG)
    bg.paste(im, (0, 0), im)
    return bg

def panel(title, cells):
    """one horizontal band: title, then before -> after pairs laid out in rows"""
    pairs = []
    for name, idx in cells:
        a = cell_rgba(load(name, False), idx)
        b = cell_rgba(load(name, True), idx)
        if a and b:
            pairs.append((flatten(a), flatten(b)))
    if not pairs:
        return None
    aw = max(p[0].width for p in pairs)
    bw = max(p[1].width for p in pairs)
    rh = max(max(p[0].height, p[1].height) for p in pairs)
    unit_w = aw + 26 + bw
    cols = 1 if unit_w > 520 else 2
    rows = (len(pairs) + cols - 1) // cols
    W = PAD*2 + cols*unit_w + (cols - 1)*40
    H = PAD*2 + 26 + rows*(rh + GAP)
    img = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((PAD, PAD - 2), title, font=font(16), fill=ACC)
    for i, (a, b) in enumerate(pairs):
        c, r = i % cols, i // cols
        x = PAD + c*(unit_w + 40)
        y = PAD + 26 + r*(rh + GAP)
        img.paste(a, (x + (aw - a.width)//2, y + (rh - a.height)//2))
        d.text((x + aw + 8, y + rh//2 - 8), '\u2192', font=font(16), fill=ARROW)
        img.paste(b, (x + aw + 26 + (bw - b.width)//2, y + (rh - b.height)//2))
    return img

def main(picks_path, outdir):
    picks = json.load(open(picks_path, encoding='utf-8'))
    os.makedirs(outdir, exist_ok=True)
    made = []
    for p in picks:
        im = panel(p['title'], [tuple(c) for c in p['cells']])
        if im is None:
            print('  skip', p['slug']); continue
        out = os.path.join(outdir, f"showcase_{p['slug']}.png")
        im.save(out)
        made.append(out)
        print(f"  {p['slug']}: {im.size[0]}x{im.size[1]}  {os.path.getsize(out)} B")
    print('panels:', len(made))

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
