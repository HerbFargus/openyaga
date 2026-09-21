# -*- coding: latin-1 -*-
"""MNG and RLE decoding for the player -- Python 2.7, no Pillow.

A port of ../../tools/yaga/{mng,rle}.py, which target Python 3 and produce PIL
images.  The player cannot use those: Pillow's last 2.7-compatible release is
from 2020, and pygame is right there.  So these produce plain RGBA bytes, which
pygame.image.frombuffer turns into a Surface directly.

Format details are in ../../FORMATS.md.  Two porting notes:

* Indexing a `str` in Python 2 gives a one-character string, not an integer, so
  every buffer here is a `bytearray` -- then `data[i]` is an int, exactly as the
  Python 3 original assumes.
* Expanding paletted pixels one at a time is far too slow in pure Python for a
  640x480 background.  Instead each colour channel is produced with a single
  256-byte `translate()` and dropped into place with a strided slice
  assignment, which keeps the work in C.
"""

import struct
import zlib

MNG_SIG = "\x8aMNG\r\n\x1a\n"
RLE_SIG = "\xf2elr\x00\x00 M"

_BPP = {2: 3, 3: 1, 6: 4}       # PNG colour type -> bytes per pixel

FMT_PAL = (0x40012F9, 0x40012FB)
FMT_BGRA = 0xC0012F9


class DecodeError(Exception):
    pass


class Layer(object):
    """One bitmap in a frame.

    `rgba` is the decoded pixels; `image` is the same thing as a pygame
    Surface, which is what the engine's own layers expose -- font_loader does
    `anim.frames[0].layers[0].image` and hands it to yagagraphics.IImage.
    """

    __slots__ = ("name", "x", "y", "w", "h", "mask", "rgba", "note", "_surface")

    @property
    def image(self):
        if self._surface is None and self.rgba is not None and self.w and self.h:
            import pygame
            surface = pygame.image.frombuffer(
                bytes(bytearray(self.rgba)), (self.w, self.h), "RGBA")
            try:
                surface = surface.convert_alpha()
            except pygame.error:
                surface = surface.copy()
            self._surface = surface
        return self._surface

    def __init__(self, name="", x=0, y=0, w=0, h=0, mask=0, rgba=None, note=""):
        self._surface = None
        self.name = name
        self.x, self.y, self.w, self.h = x, y, w, h
        self.mask = mask
        self.rgba = rgba
        self.note = note


class Frame(object):
    __slots__ = ("layers",)

    def __init__(self):
        self.layers = []


class Anim(object):
    def __init__(self, kind, path=""):
        self.kind = kind
        self.path = path
        self.frames = []

    def bbox(self, phoneme=0x1):
        boxes = [(l.x, l.y, l.x + l.w, l.y + l.h)
                 for f in self.frames for l in f.layers
                 if l.rgba is not None and (l.mask == 0 or (l.mask & phoneme))]
        if not boxes:
            return None
        return (min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes))

    def __repr__(self):
        return "<Anim %s %s, %d frames>" % (self.kind, self.path, len(self.frames))


def _channels_from_palette(palette):
    """Split an RGBA palette into four 256-byte translate tables."""
    pal = bytes(bytearray(palette))
    return (pal[0::4], pal[1::4], pal[2::4], pal[3::4])


def _expand_paletted(indices, palette, n):
    """Index plane -> RGBA bytes, one translate() per channel."""
    r, g, b, a = _channels_from_palette(palette)
    src = bytes(bytearray(indices))
    out = bytearray(n * 4)
    out[0::4] = src.translate(r)
    out[1::4] = src.translate(g)
    out[2::4] = src.translate(b)
    out[3::4] = src.translate(a)
    return out


def _rgb_to_rgba(pixels, n):
    out = bytearray(n * 4)
    out[0::4] = pixels[0::3]
    out[1::4] = pixels[1::3]
    out[2::4] = pixels[2::3]
    out[3::4] = b"\xff" * n
    return out


def _bgra_to_rgba(buf, n):
    out = bytearray(n * 4)
    out[0::4] = buf[2::4]
    out[1::4] = buf[1::4]
    out[2::4] = buf[0::4]
    out[3::4] = buf[3::4]
    return out


# --------------------------------------------------------------------------
# MNG
# --------------------------------------------------------------------------

def _unfilter(raw, w, h, bpp):
    """Strip PNG row filters.  Every image in Pajama Sam 4 uses filter 0."""
    stride = w * bpp
    if not any(raw[y * (stride + 1)] for y in range(h)):
        out = bytearray(stride * h)
        for y in range(h):
            src = y * (stride + 1) + 1
            out[y * stride:(y + 1) * stride] = raw[src:src + stride]
        return out

    out = bytearray(stride * h)
    prev = bytearray(stride)
    for y in range(h):
        base = y * (stride + 1)
        ft = raw[base]
        line = bytearray(raw[base + 1:base + 1 + stride])
        if ft == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                c = prev[i - bpp] if i >= bpp else 0
                b = prev[i]
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if (pa <= pb and pa <= pc)
                                      else (b if pb <= pc else c))) & 0xFF
        elif ft != 0:
            raise DecodeError("bad PNG filter %d" % ft)
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return out


def _decode_png(w, h, color, zdata, palette):
    bpp = _BPP.get(color)
    if bpp is None:
        raise DecodeError("unsupported PNG colour type %d" % color)
    need = h * (w * bpp) + h
    note = ""

    try:
        raw = bytearray(zlib.decompressobj().decompress(bytes(zdata), need + 16))
    except zlib.error:
        raw = None

    if raw is None or len(raw) != need:
        if raw is not None and w == 2 and h == 2 and len(raw) == 18 and color == 3:
            bpp, color, need = 4, 6, 18          # mislabelled 2x2 RGBA
        elif raw is not None:
            # 1,568 tiny sprites ship with a truncated zlib stream; keep what
            # is there and leave the rest transparent.
            note = "truncated: %d of %d bytes" % (len(raw), need)
            raw = raw + bytearray(need - len(raw))
        elif len(zdata) >= need:
            raw, note = bytearray(zdata[:need]), "raw"
        else:
            raise DecodeError("undecodable PNG data")

    pixels = _unfilter(raw, w, h, bpp)
    n = w * h
    if bpp == 1:
        return _expand_paletted(pixels, palette, n), note
    if bpp == 3:
        return _rgb_to_rgba(pixels, n), note
    return pixels, note                            # already RGBA


def load_mng(data, path=""):
    data = bytearray(data)
    if bytes(data[:8]) != MNG_SIG:
        raise DecodeError("not an MNG stream")

    anim = Anim("mng", path)
    global_pal = bytearray("\x00\x00\x00\xff" * 256)
    frame_pal = bytearray(global_pal)
    in_frames = False
    layers_here = 0
    frame = None
    layer = None
    img_w = img_h = img_color = 0
    zdata = bytearray()

    pos, end = 8, len(data)
    while pos + 8 <= end:
        size, tag = struct.unpack_from(">I4s", buffer(data), pos)
        body = data[pos + 8:pos + 8 + size]
        pos += 12 + size

        if tag == "tRNS" and size == 256:
            tgt = frame_pal if in_frames else global_pal
            tgt[3::4] = body
        elif tag == "PLTE" and size == 768:
            tgt = frame_pal if in_frames else global_pal
            tgt[0::4], tgt[1::4], tgt[2::4] = body[0::3], body[1::3], body[2::3]
        elif tag == "FRAM":
            if size == 10:
                in_frames = True
            elif layers_here == 0:
                continue
            frame = Frame()
            anim.frames.append(frame)
            layers_here = 0
            layer = None
            frame_pal = bytearray(global_pal)
        elif tag == "DEFI" and size == 12:
            x, y = struct.unpack_from(">ii", buffer(body), 4)
            layer = Layer(x=x, y=y)
            if frame is None:
                frame = Frame()
                anim.frames.append(frame)
            frame.layers.append(layer)
            layers_here += 1
        elif tag == "tEXt" and layer is not None:
            if bytes(body[:6]) == "LAYER\x00":
                layer.name = bytes(body[6:]).split("\x00")[0]
        elif tag == "flAG" and size == 4 and layer is not None:
            layer.mask = struct.unpack_from("<I", buffer(body))[0]
        elif tag == "IHDR" and size == 13:
            img_w, img_h, depth, img_color, comp, filt, inter = \
                struct.unpack(">IIBBBBB", bytes(body))
            if depth != 8 or comp or filt or inter:
                raise DecodeError("unsupported PNG variant")
            zdata = bytearray()
        elif tag == "IDAT":
            zdata += body
        elif tag == "IEND":
            if layer is not None:
                layer.w, layer.h = img_w, img_h
                try:
                    layer.rgba, layer.note = _decode_png(
                        img_w, img_h, img_color, zdata, frame_pal)
                except Exception, exc:
                    layer.note = str(exc)
            zdata = bytearray()
        elif tag == "MEND":
            break
    return anim


# --------------------------------------------------------------------------
# RLE
# --------------------------------------------------------------------------

def _decode_rle_paletted(data, pos, size, w, h, palette):
    n = w * h
    idx = bytearray(n)
    holes = []              # transparent runs, zeroed out afterwards
    off = 0
    end = pos + size
    while pos < end:
        code = data[pos]
        pos += 1
        count = (code & 0x3F) + 1
        room = max(0, min(count, n - off))
        if code & 0xC0 == 0xC0:
            if room:
                holes.append((off, room))
        elif code & 0x80:
            if room:
                idx[off:off + room] = bytearray([data[pos]]) * room
            pos += 1
        else:
            if room:
                idx[off:off + room] = data[pos:pos + room]
            pos += count
        off += count

    rgba = _expand_paletted(idx, palette, n)
    for start, run in holes:                       # punch the transparent runs
        rgba[start * 4 + 3:(start + run) * 4:4] = bytearray(run)
    return rgba


def _decode_rle_bgra(data, pos, size, w, h):
    n = w * h
    buf = bytearray(n * 4)
    off = 0
    end = pos + size
    while pos < end:
        code = data[pos]
        pos += 1
        count = (code & 0x3F) + 1
        room = max(0, min(count, n - off))
        if code & 0xC0 == 0xC0:
            pass                                    # already transparent
        elif code & 0x80:
            if room:
                buf[off * 4:(off + room) * 4] = data[pos:pos + 4] * room
            pos += 4
        else:
            if room:
                buf[off * 4:(off + room) * 4] = data[pos:pos + room * 4]
            pos += count * 4
        off += count
    return _bgra_to_rgba(buf, n)


def _bgra_palette(raw):
    pal = bytearray(raw)
    pal[0::4], pal[2::4] = pal[2::4], pal[0::4]
    return pal


def load_rle(data, path=""):
    data = bytearray(data)
    if bytes(data[:8]) != RLE_SIG:
        raise DecodeError("not a Yaga RLE stream")

    anim = Anim("rle", path)
    frame_count, flags = struct.unpack_from("<II", buffer(data), 8)
    pos = 16
    global_pal = bytearray("\x00\x00\x00\xff" * 256)
    if flags & 1:
        global_pal = _bgra_palette(data[pos:pos + 1024])
        pos += 1024

    for _ in range(frame_count):
        layer_count = struct.unpack_from("<I", buffer(data), pos + 12)[0]
        pos += 16
        frame = Frame()
        anim.frames.append(frame)
        for _ in range(layer_count):
            fx, fy, _unk, mask = struct.unpack_from("<ffII", buffer(data), pos)
            pos += 16
            name = bytes(data[pos:pos + 0x39]).split("\x00")[0]
            pos += 0x39
            if bytes(data[pos:pos + 4]) != "rle\x00":
                raise DecodeError("missing rle tag at 0x%x" % pos)
            pos += 4
            fmt = struct.unpack_from("<I", buffer(data), pos)[0]
            pos += 7                                  # format + 3 padding
            w, h, lflags, _u2, _one, size = struct.unpack_from("<IIIIII", buffer(data), pos)
            pos += 24
            palette = global_pal
            if lflags & 1:
                palette = _bgra_palette(data[pos:pos + 1024])
                pos += 1024

            layer = Layer(name=name, x=int(fx), y=int(fy), w=w, h=h, mask=mask)
            try:
                if fmt in FMT_PAL:
                    layer.rgba = _decode_rle_paletted(data, pos, size, w, h, palette)
                elif fmt == FMT_BGRA:
                    layer.rgba = _decode_rle_bgra(data, pos, size, w, h)
                else:
                    raise DecodeError("unsupported pixel format 0x%X" % fmt)
            except Exception, exc:
                layer.note = str(exc)
            frame.layers.append(layer)
            pos += size
    return anim


def load(data, path=""):
    """Decode by signature, so the file extension does not have to be right."""
    head = bytes(bytearray(data[:8]))
    if head == MNG_SIG:
        return load_mng(data, path)
    if head == RLE_SIG:
        return load_rle(data, path)
    raise DecodeError("not a recognised animation: %r" % head[:8])
