# -*- coding: utf-8 -*-
"""v1.3 builder: expansion WITHIN the game's proven message-buffer limit.
- Cap every msgsec file at MAX_ORIG (= largest original msgsec size, 16137 B),
  which the game demonstrably loads, so no buffer overflow.
- Files that grew are relocated into the ROM's UNUSED TAIL; every other file
  (sound, graphics, movie, snr) stays byte-identical at its original offset.
- Only the grown files' FAT entries, header used-size and header CRC change.
"""
import json, glob, os, struct, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import krtools, msg_rebuild
import bg_patch
import bg_labels
import formal_ui
import snr_caps as _snr
import os as _os, sys as _sys
_sys.path[:0] = [_os.path.dirname(_os.path.abspath(__file__)),
                _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..')]
from nobu2_paths import ROM_IN, ROM_OUT, WORK, FONT, DATA

ARM9_ROM_OFF = 0x4000
FONT_OFF = 0x178E64

CHAR_FIX = {'－':'−','·':'・','‧':'・','～':'〜','–':'―','—':'―','─':'―',
            '‘':"'",'’':"'",'“':'"','”':'"','⋯':'…'}
def fix(kr):
    for b, g in CHAR_FIX.items():
        if b in kr: kr = kr.replace(b, g)
    return kr

def trim(kr):
    """Drop trailing padding on each line. Japanese pads line ends with fullwidth
    spaces for column alignment; at the END of a line it is invisible, so this
    reclaims bytes for the translation with no visual change."""
    return '{BR}'.join(ln.rstrip('　 ') for ln in kr.split('{BR}'))

def enc_unit(kr, budgets, smap):
    lines = kr.split('{BR}')
    if len(lines) != len(budgets):
        raise ValueError('line count')
    parts = []
    for txt, b in zip(lines, budgets):
        e = krtools.encode_line(txt, smap)
        if len(e) > b:
            raise ValueError('overflow')
        parts.append(e)
    return b'\x0A'.join(parts)

def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc

def main():
    units_v1 = {u['id']: u for u in json.load(open(_os.path.join(WORK, 'units.json'), encoding='utf-8'))}
    for ex in (r'\units_extra.json', r'\units_extra2.json', r'\units_extra3.json'):
        if os.path.exists(WORK + ex):
            for u in json.load(open(WORK + ex, encoding='utf-8')):
                units_v1[u['id']] = u
    units_v2 = {u['id']: u for u in json.load(open(_os.path.join(WORK, 'units_v2.json'), encoding='utf-8'))}

    tr1, tr2, tr3 = {}, {}, {}
    for p in sorted(glob.glob(_os.path.join(WORK, 'tr', 'out', 'out_*.json'))):
        try:
            for it in json.load(open(p, encoding='utf-8')): tr1[it['id']] = it.get('kr', '')
        except Exception: pass
    for p in sorted(glob.glob(_os.path.join(WORK, 'tr', 'out2', 'out_*.json'))):
        try:
            for it in json.load(open(p, encoding='utf-8')): tr2[it['id']] = it.get('kr', '')
        except Exception: pass
    # v3: same byte budget as the terse fallback, but written naturally.
    # It therefore REPLACES v1 as the compact option, never the expanded one.
    for p in sorted(glob.glob(_os.path.join(WORK, 'tr', 'out3', 'out_*.json'))):
        try:
            for it in json.load(open(p, encoding='utf-8')): tr3[it['id']] = it.get('kr', '')
        except Exception: pass
    print(f'translations: v1={len(tr1)} v2={len(tr2)} v3={len(tr3)}')

    cand, budgets_of = {}, {}
    for uid, u in units_v2.items():
        budgets_of[uid] = u['lines']
        opts = []
        for src_tr, tag in ((tr2, 'v2'), (tr3, 'v3'), (tr1, 'v1')):
            raw = src_tr.get(uid)
            if raw is None: continue
            # A formal ending can cost one or more glyph slots.  Prefer it,
            # but retain the original candidate when the formalized form no
            # longer fits the unit's byte/line budget.
            # Trim before formalization as well as after it.  Message source
            # candidates often carry invisible full-width padding at the end
            # of a line; leaving that padding in the phrase prevents a
            # complete-record rewrite from matching, so the size pass can
            # accidentally fall back to the informal candidate.
            base = trim(fix(raw))
            variants = [fix(formal_ui.formalize(u['src'], base)), base]
            for kr in variants:
                if krtools.check_translation(kr, u['lines'])[0] and (tag, kr) not in opts:
                    opts.append((tag, kr))
                    break
        if opts: cand[uid] = opts
    for uid, u in units_v1.items():
        if not u['src'].startswith('msgsec') or uid in cand: continue
        kr = tr1.get(uid)
        if kr is None: continue
        base = trim(fix(kr))
        variants = [fix(formal_ui.formalize(u['src'], base)), base]
        for candidate in variants:
            if krtools.check_translation(candidate, u['lines'])[0]:
                cand[uid] = [('v1', candidate)]
                budgets_of[uid] = u['lines']
                break

    sylls = set()
    for opts in cand.values():
        for _, kr in opts: sylls |= krtools.used_syllables(kr)

    # ---- common.snr: use the SAFE field list (halfwidth-kana bytes there are
    # binary record data, not text; v1.0-v1.4 overwrote them and scrambled busho
    # records, e.g. face indices). Only genuine null-terminated SJIS fields. ----
    snr_safe = json.load(open(_os.path.join(WORK, 'snr_units_safe.json'), encoding='utf-8'))
    kr_by_off = {}
    for uid, u in units_v1.items():
        if u['src'] != 'common.snr': continue
        kr = tr1.get(uid)
        if kr is not None:
            kr_by_off[u['off']] = fix(kr)

    inplace = {}
    key = 0
    for s in snr_safe:
        kr = kr_by_off.get(s['off'])
        if kr is None: continue
        u = {'src': 'common.snr', 'off': s['off'], 'len': s['len'],
             'cap': s['cap'], 'lines': [s['cap']]}
        if krtools.check_translation(kr, u['lines'])[0]:
            inplace[('snr', key)] = (u, kr)
            sylls |= krtools.used_syllables(kr)
            key += 1
    print(f'common.snr safe fields: {len(snr_safe)}, translated: {len(inplace)}')

    for uid, u in units_v1.items():
        if u['src'] != 'arm9.bin': continue
        kr = tr1.get(uid)
        if kr is None: continue
        kr = fix(kr)
        if krtools.check_translation(kr, u['lines'])[0]:
            inplace[('arm9', uid)] = (u, kr)
            sylls |= krtools.used_syllables(kr)

    c2i = krtools.load_code2idx()

    # Hangul rides in kanji glyph slots, so a slot whose kanji is STILL printed
    # somewhere shows that kanji as a random syllable - the "깨짐" players see
    # (織田家 -> "오다덕", 急襲 -> "색襲").  Count how often each kanji survives
    # untranslated and hand out the least-used slots first, so the collisions
    # that remain are on characters the game hardly ever prints.
    still_used = collections.Counter()
    def note(text, weight=1):
        for ch in text or '':
            try: b = ch.encode('shift_jis')
            except Exception: continue
            if len(b) == 2:
                code = (b[0] << 8) | b[1]
                if c2i.get(code, 0) >= 351: still_used[code] += weight

    # Every kanji the game can still print gets weighted so it keeps its glyph.
    # Text we replace is weighted 1 (it only shows if the translation is
    # rejected); text we do NOT replace, and characters the game composes at
    # runtime, are weighted heavily so they are never repainted.
    RUNTIME = ('家氏城殿様国年月日春夏秋冬'
               '一二三四五六七八九十百千万'
               '東西南北中大小上下前後内外'
               '郎助兵衛守')
    note(RUNTIME, 10_000)
    done_snr = {u['off'] for u, _ in inplace.values() if u.get('src') == 'common.snr'}
    for uid, u in units_v1.items():
        src = u['src']
        if src == 'common.snr':
            # a name field that fails to fit is printed as the original kanji,
            # and these are short strings the game splices together
            note(u['jp'], 1 if u['off'] in done_snr else 100)
        elif src == 'arm9.bin':
            note(u['jp'], 1 if ('arm9', uid) in inplace else 100)
        else:
            note(u['jp'], 1 if uid in cand else 100)
    for uid, u in units_v2.items():
        note(u['jp'], 1 if uid in cand else 100)

    slots = [c for c, i in sorted(c2i.items()) if i >= 351]
    untouched = sum(1 for c in slots if c not in still_used)
    slots.sort(key=lambda c: (still_used.get(c, 0), c))
    pool = slots
    assert len(sylls) <= len(pool), f'pool exceeded {len(sylls)}'
    taken = pool[:len(sylls)]
    hard = sum(1 for c in taken if still_used.get(c, 0) >= 100)
    print(f'glyph slots {len(slots)}: never-printed {untouched}, '
          f'syllables {len(sylls)}, slots taken that still print kanji: {hard}')
    smap = {s: pool[i] for i, s in enumerate(sorted(sylls))}
    json.dump({s: hex(c) for s, c in smap.items()},
              open(_os.path.join(WORK, 'syllable_map.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=0)

    arm9 = bytearray(open(_os.path.join(WORK, 'bin', 'arm9.bin'), 'rb').read())
    for s, code in smap.items():
        i = c2i[code]
        arm9[FONT_OFF + i*18: FONT_OFF + i*18 + 18] = krtools.rows_to_bytes(krtools.render_glyph12(s))
    # Minimal-write policy: emit the translation plus ONE null terminator and
    # leave every other byte of the field untouched, so an over-estimated
    # capacity can never clobber neighbouring binary data.
    snr = bytearray(open(_os.path.join(WORK, 'fs', 'scenario', 'common.snr'), 'rb').read())
    for uid, (u, kr) in inplace.items():
        enc = krtools.encode_line(kr.replace('{BR}', ''), smap)
        cap = u['lines'][0]
        if len(enc) > cap:
            continue
        buf = arm9 if u['src'] == 'arm9.bin' else snr
        off = u['off']
        buf[off: off + len(enc)] = enc
        # terminator: only needed when the translation is shorter than the field's
        # text area; at exactly cap the original terminator already follows.
        if len(enc) < cap:
            buf[off + len(enc)] = 0
    print(f'font glyphs {len(smap)}, in-place units {len(inplace)}')

    manifest = json.load(open(_os.path.join(WORK, 'manifest.json')))
    msg_sizes = {os.path.basename(f['path']): f['size']
                 for f in manifest['files'] if '/msg/msgsec' in f['path']}
    # The loader reads a whole msgsec file into a pre-allocated buffer with no
    # length clamp, so the file must fit that buffer. The largest original file
    # is 16137 = 0x3F09, i.e. the buffer is a 0x4000 (16 KiB) block; 0x4000 is
    # therefore the true ceiling, not the largest original file.
    # 0x4000 would be the natural block size, but the buffer may have been sized
    # from the largest file (16137 -> 16160 after the allocator's 32-byte
    # rounding). Only "<= largest original file" is PROVEN loadable, so that is
    # the ceiling we use; the quality budget is maximised inside it instead.
    MAX_ORIG = max(msg_sizes.values())
    print(f'proven-safe message ceiling = {MAX_ORIG} bytes')

    by_src = msg_rebuild.load_units()
    new_files = {}
    selected_formal = []
    stats = {'v2': 0, 'v3': 0, 'v1': 0, 'jp': 0}
    demoted = []
    for name in sorted(by_src):
        data = open(_os.path.join(WORK, 'fs', 'msg') + '\\' + name, 'rb').read()
        orig_size = len(data)
        cap = MAX_ORIG
        units = by_src[name]
        choice = {u['id']: (0 if u['id'] in cand else None) for u in units}

        def build(ch):
            texts = {}
            for u in units:
                ci = ch.get(u['id'])
                if ci is None: continue
                _, kr = cand[u['id']][ci]
                texts[u['id']] = enc_unit(kr, budgets_of[u['id']], smap)
            return msg_rebuild.rebuild(name, data, units, texts), texts

        nf, texts = build(choice)
        demotions = 0
        # Demote in order of SMALLEST relative quality loss, not largest byte
        # gain: shaving many nearly-equivalent lines preserves the big, genuinely
        # better expansions (which is the whole point of the quality pass).
        # Keep fragments whose grammatical suffixes are supplied by runtime
        # composition. Demoting one silently recreates the reported UI defects:
        # a particle or space disappears, "...처우를" is shortened, or
        # "국에 명령" falls back to a clipped command. They cost only a few
        # bytes; the normal ranking still handles the rest of the file.
        LOCKED = {118, 132, 133, 134, 135, 189,
                  1145, 1147, 1555, 2210, 2212,
                  2425, 2428, 2431, 2455,
                  # Issue #7's fixed-width records must keep their formal
                  # candidate even when the section is trimmed to the
                  # proven-safe ceiling.  Without this, the size pass can
                  # silently demote a corrected sentence back to its raw
                  # informal fallback.
                  1975, 2109, 2110, 2150, 2166, 2167, 2190,
                  2486, 2497, 3112, 3162, 3204, 3209, 3232,
                  3380, 3406, 3428, 3430}
        while len(nf) > cap:
            need = len(nf) - cap
            ranked = []
            for u in units:
                ci = choice.get(u['id'])
                if ci is None or u['id'] in LOCKED: continue
                cur = len(texts[u['id']])
                opts = cand[u['id']]
                nxt = None
                if ci + 1 < len(opts):
                    try: nxt = len(enc_unit(opts[ci+1][1], budgets_of[u['id']], smap))
                    except Exception: nxt = None
                if nxt is None: nxt = u['len']
                gain = cur - nxt
                if gain <= 0: continue
                ranked.append((gain / max(cur, 1), gain, u['id']))
            if not ranked: break
            ranked.sort()                      # least relative loss first
            saved = 0
            for ratio, gain, uid2 in ranked:
                opts = cand[uid2]
                choice[uid2] = choice[uid2] + 1 if choice[uid2] + 1 < len(opts) else None
                demotions += 1
                saved += gain
                if saved >= need:
                    break
            nf, texts = build(choice)
        assert len(nf) <= cap, f'{name}: {len(nf)} > cap {cap}'
        new_files['/msg/' + name] = nf
        for u in units:
            ci = choice.get(u['id'])
            selected_formal.append({
                'id': u['id'],
                'src': name,
                'jp': u['jp'],
                'tag': 'jp' if ci is None else cand[u['id']][ci][0],
                'kr': None if ci is None else cand[u['id']][ci][1],
            })
            stats['jp' if ci is None else cand[u['id']][ci][0]] += 1
            # record units that had to fall back, with the byte budget they must
            # respect, so a dedicated "natural but concise" pass can replace them
            if ci is not None and cand[u['id']][ci][0] == 'v1' and u['id'] in tr2:
                cur = texts.get(u['id'])
                if cur is None: continue
                lines_b = [len(x) for x in cur.split(b'\x0A')]
                demoted.append({'id': u['id'], 'src': name,
                                'jp': units_v2[u['id']]['jp'] if u['id'] in units_v2 else u['jp'],
                                'kr_short': cand[u['id']][ci][1],
                                'kr_long': trim(fix(tr2[u['id']])),
                                'lines': lines_b})
        grow = len(nf) - orig_size
        print(f'  {name}: {orig_size} -> {len(nf)} ({grow:+d}, demotions={demotions})')
    print('msgsec unit sources:', stats)
    json.dump(selected_formal,
              open(_os.path.join(WORK, 'formal_ui_selected.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=0)
    json.dump(demoted, open(_os.path.join(WORK, 'demoted.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=0)
    print('units needing a concise-but-natural rewrite:', len(demoted))

    # ---- graphics: label-translated .dat files (same size, pixel data only) ----
    gfx_dir = _os.path.join(WORK, 'fs_gfx', 'obj')
    gfx_files = {}
    if os.path.isdir(gfx_dir):
        for fn in sorted(os.listdir(gfx_dir)):
            gfx_files['/obj/' + fn] = open(os.path.join(gfx_dir, fn), 'rb').read()
    print('graphics files patched:', len(gfx_files))

    # ---- title background: remove the baked-in Japanese prompt from the
    #     lower title screen.  The clean reference is quantised to the
    #     existing 8bpp palette, then written through the CSK codec without
    #     changing GrpBGInfo offsets or the resource size. -----------------
    bg_path = _os.path.join(WORK, 'fs', 'bg', 'GrpBG.dat')
    bg_info_path = _os.path.join(WORK, 'fs', 'bg', 'GrpBGInfo.dat')
    bg_files = {}
    if os.path.exists(bg_path) and os.path.exists(bg_info_path):
        bg_data = open(bg_path, 'rb').read()
        bg_info = open(bg_info_path, 'rb').read()
        reference = _os.path.join(DATA, 'reference', 'title_bottom_clean.png')
        patched_bg, bg_stats = bg_patch.patch_title_bottom(
            bg_data, bg_info, reference)
        patched_bg, banner_stats = bg_labels.patch_banners(
            patched_bg, bg_info, DATA, FONT)
        bg_files['/bg/GrpBG.dat'] = patched_bg
        print('title background patched:', bg_stats)
        print(f'background banners patched: {len(banner_stats)}')
    else:
        raise SystemExit('GrpBG source files are missing; cannot apply issue #4 fix')

    # ---- ROM assembly: keep everything in place; relocate only grown files to the tail ----
    rom = bytearray(open(ROM_IN, 'rb').read())
    rom[ARM9_ROM_OFF: ARM9_ROM_OFF + len(arm9)] = arm9
    fat_off = manifest['fat_off']
    used_end = struct.unpack_from('<I', rom, 0x80)[0]
    tail = (used_end + 0x1FF) & ~0x1FF
    moved = 0
    for f in manifest['files']:
        p = f['path']
        if p == '/scenario/common.snr':
            assert len(snr) == f['size']
            rom[f['start']: f['start'] + len(snr)] = snr
            continue
        if p in gfx_files:
            g = gfx_files[p]
            assert len(g) == f['size'], f'{p}: graphics size changed'
            rom[f['start']: f['start'] + len(g)] = g
            continue
        if p in bg_files:
            g = bg_files[p]
            assert len(g) == f['size'], f'{p}: background size changed'
            rom[f['start']: f['start'] + len(g)] = g
            continue
        if p not in new_files:
            continue
        d = new_files[p]
        if len(d) <= f['size']:
            rom[f['start']: f['start'] + len(d)] = d
            if len(d) < f['size']:
                rom[f['start'] + len(d): f['start'] + f['size']] = b'\x00' * (f['size'] - len(d))
            struct.pack_into('<II', rom, fat_off + f['id']*8, f['start'], f['start'] + len(d))
        else:
            start = tail
            end = start + len(d)
            assert end <= len(rom), 'ROM tail exhausted'
            rom[start:end] = d
            struct.pack_into('<II', rom, fat_off + f['id']*8, start, end)
            rom[f['start']: f['start'] + f['size']] = b'\xFF' * f['size']   # free old slot
            tail = (end + 0x1FF) & ~0x1FF
            moved += 1
    new_used = max(used_end, tail)
    struct.pack_into('<I', rom, 0x80, new_used)
    struct.pack_into('<H', rom, 0x15E, crc16(rom[:0x15E]))
    open(ROM_OUT, 'wb').write(rom)
    print(f'relocated files: {moved}, used 0x{used_end:X} -> 0x{new_used:X}')
    print('ROM written:', ROM_OUT)

if __name__ == '__main__':
    main()
