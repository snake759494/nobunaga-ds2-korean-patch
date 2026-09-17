# -*- coding: utf-8 -*-
"""Cell label tools: render cells, locate the text region inside a cell,
and redraw it with Korean text written back into the NCGR tile data."""
import struct, os, sys, json
from PIL import Image, ImageFont, ImageDraw
import nitro_gfx as ng
import ncer
import os as _os, sys as _sys
_sys.path[:0] = [_os.path.dirname(_os.path.abspath(__file__)),
                _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..')]
from nobu2_paths import ROM_IN, ROM_OUT, WORK, FONT, DATA

BOUNDARY = 4   # mappingMode 2 => 128-byte boundary => 4 tiles per index step (4bpp)

def tile_boundary(info, boundary=None):
    """Tiles per OAM tile-index step.  mappingMode 2 is a 128-byte boundary:
    four 32-byte tiles at 4bpp, but only two 64-byte tiles at 8bpp.  The 256
    colour sheets were read with the 4bpp step for a long time, which sent
    every cell after the first to the wrong picture."""
    if boundary is not None: return boundary
    return 2 if info.get('bpp') == 8 else BOUNDARY

def pal_index(info, palbank, v):
    """NCLR entry for a pixel value: 16-entry banks at 4bpp, 256 at 8bpp."""
    return palbank*(256 if info.get('bpp') == 8 else 16) + v

def cell_pixels(info, bank_idx, boundary=None):
    """return (W, H, grid[y][x] = (tile, k, palbank) source location, values)"""
    boundary = tile_boundary(info, boundary)
    bk = info['ncer']['banks'][bank_idx]
    sp = bk['sprites']
    if not sp: return None
    x0 = min(s['x'] for s in sp); y0 = min(s['y'] for s in sp)
    x1 = max(s['x']+s['w'] for s in sp); y1 = max(s['y']+s['h'] for s in sp)
    W, H = x1-x0, y1-y0
    if W <= 0 or H <= 0 or W > 512 or H > 512: return None
    src = [[None]*W for _ in range(H)]
    vals = info['vals']
    for s in reversed(sp):
        tw, th = s['w']//8, s['h']//8
        base = s['tile']*boundary
        palbank = s.get('pal', 0)
        for ty in range(th):
            for tx in range(tw):
                t = base + ty*tw + tx
                if (t+1)*64 > len(vals): continue
                for k in range(64):
                    X = s['x']-x0 + tx*8 + (k % 8)
                    Y = s['y']-y0 + ty*8 + (k // 8)
                    if 0 <= X < W and 0 <= Y < H:
                        src[Y][X] = (t, k, palbank)
    return W, H, src

def cell_image(info, bank_idx, scale=3, boundary=None):
    r = cell_pixels(info, bank_idx, boundary)
    if r is None: return None
    W, H, src = r
    vals, pal = info['vals'], info['pal']
    img = Image.new('RGB', (W, H), (255, 0, 255))
    px = img.load()
    for y in range(H):
        for x in range(W):
            s = src[y][x]
            if s is None: continue
            v = vals[s[0]*64 + s[1]]
            palbank = s[2] if len(s) > 2 else 0
            pi = pal_index(info, palbank, v)
            px[x, y] = pal[pi] if pal and pi < len(pal) else ((v*16,)*3)
    return img.resize((W*scale, H*scale), Image.NEAREST)

def color_hist(info, bank_idx, boundary=None):
    r = cell_pixels(info, bank_idx, boundary)
    if r is None: return {}
    W, H, src = r
    vals = info['vals']
    hist = {}
    for y in range(H):
        for x in range(W):
            s = src[y][x]
            if s is None: continue
            v = vals[s[0]*64 + s[1]]
            hist[v] = hist.get(v, 0) + 1
    return hist

def redraw_cell_text(info, bank_idx, text, box, ink, bg,
                     font_path=FONT, font_size=12,
                     boundary=None):
    """Clear `box` (x,y,w,h) to `bg` and draw `text` in `ink` inside the cell,
    writing results back into info['vals'] (the NCGR pixel array)."""
    r = cell_pixels(info, bank_idx, boundary)
    if r is None: return False
    W, H, src = r
    bx, by, bw, bh = box
    img = Image.new('L', (bw, bh), 255)
    f = ImageFont.truetype(font_path, font_size)
    d = ImageDraw.Draw(img)
    tw = d.textlength(text, font=f)
    d.text((max(0, (bw - tw)//2), max(0, (bh - font_size)//2 - 1)), text, font=f, fill=0)
    ipx = img.load()
    vals = info['vals']
    for y in range(bh):
        for x in range(bw):
            X, Y = bx + x, by + y
            if not (0 <= X < W and 0 <= Y < H): continue
            s = src[Y][X]
            if s is None: continue
            vals[s[0]*64 + s[1]] = ink if ipx[x, y] < 128 else bg
    return True

def save_ncgr(info, path_in, path_out):
    """re-pack info['vals'] into the NCGR pixel block and write the .dat"""
    d = bytearray(open(path_in, 'rb').read())
    subs = ng.find_subs(bytes(d))
    for s in subs:
        if s['type'] != 'NCGR': continue
        for b in ng.blocks_of(bytes(d), s):
            if b['name'] not in ('CHAR', 'RAHC'): continue
            o = b['off']
            depth = struct.unpack_from('<I', d, o+12)[0]
            datsz = struct.unpack_from('<I', d, o+24)[0]
            datoff = struct.unpack_from('<I', d, o+28)[0]
            start = o + 8 + datoff
            vals = info['vals']
            if depth == 3:   # 4bpp
                out = bytearray(datsz)
                for i in range(datsz):
                    lo = vals[i*2] & 0xF
                    hi = vals[i*2+1] & 0xF
                    out[i] = lo | (hi << 4)
            else:
                out = bytearray(vals[:datsz])
            d[start:start+datsz] = out
            open(path_out, 'wb').write(bytes(d))
            return True
    return False

if __name__ == '__main__':
    p = _os.path.join(WORK, 'fs', 'obj', 'SenryakuMainShita.dat')
    OUT = r'C:\Users\Jay\AppData\Local\Temp\claude\D--nds-roms-NOBU2\9265263d-585d-4b0c-acac-1cfa176f7263\scratchpad\gfx\cells'
    info = ncer.load(p)
    print('cell 0 palette histogram:', sorted(color_hist(info, 0).items(), key=lambda kv: -kv[1])[:6])
    im = cell_image(info, 0, scale=4)
    im.save(f'{OUT}\\cell0_before.png')
    print('cell0 size:', im.width//4, 'x', im.height//4)
