# -*- coding: latin-1 -*-
"""Windows .cur files, turned into the masks SDL wants.

The game changes its cursor by handing the engine a .cur file and an id:

    globals.g_RenderTarget.LoadCursorFile(imgPath, idValue)
    globals.g_RenderTarget.SetCursorByID(idValue)

and it does this constantly -- `CCursor.__init__` sets `g_forceHWCursor` true
and nothing ever sets it back, so the hardware path is the only one the retail
game takes.  The colourful cursor .mng files in the data are for a software
path that never runs.

All 49 of them are 1 bpp, 32x32, which is exactly what SDL 1.2 can do, so
these are the real cursors rather than an approximation of them.

The two formats disagree about what the bits mean, and the mapping is the
whole point of this module:

    Windows  AND XOR        SDL  data mask
             0   0   black       1    1
             0   1   white       0    1
             1   0   transparent 0    0
             1   1   invert      1    0

which comes out as `mask = NOT AND` and `data = XOR XOR mask`.

Layout is an ICO container: ICONDIR, one ICONDIRENTRY (whose "planes" and
"bitcount" fields hold the hotspot instead, this being a cursor rather than an
icon), a BITMAPINFOHEADER whose height counts both masks, a two-colour
palette, then the XOR bitmap and the AND bitmap, bottom-up with rows padded to
four bytes.
"""

import struct

import _stub


def parse(data):
    """(size, hotspot, data, mask) for SDL, or None if unreadable.

    data and mask are tuples of ints, already in SDL's sense rather than
    Windows', ready to hand to pygame.mouse.set_cursor -- which wants numbers
    and not a byte string, since in Python 2 a str iterates as characters and
    it rejects those with "Invalid number in mask array".
    """
    try:
        reserved, kind, count = struct.unpack_from("<HHH", data, 0)
        # kind is 1 for an icon and 2 for a cursor, and every one of this
        # game's .cur files says 1 -- they were exported as icons.  Windows
        # does not mind and neither should we; the only thing the distinction
        # costs is the hotspot, which those fields then hold as planes and
        # bit count.  Both are zero here, and (0, 0) is where these arrows
        # point anyway.
        if reserved != 0 or kind not in (1, 2) or count < 1:
            _stub.LOG.record("call", "yagagraphics.cur",
                             "not an icon or cursor: reserved=%d type=%d n=%d"
                             % (reserved, kind, count))
            return None
        width, height, _colours, _r, hot_x, hot_y, _size, offset = \
            struct.unpack_from("<BBBBHHII", data, 6)
        width = width or 256
        height = height or 256

        header_size, _w, bitmap_height, _planes, bpp = \
            struct.unpack_from("<IiihH", data, offset)
        hot_x, hot_y = (hot_x, hot_y) if kind == 2 else (0, 0)
        if bpp != 1:
            # Nothing in this game hits it, but a colour cursor cannot be
            # expressed as SDL 1.2 masks at all, so say so rather than
            # producing noise.
            _stub.LOG.record("call", "yagagraphics.cur",
                             "%d bpp cursor cannot be used with SDL 1.2" % bpp)
            return None

        rows = bitmap_height // 2
        stride = ((width + 31) // 32) * 4
        palette = 2 * 4
        start = offset + header_size + palette
        xor = data[start:start + stride * rows]
        andm = data[start + stride * rows:start + 2 * stride * rows]
        if len(xor) < stride * rows or len(andm) < stride * rows:
            return None

        # SDL wants top-down rows, packed to the cursor width.
        sdl_stride = (width + 7) // 8
        out_data = bytearray(sdl_stride * rows)
        out_mask = bytearray(sdl_stride * rows)
        for y in range(rows):
            source = (rows - 1 - y) * stride        # bottom-up
            target = y * sdl_stride
            for byte in range(sdl_stride):
                a = ord(andm[source + byte])
                x = ord(xor[source + byte])
                mask = (~a) & 0xFF
                out_mask[target + byte] = mask
                out_data[target + byte] = (x ^ mask) & 0xFF
        return ((width, rows), (hot_x, hot_y), tuple(out_data), tuple(out_mask))
    except (struct.error, IndexError, TypeError), exc:
        _stub.LOG.record("call", "yagagraphics.cur", "unreadable: %s" % exc)
        return None
