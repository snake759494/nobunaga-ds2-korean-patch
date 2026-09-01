# -*- coding: utf-8 -*-
"""Verify v1.13: only intended ARM9/text/graphics/background regions, msg FAT
entries, header used-size+CRC, and the previously-unused ROM tail may differ."""
import json, struct, os
import os as _os, sys as _sys
_sys.path[:0] = [_os.path.dirname(_os.path.abspath(__file__)),
                _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..')]
from nobu2_paths import ROM_IN, ROM_OUT, WORK, FONT, DATA

a = open(ROM_IN, 'rb').read()
b = open(ROM_OUT, 'rb').read()
manifest = json.load(open(_os.path.join(WORK, 'manifest.json')))
fat_off = manifest['fat_off']
fnt_off, fnt_size = struct.unpack_from('<II', a, 0x40)
orig_used = struct.unpack_from('<I', a, 0x80)[0]

print('sizes equal:', len(a) == len(b))
print('FNT identical:', a[fnt_off:fnt_off+fnt_size] == b[fnt_off:fnt_off+fnt_size])
print('arm7 identical:', a[0x1A5200:0x1A5200+0x26F28] == b[0x1A5200:0x1A5200+0x26F28])

msg_ids = {f['id'] for f in manifest['files'] if '/msg/msgsec' in f['path']}
allowed = [(0x4000, 0x4000 + 0x1A1098)]                    # arm9
allowed.append((0x80, 0x84))                                # used size
allowed.append((0x15E, 0x160))                              # header CRC
allowed.append((orig_used, len(a)))                         # previously unused tail
gfx_dir = _os.path.join(WORK, 'fs_gfx', 'obj')
gfx_names = set(os.listdir(gfx_dir)) if os.path.isdir(gfx_dir) else set()
for f in manifest['files']:
    p = f['path']
    if p.startswith('/obj/') and os.path.basename(p) in gfx_names:
        allowed.append((f['start'], f['start'] + f['size']))  # label-translated graphics
    if p == '/bg/GrpBG.dat':
        allowed.append((f['start'], f['start'] + f['size']))  # CSK title-screen fix
    if '/msg/msgsec' in p or p == '/scenario/common.snr':
        allowed.append((f['start'], f['start'] + f['size']))  # old slot (rewritten or freed)
    if f['id'] in msg_ids:
        allowed.append((fat_off + f['id']*8, fat_off + f['id']*8 + 8))
allowed.sort()

def in_allowed(i):
    import bisect
    j = bisect.bisect_right(allowed, (i, 1 << 62)) - 1
    return j >= 0 and allowed[j][0] <= i < allowed[j][1]

runs, i, n = [], 0, len(a)
while i < n:
    if a[i] != b[i]:
        j = i
        while j < n and a[j] != b[j]: j += 1
        runs.append((i, j)); i = j
    else:
        i += 1
outside = [(s, e) for s, e in runs if not in_allowed(s)]
print(f'diff runs: {len(runs)}, outside allowed: {len(outside)}')
for s, e in outside[:8]:
    print(f'  0x{s:X}-0x{e:X}')

# every non-msg file byte-identical at its original offset?
bad = []
for f in manifest['files']:
    if f['id'] in msg_ids or f['path'] == '/scenario/common.snr':
        continue
    if f['path'].startswith('/obj/') and os.path.basename(f['path']) in gfx_names:
        continue
    if f['path'] == '/bg/GrpBG.dat':
        continue
    s, sz = f['start'], f['size']
    if a[s:s+sz] != b[s:s+sz]:
        bad.append(f['path'])
print('non-msg files changed:', len(bad), bad[:5])

# FAT sanity: every entry points to a valid, in-bounds, non-overlapping region
ents = []
for f in manifest['files']:
    s, e = struct.unpack_from('<II', b, fat_off + f['id']*8)
    assert 0 < s < e <= len(b), f"bad FAT {f['path']} {s:#x}-{e:#x}"
    ents.append((s, e, f['path']))
ents.sort()
ov = [(ents[k], ents[k+1]) for k in range(len(ents)-1) if ents[k][1] > ents[k+1][0]]
print('FAT entries:', len(ents), 'overlaps:', len(ov))
for x, y in ov[:3]: print('  overlap', x, y)
print('new used size: 0x%X (orig 0x%X)' % (struct.unpack_from('<I', b, 0x80)[0], orig_used))
