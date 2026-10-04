# -*- coding: utf-8 -*-
"""Static verification for the CSK title-screen fix (issue #4).

This deliberately does not launch an emulator.  It proves that the patched
resource still has the original block table, that every non-target block is
byte-identical, and that the target block decodes to the supplied clean
256x192 reference through its original palette and map.
"""
from __future__ import annotations

import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nobu2_paths import DATA, ROM_OUT, WORK
import bg_csk
import bg_labels
import bg_patch


def check_banner(old_block: bytes, new_block: bytes, entry: dict) -> int:
    """A banner may only repaint the pixels inside its own plate rectangle.

    The palette, the tile map and every pixel outside the rectangle have to
    come out of the codec exactly as they went in, which is what keeps a
    caption from leaking into the artwork around it.
    """
    old_payload, _ = bg_csk.decode_block(old_block)
    new_payload, stream_end = bg_csk.decode_block(new_block)
    assert len(old_payload) == len(new_payload)
    assert new_payload[:bg_patch.CHAR_OFFSET] == old_payload[:bg_patch.CHAR_OFFSET], (
        f"block {entry['block']}: palette or map changed")
    assert struct.unpack_from("<I", new_block, 8)[0] == stream_end
    before = bg_patch.screen_indices(old_payload)
    after = bg_patch.screen_indices(new_payload)
    x0, y0, w, h = entry["plate"]
    changed = 0
    for y in range(bg_patch.SCREEN_HEIGHT):
        for x in range(bg_patch.SCREEN_WIDTH):
            i = y * bg_patch.SCREEN_WIDTH + x
            if before[i] == after[i]:
                continue
            assert x0 <= x < x0 + w and y0 <= y < y0 + h, (
                f"block {entry['block']}: pixel ({x}, {y}) changed outside the plate")
            changed += 1
    assert changed, f"block {entry['block']}: nothing changed"
    print(f"banner block {entry['block']}: {entry['jp']} -> {entry['kr']}, "
          f"{changed} pixels inside {entry['plate']}")
    return 1


def main() -> None:
    manifest = json.load(open(os.path.join(WORK, "manifest.json"), encoding="utf-8"))
    entry = next(f for f in manifest["files"] if f["path"] == "/bg/GrpBG.dat")
    info = open(os.path.join(WORK, "fs", "bg", "GrpBGInfo.dat"), "rb").read()
    original = open(os.path.join(WORK, "fs", "bg", "GrpBG.dat"), "rb").read()
    rom = open(ROM_OUT, "rb").read()
    patched = rom[entry["start"]:entry["start"] + entry["size"]]
    assert len(original) == len(patched) == entry["size"]

    banners = {int(e["block"]): e for e in bg_labels.manifest(DATA)}
    count = struct.unpack_from("<I", info, 0)[0]
    target_changed = False
    banners_seen = 0
    for index in range(count):
        offset, size = struct.unpack_from("<II", info, 8 + index * 8)
        old_block = original[offset:offset + size]
        new_block = patched[offset:offset + size]
        if index in banners:
            banners_seen += check_banner(old_block, new_block, banners[index])
            continue
        if index != bg_patch.TITLE_BOTTOM_BLOCK:
            assert old_block == new_block, f"unexpected GrpBG block change: {index}"
            continue
        old_payload, _ = bg_csk.decode_block(old_block)
        new_payload, stream_end = bg_csk.decode_block(new_block)
        assert new_payload[:bg_patch.CHAR_OFFSET] == old_payload[:bg_patch.CHAR_OFFSET]
        assert new_payload != old_payload
        assert struct.unpack_from("<I", new_block, 8)[0] == stream_end
        target = bg_patch.quantise_reference(
            new_payload,
            os.path.join(DATA, "reference", "title_bottom_clean.png"),
        )
        assert bg_patch.screen_indices(new_payload) == target
        target_changed = True
        print(
            "title block:", index,
            "decoded:", len(new_payload),
            "compressed stream:", stream_end,
            "changed payload bytes:",
            sum(a != b for a, b in zip(old_payload, new_payload)),
        )
    assert target_changed
    assert banners_seen == len(banners), (
        f"only {banners_seen} of {len(banners)} background banners changed")
    assert open(os.path.join(WORK, "fs", "bg", "GrpBGInfo.dat"), "rb").read() == info
    print("GrpBGInfo unchanged; non-target blocks byte-identical; title reference matches")


if __name__ == "__main__":
    main()
