# -*- coding: utf-8 -*-
"""Apply every gfxlabels/*.json to its .dat, writing patched copies to fs_gfx/obj/.
Expands duplicate cells (animation frames sharing identical art) via the dump manifest."""
import os, sys, json, glob, shutil, subprocess
import concurrent.futures as cf
import os as _os, sys as _sys
_sys.path[:0] = [_os.path.dirname(_os.path.abspath(__file__)),
                _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..')]
from nobu2_paths import ROM_IN, ROM_OUT, WORK, FONT, DATA

# each .dat is an independent subprocess; the box is not the bottleneck, the
# per-pixel Python loops are, so run as many as the machine will take
WORKERS = max(4, (os.cpu_count() or 4) * 2)

SRC_OBJ = _os.path.join(WORK, 'fs', 'obj')
OUT_OBJ = _os.path.join(WORK, 'fs_gfx', 'obj')
LABELS = _os.path.join(WORK, 'gfxlabels')
DUMPS = [_os.path.join(WORK, 'gfxdump2'), _os.path.join(WORK, 'gfxdump')]
TOOLS = os.path.dirname(os.path.abspath(__file__))

def manifest_for(name):
    for d in DUMPS:
        p = os.path.join(d, f'{name}_cells.json')
        if os.path.exists(p):
            return json.load(open(p, encoding='utf-8'))
    return None

def expand(name, entries):
    man = manifest_for(name)
    if not man: return entries
    dup = {}
    for c in man['cells']:
        if 'same_as' in c:
            dup.setdefault(c['same_as'], []).append(c['index'])
    out = list(entries)
    have = {e['cell'] for e in entries}
    for e in entries:
        for d in dup.get(e['cell'], []):
            if d not in have:
                out.append({'cell': d, 'jp': e.get('jp', ''), 'kr': e['kr']})
                have.add(d)
    return out

# Ending.dat is the staff roll: multi-line credit blocks (role above, name
# below) that the single-line layout cannot reproduce.
# ComTutor.dat mixes a button icon (START, +) into the same text row, and the
# plate it sits on defeats the background detection - the 2 cells are not worth
# the risk.  Both are left in Japanese.
# Common.dat holds the tiny yes/no chips: the words are only a few pixels tall
# on a plate the same size, and the text detector cannot separate them.
# SaveLoadShita paints the slot number into the same tiles as the caption,
# so rewriting the caption chews up the digit.
SKIP = {'Ending', 'ComTutor', 'Common', 'SaveLoadShita'}

def skipped(name):
    # C256_* are the 256-colour illustration sheets - emblems, season art,
    # menu icons.  Their Japanese is a caption fused into the artwork, and the
    # text detector keeps latching onto the picture instead.  Not worth it.
    return name in SKIP or name.startswith('C256_')

# Ending is a staff roll of two-line credit blocks - a subtitle cannot stand in
# for that, so it stays Japanese.  Everything else that we refuse to repaint
# gets a Korean subtitle laid over the picture instead.
# Sheets where a subtitle actually reads well: an icon or emblem with a
# caption along its bottom edge, wide enough for the Korean to stand in for.
# Everything else here is a wide bar with several Japanese words spread across
# it, where a subtitle covers one word and leaves the rest - worse than not
# translating at all - so those stay Japanese.
OVERLAY = {
    'C256_SeasonSpring', 'C256_SeasonSummer', 'C256_SeasonFall', 'C256_SeasonWinter',
    'C256_SouhaMenuShita', 'C256_ShoOptShita', 'C256_ShinbuShita1',
}
# Common (はい / いいえ) and ComTutor (START中止 / +進む) carry an icon or a
# latin prefix inside the same line, so a subtitle covers the Japanese word but
# not the rest and the button ends up half and half.  They stay Japanese.

def overlay_only(name):
    return skipped(name) and name in OVERLAY

def prepare(lp):
    """validate + expand one label file; returns (name, entries) or None"""
    name = os.path.splitext(os.path.basename(lp))[0]
    if name.startswith('_') or (skipped(name) and name not in OVERLAY): return None
    dat = os.path.join(SRC_OBJ, name + '.dat')
    if not os.path.exists(dat):
        print(f'  skip {name}: no .dat'); return None
    try:
        entries = json.load(open(lp, encoding='utf-8-sig'))
    except Exception as e:
        print(f'  skip {name}: bad json ({e})'); return None
    entries = [e for e in entries if e.get('kr')]
    if not entries: return None
    if True:
        # reject mojibake: a valid entry has Japanese in `jp` AND Hangul in `kr`.
        # Encoding-damaged files show Hangul-looking bytes in `jp` and '?' in `kr`.
        def is_jp(s):
            return any('\u3041' <= c <= '\u30ff' or '\u4e00' <= c <= '\u9fff'
                       or '\uff10' <= c <= '\uff5a' for c in s)
        def is_kr(s):
            return any('\uac00' <= c <= '\ud7a3' for c in s)
        # Terms whose natural transliteration overflows a narrow button:
        # use a shorter Korean word that still reads correctly.
        FIT = {'足軽': '보병', '足軽隊': '보병대', '騎馬隊': '기마대', '鉄砲隊': '철포대'}
        for e in entries:
            j = e.get('jp', '')
            if j in FIT:
                e['kr'] = FIT[j]
        # Latin-only art (Wi-Fi, RUN&GUN ...) is already readable - leave it alone.
        good = [e for e in entries
                if is_jp(e.get('jp', '')) and is_kr(e['kr']) and '?' not in e['kr']]
        if not good:
            print(f'  skip {name}: encoding-damaged or unusable'); return None
        if len(good) < len(entries):
            print(f'  {name}: dropped {len(entries)-len(good)} damaged entries')
        return name, expand(name, good)

def run_one(job):
    """each file is an independent process, so they all run at once"""
    name, entries = job
    dat = os.path.join(SRC_OBJ, name + '.dat')
    tmp = os.path.join(WORK, f'_labels_{name}.json')
    json.dump(entries, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False)
    out = os.path.join(OUT_OBJ, name + '.dat')
    script = 'overlay_labels.py' if overlay_only(name) else 'apply_labels.py'
    r = subprocess.run([sys.executable, os.path.join(TOOLS, script),
                        dat, tmp, out], capture_output=True, text=True, encoding='utf-8')
    os.remove(tmp)
    return name, len(entries), r.stdout.strip(), os.path.exists(out)

def main():
    os.makedirs(OUT_OBJ, exist_ok=True)
    jobs = [j for j in (prepare(lp)
                        for lp in sorted(glob.glob(_os.path.join(LABELS, '*.json')))) if j]
    total_files = total_labels = 0
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for name, n, out, ok in ex.map(run_one, jobs):
            print(f'  {name}: {out}')
            if ok:
                total_files += 1
                total_labels += n
    print(f'files patched: {total_files}, labels applied: {total_labels}')

if __name__ == '__main__':
    main()
