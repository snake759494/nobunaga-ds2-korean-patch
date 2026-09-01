# -*- coding: utf-8 -*-
"""Draw a Korean subtitle ON TOP of a sprite cell, leaving the artwork intact.

Some menus are pictures with the Japanese baked into them - a brush-and-scroll
icon captioned 作成, an emblem reading 中断データ, a cherry-blossom disc with a
big 春.  Erasing the text there destroys the picture, because the letters and
the drawing share the same colours and often the same tiles.

So instead of erasing, this overlays the Korean the way a subtitle works:
white fill with a black outline, laid over the original caption.  The art
stays; the Korean is readable against anything behind it.

Usage: python overlay_labels.py <dat-in> <labels.json> <dat-out>
"""
import os, sys, json, collections
from PIL import Image, ImageFont, ImageDraw
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from nobu2_paths import FONT
import ncer
import label_tools as lt

SIZES = (24, 12)          # Galmuri11 is only pixel-exact at multiples of 12
MIN_COL = 7               # narrower than this per syllable and it is unreadable
MIN_COVER = 0.45          # subtitle must span at least this much of the cell
MIN_RATIO = 0.6           # Korean length vs the Japanese it has to cover
_fonts = {}

def font(size):
    if size not in _fonts:
        _fonts[size] = ImageFont.truetype(FONT, size)
    return _fonts[size]

def measure(text, size):
    return font(size).getmask(text, mode='1').size[0]

def lum(rgb):
    r, g, b = rgb
    return 0.30*r + 0.59*g + 0.11*b

def palette_ink(info, src, W, H):
    """The palette entries closest to white and to black, chosen from the
    colours this cell actually uses.  The palette is indexed exactly the way
    label_tools renders it, so 4bpp banks and 256-colour sheets both work."""
    pal, vals = info['pal'], info['vals']
    if not pal: return None
    seen = {}
    for y in range(H):
        for x in range(W):
            s = src[y][x]
            if s is None: continue
            v = vals[s[0]*64 + s[1]]
            if v == 0: continue                     # transparent
            pi = (s[2] if len(s) > 2 else 0)*16 + v
            if pi < len(pal): seen.setdefault(v, pal[pi])
    if len(seen) < 2: return None
    white = max(seen.items(), key=lambda kv: lum(kv[1]))[0]
    black = min(seen.items(), key=lambda kv: lum(kv[1]))[0]
    # a dimmed variant of a button has no colour bright enough to read as
    # white, and the subtitle would sit dark-on-dark
    if lum(seen[white]) < 170 or lum(seen[white]) - lum(seen[black]) < 90:
        return None
    return white, black

def render(text, size):
    """bilevel glyph mask plus a one pixel outline around it"""
    w = measure(text, size)
    img = Image.new('L', (max(w, 1) + 2, size + 4), 0)
    d = ImageDraw.Draw(img)
    d.fontmode = '1'
    d.text((1, 2), text, font=font(size), fill=255)
    px = img.load()
    fill = [(x, y) for y in range(img.height) for x in range(img.width) if px[x, y]]
    edge = set()
    for x, y in fill:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                p = (x + dx, y + dy)
                if 0 <= p[0] < img.width and 0 <= p[1] < img.height and not px[p[0], p[1]]:
                    edge.add(p)
    return img.size, set(fill), edge

def main(dat_in, labels_json, dat_out):
    entries = json.load(open(labels_json, encoding='utf-8-sig'))
    info = ncer.load(dat_in)
    if not info or not info.get('ncer'):
        print(json.dumps({'error': 'no NCER', 'file': os.path.basename(dat_in)})); return 1
    nbanks = len(info['ncer']['banks'])
    vals = info['vals']

    # a tile written for one cell shows up in every cell that shares it, so a
    # pixel may only be claimed once
    # One size for the whole sheet: a menu where one button is 24px and the
    # next is 12px looks broken, so pick the largest size every label can use.
    usable = []
    for e in entries:
        if e.get('skip'):
            continue
        idx = e.get('cell')
        kr = (e.get('kr') or '').strip().replace(chr(10), ' ')
        if idx is None or idx >= nbanks or not kr: continue
        r = lt.cell_pixels(info, idx)
        if r is None: continue
        W, H, _ = r
        if W < 20 or H < 14: continue
        usable.append((kr, W, H))
    size = None
    forced_sizes = {int(e['size']) for e in entries
                    if not e.get('skip') and e.get('size') in SIZES}
    if len(forced_sizes) == 1:
        size = next(iter(forced_sizes))
    for s_ in SIZES:
        if size is not None:
            break
        if usable and all(s_ + 4 <= H and measure(kr, s_) + 2 <= W
                          for kr, W, H in usable):
            size = s_; break
    if size is None:
        size = SIZES[-1]

    claimed = set()
    drawn = skipped = 0
    rects = {}
    for e in entries:
        if e.get('skip'):
            skipped += 1
            continue
        forced = bool(e.get('force'))
        idx = e.get('cell')
        kr = (e.get('kr') or '').strip().replace('\n', ' ')
        if idx is None or idx >= nbanks or not kr:
            skipped += 1; continue
        r = lt.cell_pixels(info, idx)
        if r is None:
            skipped += 1; continue
        W, H, src = r
        ink = palette_ink(info, src, W, H)
        if ink is None or W < 20 or H < 14:
            skipped += 1; continue
        white, black = ink

        if not forced and (size + 4 > H or measure(kr, size) + 2 > W):
            skipped += 1; continue
        if not forced and measure(kr, size) / max(len(kr), 1) < MIN_COL:
            skipped += 1; continue
        (tw, th), fill, edge = render(kr, size)
        if not forced and (tw > W or th > H):
            skipped += 1; continue

        # A subtitle only works if it is big enough to stand in for the line it
        # covers.  Much narrower than the cell and the Japanese pokes out at
        # both ends, which reads worse than leaving the cell alone.
        if not forced and tw < MIN_COVER * W:
            skipped += 1; continue

        ox = (W - tw) // 2
        # these captions run along the bottom edge of the icon; small buttons
        # carry their text in the middle
        oy = (H - th)//2 if H <= 40 else max(0, H - th - 2)

        # a twin cell - the same art one pixel over - has already written most
        # of these tiles; drawing again would print the subtitle twice
        pix = [(x, y) for y in range(oy, min(H, oy + th))
               for x in range(ox, min(W, ox + tw)) if src[y][x]]
        if pix:
            taken = sum(1 for x, y in pix
                        if src[y][x][0]*64 + src[y][x][1] in claimed)
            if taken > 0.4 * len(pix):
                skipped += 1; continue

        def put(X, Y, colour):
            if not (0 <= X < W and 0 <= Y < H): return False
            s_ = src[Y][X]
            if s_ is None: return False
            key = s_[0]*64 + s_[1]
            if key in claimed: return False
            claimed.add(key); vals[key] = colour
            return True

        for x, y in edge:                    # black outline first
            put(ox + x, oy + y, black)
        wrote = False
        for x, y in fill:                    # then the white letters on top
            wrote |= put(ox + x, oy + y, white)

        if wrote:
            drawn += 1
            rects[str(idx)] = [ox, oy, ox + tw, oy + th]
        else:
            skipped += 1

    ok = lt.save_ncgr(info, dat_in, dat_out)
    rd = os.path.join(os.path.dirname(os.path.dirname(dat_out)), 'rects')
    os.makedirs(rd, exist_ok=True)
    json.dump(rects, open(os.path.join(rd, os.path.basename(dat_out) + '.json'),
                          'w', encoding='utf-8'))
    print(json.dumps({'file': os.path.basename(dat_in), 'overlaid': drawn,
                      'skipped': skipped, 'written': bool(ok)}, ensure_ascii=False))
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3]))
