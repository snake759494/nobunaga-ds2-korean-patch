# -*- coding: utf-8 -*-
"""Apply Korean label translations into the sprite graphics of a .dat archive.

Two things make this harder than "draw text into a box":

1. The UI sprites are built from a shared GLYPH ATLAS - 確定 and 確認 both point
   at the tiles of 確.  Drawing whole strings per cell makes neighbouring labels
   overwrite each other.  So text is laid out CHARACTER BY CHARACTER into equal
   columns and each tile is claimed by exactly one character: a shared glyph
   then always receives the same Hangul syllable (hanja readings are 1:1).
   Tiles that two different characters would claim are left untouched.

2. Galmuri11 is a PIXEL font.  It must be rendered without antialiasing and at
   its native 12px size, otherwise thresholding shreds the strokes.

Usage: python apply_labels.py <dat-in> <labels.json> <dat-out>
"""
import os, sys, json, collections
from PIL import Image, ImageFont, ImageDraw
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ncer
import label_tools as lt
import os as _os, sys as _sys
_sys.path[:0] = [_os.path.dirname(_os.path.abspath(__file__)),
                _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..')]
from nobu2_paths import ROM_IN, ROM_OUT, WORK, FONT, DATA

# Galmuri11 is pixel-perfect at multiples of 12 and ONLY there: at 9 or 10 px
# the strokes of a Hangul syllable merge into a solid block.  So 24 for tall
# buttons, 12 for everything else, and nothing in between - a label that cannot
# fit 12 px per character is skipped rather than rendered as mush.
SIZES = (24, 12)
MIN_COL = 7
INSET = 2
MIN_INK = 8
_fonts = {}

def font(size):
    if size not in _fonts:
        _fonts[size] = ImageFont.truetype(FONT, size)
    return _fonts[size]

def measure(text, size):
    return font(size).getmask(text, mode='1').size[0]

def analyse(info, idx):
    """(W,H,src,bg,ink,box) - box is the bbox of the TEXT ink only, so frames,
    borders and gradients drawn in other colours stay out of the layout.

    Buttons here are ornate (bevelled frame over a gradient fill), so the text
    is not simply "the second most common colour" - it is the BRIGHTEST colour
    that covers a meaningful number of pixels well inside the frame."""
    r = lt.cell_pixels(info, idx)
    if r is None: return None
    W, H, src = r
    if W < 12 or H < 10: return None
    inx = max(INSET, W // 8)
    iny = max(INSET, H // 6)
    if W - 2*inx < 8 or H - 2*iny < 8:
        inx = iny = INSET
    vals, pal = info['vals'], info['pal']
    hist = collections.Counter(); banks = collections.Counter()
    for y in range(iny, H - iny):
        for x in range(inx, W - inx):
            s = src[y][x]
            if s:
                hist[vals[s[0]*64 + s[1]]] += 1
                banks[s[2] if len(s) > 2 else 0] += 1
    if len(hist) < 2: return None
    bg = hist.most_common(1)[0][0]
    pb = banks.most_common(1)[0][0] if banks else 0

    def lum(v):
        pi = pb*16 + v
        if not pal or pi >= len(pal): return v * 16
        r_, g_, b_ = pal[pi]
        return 0.30*r_ + 0.59*g_ + 0.11*b_

    # The lettering is the brightest colour that covers a real area.  Picking
    # the brightest colour outright latches onto a stray highlight inside an
    # icon, and the "text" box then spans the whole button.
    nonbg = [(v, n) for v, n in hist.items()
             if v != bg and v != 0 and n >= MIN_INK]
    if not nonbg: return None
    peak = max(n for _, n in nonbg)
    cands = [v for v, n in nonbg if n >= 0.15 * peak]
    ink = max(cands, key=lum)

    # Measure the text over the WHOLE cell, not the inset window: wide banner
    # labels have no frame and the inset would clip their first and last glyph.
    # A frame instead shows up as a row or column that is almost solid ink, so
    # drop those lines before taking the bounding box.
    ipx = [[False]*W for _ in range(H)]
    solid = [[False]*W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            s = src[y][x]
            if s is None: continue
            v = vals[s[0]*64 + s[1]]
            solid[y][x] = v != 0
            ipx[y][x] = v == ink
    cx = [x for x in range(W) if any(solid[y][x] for y in range(H))]
    cy = [y for y in range(H) if any(solid[y][x] for x in range(W))]
    if not cx or not cy: return None
    cx0, cx1, cy0, cy1 = cx[0], cx[-1], cy[0], cy[-1]

    def run(cells):
        best = cur = 0
        for c in cells:
            cur = cur + 1 if c else 0
            best = max(best, cur)
        return best
    def frame_at(fixed_is_col, start, step, span, need):
        """innermost near-edge line that is a continuous stroke - a frame, not text"""
        found = None
        for d in range(5):
            i = start + d*step
            if not (0 <= i < (W if fixed_is_col else H)): break
            line = ([ipx[y][i] for y in range(cy0, cy1 + 1)] if fixed_is_col
                    else [ipx[i][x] for x in range(cx0, cx1 + 1)])
            if run(line) >= need: found = i
        return found
    hspan, vspan = cx1 - cx0 + 1, cy1 - cy0 + 1
    fl = frame_at(True, cx0, 1, vspan, max(8, int(vspan * 0.7)))
    fr = frame_at(True, cx1, -1, vspan, max(8, int(vspan * 0.7)))
    ft = frame_at(False, cy0, 1, hspan, max(8, int(hspan * 0.7)))
    fb = frame_at(False, cy1, -1, hspan, max(8, int(hspan * 0.7)))
    rx0 = (fl + 1) if fl is not None else cx0
    rx1 = (fr - 1) if fr is not None else cx1
    ry0 = (ft + 1) if ft is not None else cy0
    ry1 = (fb - 1) if fb is not None else cy1
    if rx1 - rx0 < 8 or ry1 - ry0 < 6: return None

    pts = [(x, y) for y in range(ry0, ry1 + 1) for x in range(rx0, rx1 + 1) if ipx[y][x]]
    if len(pts) < MIN_INK: return None
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    box = (min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)
    if box[2] < 6 or box[3] < 6: return None
    room = (rx0, ry0, rx1 - rx0 + 1, ry1 - ry0 + 1)
    framed = any(f is not None for f in (fl, fr, ft, fb))
    bgs = backgrounds(src, W, H, vals, box, room, ink, bg)
    erase = grow(src, W, H, vals, box, room, set(bgs.values()) | {bg, 0})
    # If the detected text swallows a framed button whole, the colour analysis
    # has latched onto the plate rather than the lettering; repainting it would
    # wipe the button.  Leave such a cell alone.
    # A framed button whose "text" fills the plate edge to edge means the colour
    # analysis latched onto the plate, not the lettering - repainting would wipe
    # the button.  Small labels legitimately fill their plate, so only large
    # ones are rejected.
    if (framed and room[2]*room[3] > 900
            and erase[2]*erase[3] >= 0.85 * room[2]*room[3]): return None
    # If a lot of lettering on the same line survives outside the repaint area,
    # the result would read half Korean, half Japanese.  Better to leave it.
    # Count only pixels in the LETTERING colour: side rules, brackets and other
    # decoration are drawn in other shades and legitimately stay put, but a big
    # share of surviving ink means half the sentence would remain Japanese.
    left = inside = 0
    for y in range(erase[1], min(H, erase[1] + erase[3])):
        for x in range(rx0, rx1 + 1):
            if not ipx[y][x]: continue
            if erase[0] <= x < erase[0] + erase[2]: inside += 1
            else: left += 1
    if left > 20 and left > 0.30 * (left + inside): return None
    return W, H, src, bgs, bg, ink, box, room, erase

def grow(src, W, H, vals, box, room, bgset, limit=6):
    """Widen the bbox until it covers the glyph's decoration.  The layout box is
    the bbox of the core colour only; these labels are drawn with a coloured
    outline and swashes that reach past it, and leaving those behind puts stray
    strokes around the Hangul."""
    x0, y0, x1, y1 = box[0], box[1], box[0] + box[2], box[1] + box[3]
    rx, ry, rw, rh = room
    rx1, ry1 = rx + rw, ry + rh
    def dirty(pts):
        for x, y in pts:
            if 0 <= x < W and 0 <= y < H:
                s = src[y][x]
                if s and vals[s[0]*64 + s[1]] not in bgset: return True
        return False
    for _ in range(limit):
        moved = False
        if x0 > rx and dirty([(x0 - 1, y) for y in range(y0, y1)]):
            x0 -= 1; moved = True
        if x1 < rx1 and dirty([(x1, y) for y in range(y0, y1)]):
            x1 += 1; moved = True
        if y0 > ry and dirty([(x, y0 - 1) for x in range(x0, x1)]):
            y0 -= 1; moved = True
        if y1 < ry1 and dirty([(x, y1) for x in range(x0, x1)]):
            y1 += 1; moved = True
        if not moved: break
    return (x0, y0, x1 - x0, y1 - y0)

def backgrounds(src, W, H, vals, box, room, ink, bg):
    """Background colour PER ROW.  Buttons are painted with a vertical gradient,
    so erasing the kanji with one flat colour leaves a visible band - and when
    the plate is smaller than the cell, the cell-wide favourite is the
    transparent margin, which would punch a hole straight through the button."""
    bx, by, bw, bh = box
    rx, ry, rw, rh = room
    sides = list(range(rx, bx)) + list(range(bx + bw, rx + rw))
    # When the text spans the full width there is nothing beside it to sample.
    # Fall back to the cell's outer ring, which is always outside the lettering
    # - never to colours inside the text row, which are the glyph's own outline
    # and shadow and would erase the kanji into a dark bar.
    # What sits behind the lettering?  Sample the halo just outside the glyphs
    # first: for a caption floating in a transparent window that IS the answer.
    # But on a button the halo is only the inner bevel line, so when the near
    # ring has no clear majority, widen out to the whole plate on those rows.
    near = collections.Counter()
    for y in range(max(0, by - 4), min(H, by + bh + 4)):
        for x in range(max(0, bx - 4), min(W, bx + bw + 4)):
            if bx - 2 <= x < bx + bw + 2 and by - 2 <= y < by + bh + 2: continue
            if not (rx <= x < rx + rw and ry <= y < ry + rh): continue
            s_ = src[y][x]
            if s_:
                v = vals[s_[0]*64 + s_[1]]
                if v != ink: near[v] += 1
    wide = collections.Counter()
    for y in range(max(0, by), min(H, by + bh)):
        for x in range(max(0, rx), min(W, rx + rw)):
            if bx - 2 <= x < bx + bw + 2: continue
            s_ = src[y][x]
            if s_:
                v = vals[s_[0]*64 + s_[1]]
                if v != ink: wide[v] += 1
    tot = sum(near.values())
    # A transparent halo is proof the caption floats in a window, so trust it.
    # An opaque halo may just be the plate's inner bevel, which is a line and
    # not the fill - in that case take the colour of the plate as a whole.
    if tot and near.most_common(1)[0] [0] == 0 and near[0] >= 0.6 * tot:
        vfill = 0
    elif wide:
        vfill = wide.most_common(1)[0][0]
    elif near:
        vfill = near.most_common(1)[0][0]
    else:
        vfill = bg
    common = {v for v, _ in (wide or near).most_common(3)}
    if vfill == 0:
        # the label floats on transparency: erase it back to transparency for
        # every row.  Sampling beside the text would pick up the outer glyph's
        # swash and lay it down as a coloured bar straight through the word.
        return {y: 0 for y in range(max(0, min(ry, by - PAD)),
                                    min(H, max(ry + rh, by + bh + PAD)))}
    out = {}
    for y in range(max(0, min(ry, by - PAD)), min(H, max(ry + rh, by + bh + PAD))):
        beside = collections.Counter()
        for x in sides:
            if 0 <= x < W and src[y][x]:
                v = vals[src[y][x][0]*64 + src[y][x][1]]
                if v != ink: beside[v] += 1
        # a couple of pixels beside the text are just the outer glyph's outline;
        # only a real margin tells us the plate colour for this row
        if len(sides) >= 12 and sum(beside.values()) >= 12:
            v = beside.most_common(1)[0][0]
            # a bevel highlight beside the text is not the plate colour; only
            # accept a sample that the plate interior actually uses a lot of
            if v in common:
                out[y] = v; continue
        out[y] = vfill
    return out

def layout(text, box, room, force=None):
    """split the ink bbox into equal character columns, sized as large as the
    space inside the frame allows.  Returns (size, [(rect, char), ...])."""
    bx, by, bw, bh = box
    rx, ry, rw, rh = room
    n = len(text)
    # Korean often needs one more syllable than the kanji it replaces.  Rather
    # than clip it, borrow the empty space beside the original word.
    need = measure(text, SIZES[-1])
    if need > bw:
        bx = max(rx, bx - (need - bw + 1)//2)
        bw = min(rx + rw - bx, need)
    colw = bw / n
    size = SIZES[-1]
    for s in SIZES:
        if s <= rh and all(measure(c, s) <= colw + 1 for c in text):
            size = s; break
    if force is not None:
        size = force
    dh = min(rh, max(bh, size))
    dy = max(ry, min(by + (bh - dh)//2, ry + rh - dh))
    out = []
    for i, ch in enumerate(text):
        x0 = bx + int(round(i * bw / n))
        x1 = bx + int(round((i + 1) * bw / n))
        out.append(((x0, dy, max(1, x1 - x0), dh), ch))
    return size, out

def pixels_in(src, W, H, col):
    """the atlas pixels (tile*64+k) a column covers - pixel granularity, because
    neighbouring columns legitimately share the tiles at their border"""
    x0, y0, w, h = col
    return {src[y][x][0]*64 + src[y][x][1]
            for y in range(max(0, y0), min(H, y0 + h))
            for x in range(max(0, x0), min(W, x0 + w))
            if src[y][x]}

def render(text, bw, bh, size):
    """bilevel Galmuri render, centred in a bw x bh box"""
    w = measure(text, size)
    if w > bw and size > SIZES[-1]:
        size = SIZES[-1]
        w = measure(text, size)
    img = Image.new('L', (max(bw, 1), max(bh, 1)), 255)
    d = ImageDraw.Draw(img)
    d.fontmode = '1'                      # no antialiasing - keep pixel strokes intact
    d.text(((bw - w) // 2, (bh - size) // 2), text, font=font(size), fill=0)
    return img

PAD = 3      # the original glyph's soft edge sits just outside the ink bbox

def paint(info, src, W, H, region, canvas, ink, bgs, bg, claimed, blocked, own, bgset):
    """write the rendered region; never touch a pixel another character owns"""
    rx, ry = region
    px = canvas.load(); vals = info['vals']
    for y in range(canvas.height):
        for x in range(canvas.width):
            X, Y = rx + x, ry + y
            if not (0 <= X < W and 0 <= Y < H): continue
            s = src[Y][X]
            if s is None or s[0] not in own: continue
            key = s[0]*64 + s[1]
            if key in claimed: continue
            claimed.add(key)
            fill = bgs.get(Y, bg)
            v = ink if px[x, y] < 128 else fill
            # An atlas pixel that some other cell shows outside its text area is
            # part of that cell's artwork - a button plate, a frame.  Laying our
            # background over it punches a hole there.  Drawing a stroke, or
            # wiping out something that is lettering here, is always safe.
            if key in blocked and v != ink and vals[key] != ink: continue
            # A transparent pixel must stay transparent.  The same atlas tile is
            # reused by other cells where it shows through as empty space, so
            # touching it paints stray marks across the screen.  The exception is
            # a label that genuinely sits on transparency (banner titles): there
            # the row's own background IS transparent, so strokes may be added.
            if vals[key] == 0 and fill != 0: continue
            vals[key] = v

def main(dat_in, labels_json, dat_out):
    entries = json.load(open(labels_json, encoding='utf-8-sig'))
    info = ncer.load(dat_in)
    if not info or not info.get('ncer'):
        print(json.dumps({'error': 'no NCER', 'file': os.path.basename(dat_in)})); return 1
    nbanks = len(info['ncer']['banks'])

    # ---- one size for the whole sheet.  A menu where one button is 24px and
    # the one beside it is 12px reads as a mistake, so every label on a sheet
    # uses the largest size that all of them can manage.
    sheet_size = None
    for e in entries:
        idx = e.get('cell')
        kr = (e.get('kr') or '').strip()
        if idx is None or idx >= nbanks or not kr: continue
        a = analyse(info, idx)
        if a is None: continue
        _, _, _, _, _, _, box, room, _ = a
        s_, _ = layout(kr, box, room)
        sheet_size = s_ if sheet_size is None else min(sheet_size, s_)

    # ---- pass 1: work out what each character column wants, and where two
    #      different characters would fight over the same atlas tiles
    plans = []
    want = collections.defaultdict(set)      # tile -> {char}
    for e in entries:
        idx = e.get('cell')
        jp = (e.get('jp') or '').strip()
        kr = (e.get('kr') or '').strip()
        if idx is None or idx >= nbanks or not kr: continue
        a = analyse(info, idx)
        if a is None: continue
        W, H, src, bgs, bg, ink, box, room, erase = a
        # Some banks are mid-animation frames that draw only a sliver of the
        # button.  Their text box is far too narrow for the label, and writing
        # into it both looks wrong and damages the tiles the full frame shares.
        widest = max(kr.split('\n'), key=len)
        if box[2] < MIN_COL * len(widest): continue
        # And the reverse: a box far wider than the Korean needs means the
        # colour analysis grabbed an icon or a frame as well as the caption.
        # Repainting that would wipe out the button, so leave the cell alone.
        if box[2] > 2.6 * measure(widest, 12): continue
        # Korean that is much wider than the word it replaces cannot be placed
        # without crowding the frame, so leave those cells in Japanese.
        if measure(widest, 12) > 1.5 * box[2]: continue
        size, cols = layout(kr, box, room, force=sheet_size)
        if not (jp and len(kr) == len(jp) and len(kr) > 1):
            cols = [(cols[0][0][:2] + (box[2], cols[0][0][3]), kr)]
        items = []
        for col, ch in cols:
            ps = pixels_in(src, W, H, col)
            for p in ps: want[p].add(ch)
            items.append((col, ch, ps))
        plans.append((idx, W, H, src, bgs, bg, ink, size, room, erase, items))

    conflicted = {p for p, cs in want.items() if len(cs) > 1}

    # ---- pass 2: fix the repaint rectangle of every label that survived
    jobs = []
    skipped = 0
    for idx, W, H, src, bgs, bg, ink, size, room, erase, items in plans:
        # all or nothing: a half-translated word ("데모플レ이") is worse than
        # leaving the original, so one contested character vetoes the label
        if any(ps & conflicted for _, _, ps in items):
            skipped += 1; continue
        cols = [(c, ch) for c, ch, ps in items]
        # repaint the accepted columns plus a small pad, so the original glyph's
        # soft outline does not survive around the new Hangul.  Stay inside the
        # frame: bleeding into the transparent margin leaves blobs on screen.
        rox, roy, row_, roh = room
        rx = max(rox, min([c[0] for c, _ in cols] + [erase[0]]) - PAD)
        rx1 = min(rox + row_, max([c[0] + c[2] for c, _ in cols] + [erase[0] + erase[2]]) + PAD)
        ry = max(roy, min([c[1] for c, _ in cols] + [erase[1]]) - PAD)
        ry1 = min(roy + roh, max([c[1] + c[3] for c, _ in cols] + [erase[1] + erase[3]]) + PAD)
        if rx1 <= rx or ry1 <= ry: continue
        jobs.append((idx, W, H, src, bgs, bg, ink, size, cols, (rx, ry, rx1, ry1)))

    # ---- pass 3: a cell layers a text sprite over a background sprite that
    # other labelled cells reuse at a different offset.  Any atlas pixel that
    # such a cell shows outside its own text rectangle must stay untouched, or
    # writes leak out as stray marks elsewhere on the screen.
    exposed, owned = set(), set()
    for _, W, H, src, _, _, _, _, _, (rx, ry, rx1, ry1) in jobs:
        for y in range(H):
            inside = ry <= y < ry1
            for x in range(W):
                s = src[y][x]
                if s is None: continue
                k = s[0]*64 + s[1]
                if inside and rx <= x < rx1: owned.add(k)
                else: exposed.add(k)
    # A pixel that some label owns as its own lettering is safe to rewrite even
    # if a sibling cell shows it a pixel or two off; only pixels that NO label
    # claims - plates, frames, icons - are off limits.
    blocked = conflicted | exposed

    # ---- pass 4: draw
    claimed = set()
    drawn = 0
    vals = info['vals']
    for idx, W, H, src, bgs, bg, ink, size, cols, (rx, ry, rx1, ry1) in jobs:
        canvas = Image.new('L', (rx1 - rx, ry1 - ry), 255)
        for c, ch in cols:
            # a column narrower than the glyph would clip its left edge, so
            # render at full width and let neighbours overlap by a pixel
            w = max(c[2], size)
            img = render(ch, w, c[3], size)
            canvas.paste(img, (c[0] - rx - (w - c[2])//2, c[1] - ry))
            drawn += 1
        own = set(); seen = taken = 0
        for y in range(max(0, ry), min(H, ry1)):
            for x in range(max(0, rx), min(W, rx1)):
                s_ = src[y][x]
                if s_ is None: continue
                own.add(s_[0]); seen += 1
                if s_[0]*64 + s_[1] in claimed: taken += 1
        # A twin cell one pixel away has already rewritten most of these tiles.
        # Painting the leftover fringe would double the strokes, so stand down -
        # the twin's Hangul is already what this cell displays.
        if seen and taken > 0.45 * seen: continue
        paint(info, src, W, H, (rx, ry), canvas, ink, bgs, bg, claimed,
              blocked, own, set(bgs.values()) | {bg, 0})
    ok = lt.save_ncgr(info, dat_in, dat_out)
    # record where each cell was allowed to change, so the damage checker can
    # tell an intended rewrite from atlas leakage into an unrelated cell
    rd = os.path.join(os.path.dirname(os.path.dirname(dat_out)), 'rects')
    os.makedirs(rd, exist_ok=True)
    json.dump({str(j[0]): list(j[9]) for j in jobs},
              open(os.path.join(rd, os.path.basename(dat_out) + '.json'),
                   'w', encoding='utf-8'))
    print(json.dumps({'file': os.path.basename(dat_in), 'cells': len(plans),
                      'glyphs': drawn, 'skipped_conflict': skipped,
                      'written': bool(ok)}, ensure_ascii=False))
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3]))
