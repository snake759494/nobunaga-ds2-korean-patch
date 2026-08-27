# -*- coding: utf-8 -*-
"""How much Japanese still shows up wearing a Hangul glyph?

Hangul is stored by repainting kanji glyph slots.  Any kanji that survives
untranslated and happens to sit in a repainted slot is drawn as a random
Korean syllable - that is the corruption players report (織田家 -> "오다덕").
This scans the finished ROM's text regions and counts real collisions.

Usage: python tools/check_glyph_clash.py [--list N]
"""
import os, sys, json, collections
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nobu2_paths import ROM_OUT, WORK

def sjis_runs(buf):
    """codes of 2-byte SJIS pairs, only inside plausible text runs"""
    out = collections.Counter()
    i, n = 0, len(buf)
    while i < n:
        b = buf[i]
        if (0x81 <= b <= 0x9F or 0xE0 <= b <= 0xEF) and i + 1 < n:
            t = buf[i + 1]
            if 0x40 <= t <= 0xFC and t != 0x7F:
                out[(b << 8) | t] += 1
                i += 2
                continue
        i += 1
    return out

def main():
    c2i = {int(k, 16): v for k, v in json.load(open(os.path.join(WORK, 'code2idx.json'))).items()}
    smap = json.load(open(os.path.join(WORK, 'syllable_map.json'), encoding='utf-8'))
    code2syl = {int(v, 16): s for s, v in smap.items()}
    rom = open(ROM_OUT, 'rb').read()
    man = json.load(open(os.path.join(WORK, 'manifest.json')))

    counts = collections.Counter()
    for f in man['files']:
        if f['path'].startswith('/msg/msgsec') or f['path'] == '/scenario/common.snr':
            counts += sjis_runs(rom[f['start']: f['start'] + f['size']])
    # arm9 is code as well as text; still worth counting, it is where the
    # system strings live
    counts += sjis_runs(rom[0x4000: 0x4000 + 0x1A1098])

    kanji = {c: n for c, n in counts.items() if c2i.get(c, 0) >= 351}
    clash = {c: n for c, n in kanji.items() if c in code2syl}
    print(f'kanji-slot codes still present : {len(kanji)} distinct, {sum(kanji.values())} times')
    print(f'  of them repainted as Hangul  : {len(clash)} distinct, {sum(clash.values())} times')
    if clash:
        print(f'  -> those show as the wrong syllable on screen')
    n = 20
    if '--list' in sys.argv:
        n = int(sys.argv[sys.argv.index('--list') + 1])
    for c, k in sorted(clash.items(), key=lambda x: -x[1])[:n]:
        try: ch = bytes([c >> 8, c & 0xFF]).decode('shift_jis')
        except Exception: ch = '?'
        print(f'     {ch}  U+{ord(ch):04X}  {k:5d}x  shows as "{code2syl[c]}"')
    return len(clash)

if __name__ == '__main__':
    sys.exit(0 if main() == 0 else 1)
