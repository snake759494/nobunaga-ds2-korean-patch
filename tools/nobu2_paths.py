# -*- coding: utf-8 -*-
"""Every path the toolchain uses, in one place.

The tools were written against one machine; this module is what makes them
portable.  Nothing here needs editing for a normal build - point NOBU2_ROM at
your own dump and the rest follows.

Environment overrides:
  NOBU2_ROM   path to the Japanese ROM        (default: rom/nobu2-jp.nds)
  NOBU2_OUT   path to write the patched ROM   (default: rom/nobu2-kr.nds)
  NOBU2_WORK  scratch directory               (default: _work)
  NOBU2_FONT  Galmuri11.ttf                   (default: fonts/Galmuri11.ttf)
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _p(env, *rel):
    v = os.environ.get(env)
    return os.path.abspath(v) if v else os.path.join(REPO, *rel)

ROM_IN  = _p('NOBU2_ROM',  'rom', 'nobu2-jp.nds')
ROM_OUT = _p('NOBU2_OUT',  'rom', 'nobu2-kr.nds')
WORK    = _p('NOBU2_WORK', '_work')
FONT    = _p('NOBU2_FONT', 'fonts', 'Galmuri11.ttf')
DATA    = os.path.join(REPO, 'data')
PATCH   = os.path.join(REPO, 'nobu2-kr.xdelta')

# CRC32 of the ROM this patch was built against, and of the result.
ROM_CRC = 0x72C536BA
OUT_CRC = 0x24C70E29

def check_rom():
    """fail early and clearly rather than producing a broken ROM"""
    import zlib
    if not os.path.exists(ROM_IN):
        raise SystemExit(
            f'ROM not found: {ROM_IN}\n'
            f'Put your own dump there, or set NOBU2_ROM=/path/to/rom.nds')
    crc = zlib.crc32(open(ROM_IN, 'rb').read()) & 0xFFFFFFFF
    if crc != ROM_CRC:
        raise SystemExit(
            f'ROM CRC32 mismatch: got {crc:08X}, expected {ROM_CRC:08X}\n'
            f'This patch targets "Nobunaga no Yabou DS 2 (Japan)" (CN2J).')
    return crc
