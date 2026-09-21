"""Decoder for the MNG animation files shipped with Pajama Sam 4 (Yaga engine).

The files are real MNG streams (signature 8A 4D 4E 47 0D 0A 1A 0A) but they use
a private subset that the engine reads directly:

  MHDR              header, ignored
  PLTE / tRNS       256-entry global palette + alpha, before the first FRAM;
                    after it, they apply to the frame being built
  FRAM  (len 10)    starts the first frame
  FRAM  (len 0)     starts a subsequent frame (skipped if no layer was defined)
  DEFI  (len 12)    starts a layer; last 8 bytes are signed BE x, y
  tEXt  "LAYER\0n"  the layer's name
  flAG  (len 4)     little-endian lipsync/phoneme mask for the layer
  IHDR/IDAT/IEND    the layer's bitmap, as an ordinary PNG image stream
  MEND              end

Cross-checked against animation_mng.c in cyxx/linyaga.
"""

from __future__ import annotations

import struct
import zlib

from PIL import Image

from .anim import Anim, Frame, Layer

MNG_SIG = b"\x8aMNG\r\n\x1a\n"

_BPP = {2: 3, 3: 1, 6: 4}  # PNG colour type -> bytes per pixel (8-bit only)


class MngError(Exception):
    pass


def _unfilter(raw: bytes, w: int, h: int, bpp: int):
    """Strip PNG row filters.  Returns (pixels, filters_used)."""
    stride = w * bpp
    used = set()
    # Fast path: every filter byte is 0, so just drop them.
    if not any(raw[y * (stride + 1)] for y in range(h)):
        out = bytearray(stride * h)
        for y in range(h):
            src = y * (stride + 1) + 1
            out[y * stride:(y + 1) * stride] = raw[src:src + stride]
        return bytes(out), {0}

    out = bytearray(stride * h)
    prev = bytearray(stride)
    for y in range(h):
        base = y * (stride + 1)
        ft = raw[base]
        used.add(ft)
        line = bytearray(raw[base + 1:base + 1 + stride])
        if ft == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                c = prev[i - bpp] if i >= bpp else 0
                b = prev[i]
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        elif ft != 0:
            raise MngError("bad PNG filter %d" % ft)
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return bytes(out), used


def _decode_image(w, h, color, zdata, palette_rgba):
    """Turn one IHDR/IDAT group into an RGBA PIL image."""
    bpp = _BPP.get(color)
    if bpp is None:
        raise MngError("unsupported PNG colour type %d" % color)
    buf_size = h * (w * bpp) + h
    note = ""
    # Inflate first.  linyaga decides on size alone (zsize >= buf_size means
    # stored raw), but that misreads small images whose zlib stream is longer
    # than the pixels it encodes -- a 2x2 palette image is 6 bytes raw and ~15
    # compressed -- so trust what actually inflates and keep raw as the fallback.
    raw = None
    try:
        raw = zlib.decompressobj().decompress(zdata, buf_size + 16)
    except zlib.error:
        raw = None
    if raw is None or len(raw) != buf_size:
        # linyaga has one special case here: a 2x2 palette image whose data is
        # really 4 RGBA pixels (18 = 2 rows * (2*4) + 2 filter bytes).
        if raw is not None and w == 2 and h == 2 and len(raw) == 18 and color == 3:
            bpp, color, buf_size = 4, 6, 18
        elif raw is not None:
            # A handful of tiny images ship with a truncated zlib stream (e.g.
            # the 3x3 twinkles in elastic_land, 9 of 12 bytes present; a few 1x1
            # layers are nothing but a zlib header).  Keep
            # the rows that are there and leave the rest transparent.
            note = "truncated: %d of %d bytes" % (len(raw), buf_size)
            raw = raw + b"\x00" * (buf_size - len(raw))
        elif len(zdata) >= buf_size:
            raw = zdata[:buf_size]  # stored with no zlib wrapper
            note = "raw"
        else:
            raise MngError("undecodable PNG data: %d compressed bytes, want %d"
                           % (len(zdata), buf_size))
    pixels, filters = _unfilter(raw, w, h, bpp)
    if filters - {0}:
        note = (note + " " if note else "") + "filters=%s" % sorted(filters)

    if bpp == 1:
        im = Image.frombytes("P", (w, h), pixels)
        im.putpalette(palette_rgba, rawmode="RGBA")
        im = im.convert("RGBA")
    elif bpp == 3:
        im = Image.frombytes("RGB", (w, h), pixels).convert("RGBA")
    else:
        im = Image.frombytes("RGBA", (w, h), pixels)
    return im, note


def load(data: bytes, source: str = "") -> Anim:
    if not data[:8] == MNG_SIG:
        raise MngError("not an MNG stream")

    anim = Anim(kind="mng", source=source)
    # Default palette: opaque black, matching linyaga.
    global_pal = bytearray(b"\x00\x00\x00\xff" * 256)
    frame_pal = bytearray(global_pal)
    in_frames = False
    layers_this_frame = 0
    frame = None
    layer = None
    img_w = img_h = img_color = 0
    zdata = bytearray()

    pos, end = 8, len(data)
    while pos + 8 <= end:
        size, tag = struct.unpack_from(">I4s", data, pos)
        body = data[pos + 8:pos + 8 + size]
        pos += 12 + size  # length + tag + body + crc

        if tag == b"tRNS" and size == 256:
            tgt = frame_pal if in_frames else global_pal
            tgt[3::4] = body
        elif tag == b"PLTE" and size == 768:
            tgt = frame_pal if in_frames else global_pal
            tgt[0::4], tgt[1::4], tgt[2::4] = body[0::3], body[1::3], body[2::3]
        elif tag == b"FRAM":
            if size == 10:
                in_frames = True
            elif layers_this_frame == 0:
                continue  # empty FRAM, no frame to close
            frame = Frame()
            anim.frames.append(frame)
            layers_this_frame = 0
            layer = None
            frame_pal = bytearray(global_pal)
        elif tag == b"DEFI" and size == 12:
            x, y = struct.unpack_from(">ii", body, 4)
            layer = Layer(x=x, y=y)
            if frame is None:  # DEFI before any FRAM: start one anyway
                frame = Frame()
                anim.frames.append(frame)
            frame.layers.append(layer)
            layers_this_frame += 1
        elif tag == b"tEXt" and layer is not None:
            if body.startswith(b"LAYER\x00"):
                layer.name = body[6:].split(b"\x00")[0].decode("latin-1")
        elif tag == b"flAG" and size == 4 and layer is not None:
            layer.mask = struct.unpack_from("<I", body)[0]
        elif tag == b"IHDR" and size == 13:
            img_w, img_h, depth, img_color, comp, filt, interlace = struct.unpack(">IIBBBBB", body)
            if depth != 8 or comp != 0 or filt != 0 or interlace != 0:
                raise MngError(
                    "unsupported PNG: depth=%d comp=%d filter=%d interlace=%d"
                    % (depth, comp, filt, interlace))
            zdata = bytearray()
        elif tag == b"IDAT":
            zdata += body
        elif tag == b"IEND":
            if layer is not None:
                layer.w, layer.h = img_w, img_h
                try:
                    layer.image, layer.note = _decode_image(
                        img_w, img_h, img_color,
                        bytes(zdata), bytes(frame_pal))
                except Exception as exc:
                    layer.note = str(exc)
                    anim.notes.append("%s: %s" % (layer.name or "?", exc))
            zdata = bytearray()
        elif tag == b"MEND":
            break

    return anim
