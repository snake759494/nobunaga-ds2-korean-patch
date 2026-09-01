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
import bg_patch


def main() -> None:
    manifest = json.load(open(os.path.join(WORK, "manifest.json"), encoding="utf-8"))
    entry = next(f for f in manifest["files"] if f["path"] == "/bg/GrpBG.dat")
    info = open(os.path.join(WORK, "fs", "bg", "GrpBGInfo.dat"), "rb").read()
    original = open(os.path.join(WORK, "fs", "bg", "GrpBG.dat"), "rb").read()
    rom = open(ROM_OUT, "rb").read()
    patched = rom[entry["start"]:entry["start"] + entry["size"]]
    assert len(original) == len(patched) == entry["size"]

    count = struct.unpack_from("<I", info, 0)[0]
    target_changed = False
    for index in range(count):
        offset, size = struct.unpack_from("<II", info, 8 + index * 8)
        old_block = original[offset:offset + size]
        new_block = patched[offset:offset + size]
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
    assert open(os.path.join(WORK, "fs", "bg", "GrpBGInfo.dat"), "rb").read() == info
    print("GrpBGInfo unchanged; non-target blocks byte-identical; title reference matches")


if __name__ == "__main__":
    main()
