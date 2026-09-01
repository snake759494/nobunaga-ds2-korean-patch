#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the Korean ROM from your own Japanese dump.

    python build.py                # everything
    python build.py --steps 4,5    # re-run only some steps

Steps
  1 check    verify the ROM is the right dump (CRC32)
  2 extract  unpack the filesystem, ARM9/ARM7 and the FAT manifest
  3 stage    copy the shipped translation data into the work directory
  4 graphics redraw the Japanese sprite labels in Hangul
  5 assemble build the font, encode the text, write the patched ROM
  6 verify   prove the ROM only changed where it was supposed to
  7 patch    emit nobu2-kr.xdelta for distribution

Nothing here needs a network connection or the original author's machine.
"""
import os, sys, shutil, subprocess, zlib, argparse

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(REPO, 'tools'))
from nobu2_paths import ROM_IN, ROM_OUT, WORK, FONT, DATA, PATCH, ROM_CRC, OUT_CRC

PY = sys.executable
TOOLS = os.path.join(REPO, 'tools')
GFX = os.path.join(TOOLS, 'gfx')

def run(script, *args, cwd=None):
    r = subprocess.run([PY, script, *args], cwd=cwd)
    if r.returncode != 0:
        raise SystemExit(f'FAILED: {os.path.basename(script)}')

def head(n, title):
    print(f'\n=== {n}. {title} ' + '=' * max(0, 52 - len(title)))

# ---------------------------------------------------------------- steps

def step1_check():
    head(1, 'check the ROM')
    if not os.path.exists(ROM_IN):
        raise SystemExit(
            f'ROM not found at {ROM_IN}\n'
            f'Place your own dump of "Nobunaga no Yabou DS 2 (Japan)" there,\n'
            f'or run with NOBU2_ROM=/path/to/your.nds')
    crc = zlib.crc32(open(ROM_IN, 'rb').read()) & 0xFFFFFFFF
    print(f'  {os.path.basename(ROM_IN)}  CRC32 {crc:08X}', end='  ')
    if crc != ROM_CRC:
        raise SystemExit(f'\n  expected {ROM_CRC:08X} - this is a different dump.')
    print('OK')
    if not os.path.exists(FONT):
        raise SystemExit(f'Font not found: {FONT}')

def step2_extract():
    head(2, 'extract the ROM')
    os.makedirs(WORK, exist_ok=True)
    run(os.path.join(TOOLS, 'nds_extract.py'))

def step3_stage():
    head(3, 'stage the translation data')
    os.makedirs(WORK, exist_ok=True)
    for fn in ('units.json', 'units_v2.json', 'snr_units_safe.json',
               'code2idx.json',
               'units_extra.json', 'units_extra2.json', 'units_extra3.json'):
        src = os.path.join(DATA, fn)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(WORK, fn))
    tr = os.path.join(WORK, 'tr')
    for sub in ('out', 'out2', 'out3'):
        dst = os.path.join(tr, sub)
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(os.path.join(DATA, 'translations', sub), dst)
    for name, src in (('gfxlabels', os.path.join(DATA, 'gfxlabels')),
                      ('gfxdump', os.path.join(DATA, 'cells'))):
        dst = os.path.join(WORK, name)
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst)
    n = sum(len(os.listdir(os.path.join(tr, s))) for s in ('out', 'out2', 'out3'))
    print(f'  {n} translation files, '
          f'{len(os.listdir(os.path.join(WORK, "gfxlabels")))} label files')

def step4_graphics():
    head(4, 'redraw the sprite labels')
    out = os.path.join(WORK, 'fs_gfx', 'obj')
    shutil.rmtree(os.path.join(WORK, 'fs_gfx'), ignore_errors=True)
    os.makedirs(out, exist_ok=True)
    run(os.path.join(GFX, 'apply_all.py'))

def step5_assemble():
    head(5, 'assemble the ROM')
    os.makedirs(os.path.dirname(ROM_OUT), exist_ok=True)
    run(os.path.join(TOOLS, 'patch_build4.py'))

def step6_verify():
    head(6, 'verify')
    run(os.path.join(TOOLS, 'verify_snr_safe.py'))
    run(os.path.join(TOOLS, 'verify_formal_ui.py'))
    run(os.path.join(TOOLS, 'verify_bg_patch.py'))
    run(os.path.join(TOOLS, 'verify_layout2.py'))
    run(os.path.join(GFX, 'check_damage.py'))
    crc = zlib.crc32(open(ROM_OUT, 'rb').read()) & 0xFFFFFFFF
    print(f'  patched CRC32 {crc:08X}', end='  ')
    print('(matches the published release)' if crc == OUT_CRC
          else f'(reference build is {OUT_CRC:08X} - differs, see BUILD.md)')

def step7_patch():
    head(7, 'write the xdelta patch')
    try:
        import pyxdelta
    except ImportError:
        print('  pyxdelta not installed - skipping (pip install pyxdelta)')
        return
    ok = pyxdelta.run(ROM_IN, ROM_OUT, PATCH)
    print(f'  {PATCH}  {os.path.getsize(PATCH)} bytes  ok={ok}')

STEPS = [step1_check, step2_extract, step3_stage, step4_graphics,
         step5_assemble, step6_verify, step7_patch]

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--steps', help='comma separated step numbers, e.g. 4,5,6')
    a = ap.parse_args()
    want = ([int(x) for x in a.steps.split(',')] if a.steps
            else list(range(1, len(STEPS) + 1)))
    print(f'ROM in   {ROM_IN}\nROM out  {ROM_OUT}\nwork     {WORK}')
    for i in want:
        STEPS[i - 1]()
    print(f'\nDone. Patched ROM: {ROM_OUT}')

if __name__ == '__main__':
    main()
