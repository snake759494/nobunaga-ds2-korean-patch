# -*- coding: utf-8 -*-
"""Verify the selected ordinary UI text uses the requested formal style.

``patch_build4.py`` records the exact candidate chosen after byte-budget
demotions.  Checking that record catches a regression that a source-only
grep misses: a formal candidate can be rejected for one fixed-width line and
silently fall back to an older informal candidate.  Scenario prose and the
compact busho-description sections are outside the formal-source set by
design.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import formal_ui
from nobu2_paths import WORK


# These are sentence-ending forms, not arbitrary syllables inside a name or a
# noun.  A full-width Japanese punctuation mark is retained by the game and
# is included in the look-ahead for the same reason as ASCII '?'/'!'.
BAD_ENDINGS = (
    ('polite-informal', re.compile(
        r'(?:세요|어요|아요|죠|나요|까요|해요|돼요|있어요|없어요)(?=[！。！？…?]|\{BR\}|$)')),
    ('archaic', re.compile(
        r'(?:하오|이오|지오|라오|오리까|소이다|주소서|주오|주시오|소서|겠소|옵소서)(?=[！。！？…?]|\{BR\}|$)')),
    ('imperative-informal', re.compile(
        r'(?:하라|어라|여라|마라)(?=[！。！？…?]|\{BR\}|$)')),
    ('plain-narrative', re.compile(
        r'(?:구나|다네|네|것이다|겠다|이다|한다|된다|있다|없다)(?=[！。！？…?]|\{BR\}|$)')),
    ('question-informal', re.compile(
        # ``입니다？``/``습니다？`` are already formal; their final syllable
        # also happens to be 다, so exclude the preceding 니.
        r'(?:나|냐|가|(?<!니)다)(?=[？?])')),
)


def main():
    path = os.path.join(WORK, 'formal_ui_selected.json')
    if not os.path.exists(path):
        raise SystemExit(f'missing builder audit record: {path}')
    rows = json.load(open(path, encoding='utf-8'))
    checked = 0
    violations = []
    for row in rows:
        if row.get('src') not in formal_ui.FORMAL_SOURCES:
            continue
        text = row.get('kr')
        if not text:
            continue
        checked += 1
        normalized = formal_ui.formalize(row['src'], text)
        if normalized != text:
            violations.append((row['id'], row['src'], 'not-idempotent', text, normalized))
            continue
        for label, pattern in BAD_ENDINGS:
            match = pattern.search(text)
            if match:
                violations.append((row['id'], row['src'], label, text, match.group()))
                break
    print(f'formal UI records checked: {checked}')
    if violations:
        for row in violations:
            print('  violation:', row)
        raise SystemExit(f'formal UI violations: {len(violations)}')
    print('formal UI endings: OK')


if __name__ == '__main__':
    main()
