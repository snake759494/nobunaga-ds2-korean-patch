# -*- coding: utf-8 -*-
"""Draw a Korean caption on a sprite cell.

Some menus are pictures with the Japanese baked into them - a brush-and-scroll
icon captioned 作成, an emblem reading 中断データ, a cherry-blossom disc with a
big 春.  Erasing the text there destroys the picture, because the letters and
the drawing share the same colours and often the same tiles.

By default this overlays the Korean the way a subtitle works: white fill with
a black outline, laid over the original caption.  For small captions whose
Japanese remains visible around the subtitle, label data can opt into a
``manual.replace`` rectangle.  That mode paints a compact caption panel first
and then draws the Korean on it, so the translated asset contains no leftover
Japanese while the surrounding artwork remains unchanged.

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
    """The palette entries to use for the white letters and the black outline.

    4bpp: the entries closest to white and to black among the colours this
    cell actually uses (a 16-entry bank rarely has a spare white).
    8bpp: every bank has 256 entries, so pick the brightest and the darkest
    entry of the whole bank - the caption must read as white-on-black, not as
    cream-on-brown, whichever colours the picture happens to use.  Cells that
    share tiles but select a different bank (a dimmed button) are checked too:
    the chosen entries must stay light/dark in every bank the sheet uses."""
    pal, vals = info['pal'], info['vals']
    if not pal: return None
    banks = set()
    for y in range(H):
        for x in range(W):
            s = src[y][x]
            if s is not None: banks.add(s[2] if len(s) > 2 else 0)
    if info.get('bpp') == 8:
        sheet_banks = {s.get('pal', 0) for bk in info['ncer']['banks'] for s in bk['sprites']}
        cand = list(range(1, 256))
        def score(v, want_white):
            ls = [lum(pal[lt.pal_index(info, b, v)]) for b in sheet_banks
                  if lt.pal_index(info, b, v) < len(pal)]
            if not ls: return -1
            return min(ls) if want_white else 255 - max(ls)
        white = max(cand, key=lambda v: score(v, True))
        black = max(cand, key=lambda v: score(v, False))
        if score(white, True) < 170 or score(white, True) - (255 - score(black, False)) < 90:
            return None
        return white, black
    seen = {}
    for y in range(H):
        for x in range(W):
            s = src[y][x]
            if s is None: continue
            v = vals[s[0]*64 + s[1]]
            if v == 0: continue                     # transparent
            pi = lt.pal_index(info, s[2] if len(s) > 2 else 0, v)
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

def rect_value(manual, key, default, W, H):
    """Read a clipped [x, y, w, h] rectangle from a manual entry."""
    raw = manual.get(key, default)
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        raw = default
    x, y, w, h = (int(v) for v in raw)
    x = max(0, min(W, x)); y = max(0, min(H, y))
    w = max(0, min(W - x, w)); h = max(0, min(H - y, h))
    return x, y, w, h

def replace_caption(info, idx, entry, claimed, rects):
    """Replace a manually selected artwork caption with a solid caption panel.

    C256 sheets are 8bpp, but the NCER still points each visible pixel back to
    its NCGR byte.  Restricting the write to the selected cell rectangle keeps
    the operation deterministic and lets duplicate animation cells share the
    same rewritten tiles without writing a second copy of the text.
    """
    r = lt.cell_pixels(info, idx)
    if r is None:
        return False
    W, H, src = r
    manual = entry.get('manual') or {}
    cover = rect_value(manual, 'cover', (0, 0, W, H), W, H)
    text_box = rect_value(manual, 'text_box', cover, W, H)
    if cover[2] <= 0 or cover[3] <= 0 or text_box[2] <= 0 or text_box[3] <= 0:
        return False

    kr = (entry.get('kr') or '').strip().replace(chr(10), ' ')
    if not kr:
        return False
    ink_pair = palette_ink(info, src, W, H)
    if ink_pair is None:
        return False
    white, black = ink_pair
    # Some C256 animation states share the same NCGR tiles but select a
    # different palette bank. A value that is white in one bank can be dark
    # in the other, so label data may provide a value bright in every bank.
    white = int(manual.get('ink', white))
    black = int(manual.get('outline', black))
    backdrop = int(manual.get('bg', black))
    size = int(entry.get('size', 12))
    if size not in SIZES:
        size = 12
    while size > 12 and (measure(kr, size) + 2 > text_box[2] or size + 4 > text_box[3]):
        size = 12
    (tw, th), fill, edge = render(kr, size)
    if tw > text_box[2] or th > text_box[3]:
        return False

    # If this cell is an animation duplicate of an already handled cell, the
    # NCGR bytes already carry the same panel and Korean caption.
    keys = set()
    for y in range(cover[1], cover[1] + cover[3]):
        for x in range(cover[0], cover[0] + cover[2]):
            s = src[y][x]
            if s:
                keys.add(s[0] * 64 + s[1])
    if keys and len(keys & claimed) >= 0.90 * len(keys):
        # Keep the audit rectangle for duplicate animation cells too.  Their
        # NCGR values were changed by the first cell, so the audit must treat
        # the same visual caption area as intentional in every duplicate.
        rects[str(idx)] = [cover[0], cover[1], cover[0] + cover[2], cover[1] + cover[3]]
        return False

    vals = info['vals']
    for y in range(cover[1], cover[1] + cover[3]):
        for x in range(cover[0], cover[0] + cover[2]):
            s = src[y][x]
            if not s:
                continue
            key = s[0] * 64 + s[1]
            vals[key] = backdrop
            claimed.add(key)

    ox = text_box[0] + (text_box[2] - tw) // 2
    oy = text_box[1] + (text_box[3] - th) // 2
    for x, y in edge:
        X, Y = ox + x, oy + y
        if 0 <= X < W and 0 <= Y < H and src[Y][X]:
            vals[src[Y][X][0] * 64 + src[Y][X][1]] = black
    for x, y in fill:
        X, Y = ox + x, oy + y
        if 0 <= X < W and 0 <= Y < H and src[Y][X]:
            vals[src[Y][X][0] * 64 + src[Y][X][1]] = white
    rects[str(idx)] = [cover[0], cover[1], cover[0] + cover[2], cover[1] + cover[3]]
    return True

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
        if (e.get('manual') or {}).get('replace'):
            if replace_caption(info, idx, e, claimed, rects):
                drawn += 1
            else:
                skipped += 1
            continue
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
        # a caption painted in the middle of the picture (the season discs)
        # is covered best by a subtitle placed right over it
        if e.get('pos') == 'center':
            oy = (H - th)//2

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

    # a dimmed or offset animation frame reuses the same tiles, so it now
    # carries the subtitle too; record the same rectangle for it so the
    # damage audit knows the change there is intentional
    def tile_keys(j):
        r = lt.cell_pixels(info, j)
        if r is None: return None
        W, H, src = r
        return (W, H), {src[y][x][0]*64 + src[y][x][1]
                        for y in range(H) for x in range(W) if src[y][x]}
    drawn_keys = {i_: tile_keys(int(i_)) for i_ in list(rects)}
    for j in range(nbanks):
        if str(j) in rects: continue
        kj = tile_keys(j)
        if not kj or not kj[1]: continue
        for i_, ki in drawn_keys.items():
            if ki and ki[0] == kj[0] and len(kj[1] & ki[1]) >= 0.5*len(kj[1]):
                rects[str(j)] = rects[i_]; break
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
