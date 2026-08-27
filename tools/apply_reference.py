# -*- coding: utf-8 -*-
"""Apply the terminology and province-name corrections from the reference docs.

The fixed-width name field in common.snr is 4 bytes - two Korean syllables.
A Japanese reading does not fit, so it was being truncated, and different
provinces collapsed onto the same string: 山城 and 大和 both showed as '야마',
石見/岩代/磐城 all as '이와'. Two hanja read as two Sino-Korean syllables fit
the field exactly and stay distinct, so that is what the field gets.

Prose is left alone on purpose: '가이호 유쇼' is a person and '미미카와' is a
river, so blanket string replacement there corrupts text. Only whole-field
names and unambiguous game terms are rewritten.

Usage: python tools/apply_reference.py [--dry-run]
"""
import os, sys, json, glob, collections
sys.stdout.reconfigure(encoding='utf-8')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, 'data')
REF = os.path.join(DATA, 'reference')
DRY = '--dry-run' in sys.argv

prov = json.load(open(os.path.join(REF, 'ryoseikoku.json'), encoding='utf-8'))['map']
gl = json.load(open(os.path.join(REF, 'glossary_fix.json'), encoding='utf-8'))

# hanja -> new korean, for whole-field replacement in common.snr
FIELD = {jp: v[0] for jp, v in prov.items()}
for jp, new, old, why in gl['tactics']:
    FIELD[jp] = new
for jp, new, old, why in gl['menu']:
    FIELD[jp] = new

# korean -> korean, for unambiguous words inside message text.
# Deliberately excludes 배반/적대/공물/절교/수비/축성: in prose those are
# ordinary words, not the command names, and rewriting them would be wrong.
TEXT = {
    '석고': '농업', '병수': '병력', '합전': '전쟁',
    '미카와혼': '삼하혼', '월벽': '벽월', '창벽': '창금',
    '불화살': '화시', '만궁': '궁구', '화살비': '시우',
    '국파괴': '국붕', '척탄': '투배락',
}

def load_units():
    u = {x['id']: x for x in json.load(open(os.path.join(DATA, 'units.json'), encoding='utf-8'))}
    for extra in ('units_extra.json', 'units_extra2.json', 'units_extra3.json'):
        p = os.path.join(DATA, extra)
        if os.path.exists(p):
            for x in json.load(open(p, encoding='utf-8')): u[x['id']] = x
    return u

def fits(kr, cap):
    return len(kr.encode('utf-16-le')) // 2 * 2 <= cap    # 2 bytes per syllable

def main():
    units = load_units()
    stats = collections.Counter()
    detail = collections.defaultdict(set)

    for sub in ('out', 'out2', 'out3'):
        for path in sorted(glob.glob(os.path.join(DATA, 'translations', sub, 'out_*.json'))):
            items = json.load(open(path, encoding='utf-8'))
            dirty = False
            for it in items:
                uid, kr = it['id'], it.get('kr', '')
                u = units.get(uid)
                if not kr or not u:
                    continue
                jp = u.get('jp', '')
                # 1. whole-field names and terms
                if u['src'] == 'common.snr' and jp in FIELD:
                    new = FIELD[jp]
                    if new != kr and len(new) * 2 <= u['cap']:
                        detail['field'].add(f'{jp}: {kr} -> {new}')
                        it['kr'] = new; dirty = True; stats['field'] += 1
                        continue
                # 2. unambiguous words inside text
                new = kr
                for a, b in TEXT.items():
                    if a in new:
                        new = new.replace(a, b)
                if new != kr and len(new) <= len(kr):
                    for a, b in TEXT.items():
                        if a in kr: detail['text'].add(f'{a} -> {b}')
                    it['kr'] = new; dirty = True; stats['text'] += 1
            if dirty and not DRY:
                json.dump(items, open(path, 'w', encoding='utf-8'),
                          ensure_ascii=False, indent=1)

    # 3. graphics labels
    LABEL = {jp: new for jp, new, old, why in gl['menu']}
    LABEL.update({jp: new for jp, new, old, why in gl['tactics']})
    # the image triage mis-read some Japanese; fix the source text too
    MISREAD = {wrong: (right, kr) for wrong, right, kr, why in gl.get('label_misread', [])}
    for path in sorted(glob.glob(os.path.join(DATA, 'gfxlabels', '*.json'))):
        try:
            items = json.load(open(path, encoding='utf-8-sig'))
        except Exception:
            continue
        dirty = False
        for it in items:
            jp = (it.get('jp') or '').strip()
            if jp in MISREAD:
                right, kr = MISREAD[jp]
                detail['label'].add(f'{jp}(오독) -> {right}: {it.get("kr")} -> {kr}')
                it['jp'], it['kr'] = right, kr
                dirty = True; stats['label'] += 1
                continue
            if jp in LABEL and it.get('kr') != LABEL[jp]:
                detail['label'].add(f"{jp}: {it.get('kr')} -> {LABEL[jp]}")
                it['kr'] = LABEL[jp]; dirty = True; stats['label'] += 1
        if dirty and not DRY:
            json.dump(items, open(path, 'w', encoding='utf-8'),
                      ensure_ascii=False, indent=1)

    print(('DRY RUN - ' if DRY else '') +
          f"name/term fields: {stats['field']}, text units: {stats['text']}, "
          f"graphics labels: {stats['label']}")
    for k in ('field', 'label', 'text'):
        if detail[k]:
            print(f'\n{k} ({len(detail[k])} distinct):')
            for line in sorted(detail[k]): print('   ', line)

if __name__ == '__main__':
    main()
