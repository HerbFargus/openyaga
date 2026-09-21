"""Decoder for the Yaga engine's own .rle sprite animations.

Layout (all little-endian), cross-checked against animation_rle.c in cyxx/linyaga:

  8   signature F2 65 6C 72 00 00 20 4D
  u32 frame count
  u32 flags -- bit 0: a 256-entry BGRA palette follows
  [1024 bytes palette]
  per frame:
    16  header, layer count at +12
    per layer:
      f32 x, f32 y
      u32 unknown, u32 phoneme mask
      57  layer name (NUL padded)
      4   "rle\0"
      u32 pixel format: 0x40012F9 / 0x40012FB paletted, 0xC0012F9 BGRA
      3   padding
      u32 width, u32 height
      u32 flags -- bit 0: a per-layer 256-entry BGRA palette follows
      u32 unknown, u32 always 1, u32 compressed size
      [1024 bytes palette]
      compressed size bytes of RLE data

RLE codes: count = (code & 0x3F) + 1; (code & 0xC0) == 0xC0 skips `count`
transparent pixels, code & 0x80 repeats one colour, otherwise `count` literals.
"""

from __future__ import annotations

import struct

from PIL import Image, ImageChops

from .anim import Anim, Frame, Layer

RLE_SIG = b"\xf2elr\x00\x00 M"

FMT_PAL = (0x40012F9, 0x40012FB)
FMT_BGRA = 0xC0012F9


class RleError(Exception):
    pass


def _bgra_palette_to_rgba(pal: bytes) -> bytes:
    b = bytearray(pal)
    b[0::4], b[2::4] = b[2::4], b[0::4]
    return bytes(b)


def _decode_paletted(data, pos, size, w, h, palette_rgba):
    """Paletted RLE -> RGBA image.  Builds an index plane plus a coverage mask,
    so untouched (transparent) runs stay fully transparent."""
    n = w * h
    idx = bytearray(n)
    cover = bytearray(n)
    off = 0
    end = pos + size
    while pos < end:
        code = data[pos]
        pos += 1
        count = (code & 0x3F) + 1
        if off + count > n:
            count = max(0, n - off)
        if code & 0xC0 == 0xC0:
            pass  # transparent run
        elif code & 0x80:
            idx[off:off + count] = bytes([data[pos]]) * count
            cover[off:off + count] = b"\xff" * count
            pos += 1
        else:
            run = (code & 0x3F) + 1
            idx[off:off + count] = data[pos:pos + count]
            cover[off:off + count] = b"\xff" * count
            pos += run
        off += (code & 0x3F) + 1
    im = Image.frombytes("P", (w, h), bytes(idx))
    im.putpalette(palette_rgba, rawmode="RGBA")
    im = im.convert("RGBA")
    mask = Image.frombytes("L", (w, h), bytes(cover))
    im.putalpha(ImageChops.multiply(im.getchannel("A"), mask))
    return im, pos - end


def _decode_bgra(data, pos, size, w, h):
    n = w * h
    buf = bytearray(n * 4)
    off = 0
    end = pos + size
    while pos < end:
        code = data[pos]
        pos += 1
        count = (code & 0x3F) + 1
        if code & 0xC0 == 0xC0:
            pass  # transparent run
        elif code & 0x80:
            px = data[pos:pos + 4]
            pos += 4
            if off < n:
                buf[off * 4:(off + count) * 4] = px * min(count, n - off)
        else:
            take = min(count, max(0, n - off))
            buf[off * 4:(off + take) * 4] = data[pos:pos + take * 4]
            pos += count * 4
        off += count
    im = Image.frombytes("RGBA", (w, h), bytes(buf), "raw", "BGRA")
    return im, pos - end


def load(data: bytes, source: str = "") -> Anim:
    if data[:8] != RLE_SIG:
        raise RleError("not a Yaga RLE stream")
    anim = Anim(kind="rle", source=source)
    frame_count, flags = struct.unpack_from("<II", data, 8)
    pos = 16
    global_pal = b"\x00\x00\x00\xff" * 256
    if flags & 1:
        global_pal = _bgra_palette_to_rgba(data[pos:pos + 1024])
        pos += 1024

    for _ in range(frame_count):
        layer_count = struct.unpack_from("<I", data, pos + 12)[0]
        pos += 16
        frame = Frame()
        anim.frames.append(frame)
        for _ in range(layer_count):
            fx, fy, _unk, mask = struct.unpack_from("<ffII", data, pos)
            pos += 16
            name = data[pos:pos + 0x39].split(b"\x00")[0].decode("latin-1")
            pos += 0x39
            if data[pos:pos + 4] != b"rle\x00":
                raise RleError("missing rle tag at 0x%x in %s" % (pos, source))
            pos += 4
            fmt = struct.unpack_from("<I", data, pos)[0]
            pos += 4 + 3
            w, h, lflags, _unk2, one, size = struct.unpack_from("<IIIIII", data, pos)
            pos += 24
            palette = global_pal
            if lflags & 1:
                palette = _bgra_palette_to_rgba(data[pos:pos + 1024])
                pos += 1024

            layer = Layer(name=name, x=int(fx), y=int(fy), w=w, h=h, mask=mask)
            try:
                if fmt in FMT_PAL:
                    layer.image, slack = _decode_paletted(data, pos, size, w, h, palette)
                elif fmt == FMT_BGRA:
                    layer.image, slack = _decode_bgra(data, pos, size, w, h)
                else:
                    raise RleError("unsupported pixel format 0x%X" % fmt)
                if slack:
                    layer.note = "overran RLE block by %d bytes" % slack
            except Exception as exc:
                layer.note = str(exc)
                anim.notes.append("%s: %s" % (name or "?", exc))
            frame.layers.append(layer)
            pos += size
    return anim
