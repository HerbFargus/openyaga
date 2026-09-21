#!/usr/bin/env python3
"""Extractor for the Yaga engine data files used by Pajama Sam 4:
Life Is Rough When You Lose Your Stuff (and Putt-Putt: Pep's Birthday Surprise).

The .he data files are stored (uncompressed) ZIP archives.  Sprites live in them
as .mng (an MNG subset) and .rle (a Yaga-specific RLE), both decoded here to
RGBA and written out as PNG frames, sheets, or animations.

  yaga_extract.py archives
  yaga_extract.py ls --ext .rle
  yaga_extract.py info "*ela_enter_vista*"
  yaga_extract.py sprites --pattern "*sam*" --formats sheet,apng
  yaga_extract.py raw --ext .xml
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import zipfile

from yaga import he, mng, rle, render
from yaga.anim import Anim, PHONEME_ALL, PHONEME_NONE, PHONEME_REST, PHONEME_NAMES


def parse_phoneme(value):
    """--phoneme accepts rest/all/none, a phoneme name, or a number."""
    v = str(value).strip().lower()
    if v in ("rest", "root", "default"):
        return PHONEME_REST
    if v == "all":
        return PHONEME_ALL
    if v == "none":
        return PHONEME_NONE
    for bit, name in PHONEME_NAMES.items():
        if name.lower() == v:
            return bit
    return int(v, 0)

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA = os.path.join(os.path.dirname(HERE), "stock-game-files", "program files", "Atari")
DEFAULT_OUT = os.path.join(os.path.dirname(HERE), "extracted")


def decode(name: str, data: bytes) -> Anim:
    if name.lower().endswith(".rle"):
        return rle.load(data, name)
    return mng.load(data, name)


def cmd_archives(args):
    archives = he.find_archives(args.data)
    if not archives:
        sys.exit("no .he archives under %s" % args.data)
    total = 0
    for path in archives:
        zf = zipfile.ZipFile(path)
        infos = zf.infolist()
        exts = {}
        for i in infos:
            e = os.path.splitext(i.filename)[1].lower() or "(none)"
            c, b = exts.get(e, (0, 0))
            exts[e] = (c + 1, b + i.file_size)
        total += len(infos)
        print("%-16s %5d entries  %7.1f MB" % (
            os.path.basename(path), len(infos),
            sum(i.file_size for i in infos) / 1048576))
        for e, (c, b) in sorted(exts.items(), key=lambda kv: -kv[1][1]):
            print("      %-6s %5d  %7.1f MB" % (e, c, b / 1048576))
    print("%d entries in %d archives" % (total, len(archives)))


def cmd_ls(args):
    archives = he.find_archives(args.data)
    n = 0
    for path, zf, info in he.iter_members(archives, args.pattern, args.ext):
        print("%-16s %10d  %s" % (os.path.basename(path), info.file_size, info.filename))
        n += 1
        if args.limit and n >= args.limit:
            break
    print("-- %d members" % n, file=sys.stderr)


def cmd_info(args):
    archives = he.find_archives(args.data)
    for path, zf, info in he.iter_members(archives, args.pattern, he.IMAGE_EXTS):
        anim = decode(info.filename, zf.read(info))
        print("%s  (%s, in %s)" % (info.filename, anim.kind, os.path.basename(path)))
        print("  %d frames, bbox %s" % (len(anim.frames), anim.bbox(PHONEME_ALL)))
        for fi, frame in enumerate(anim.frames):
            print("  frame %d: %d layers" % (fi, len(frame.layers)))
            for layer in frame.layers:
                print("      %-34s %4d,%-4d %4dx%-4d mask=0x%08X %s" % (
                    layer.name[:34], layer.x, layer.y, layer.w, layer.h,
                    layer.mask, layer.note))
            if fi >= args.frames - 1 and len(anim.frames) > args.frames:
                print("  ... %d more frames" % (len(anim.frames) - args.frames))
                break
        if anim.notes:
            print("  notes: %s" % anim.notes[:5])


def _job(task):
    """Decode one member and write the requested outputs.  Returns a record."""
    path, member, out_root, formats, phoneme, fps, columns = task
    rec = {"archive": os.path.basename(path), "member": member}
    try:
        with zipfile.ZipFile(path) as zf:
            data = zf.read(member)
        if not data:
            rec["error"] = "empty file"
            return rec
        anim = decode(member, data)
    except Exception as exc:
        rec["error"] = "%s: %s" % (type(exc).__name__, exc)
        return rec

    stem = os.path.splitext(member)[0].replace("\\", "/")
    base = os.path.join(out_root, os.path.splitext(os.path.basename(path))[0], *stem.split("/"))
    os.makedirs(os.path.dirname(base), exist_ok=True)

    images, box = render.compose(anim, phoneme=phoneme)
    rec.update(kind=anim.kind, frames=len(anim.frames), box=box,
               layers=sorted({l.name for f in anim.frames for l in f.layers}),
               phoneme_layers=sorted({l.name: l.mask for f in anim.frames
                                      for l in f.layers if l.is_phoneme}.items()))
    if anim.notes:
        rec["notes"] = anim.notes[:8]
    written = []

    if "frames" in formats and images:
        if len(images) == 1:
            images[0].save(base + ".png")
            written.append(base + ".png")
        else:
            os.makedirs(base, exist_ok=True)
            for i, im in enumerate(images):
                p = os.path.join(base, "frame_%03d.png" % i)
                im.save(p)
                written.append(p)
    if "layers" in formats:
        os.makedirs(base + "_layers", exist_ok=True)
        for fi, frame in enumerate(anim.frames):
            for li, layer in enumerate(frame.layers):
                if layer.image is None:
                    continue
                safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in layer.name)
                p = os.path.join(base + "_layers",
                                 "f%03d_l%02d_%s.png" % (fi, li, safe or "layer"))
                layer.image.save(p)
                written.append(p)
    if "sheet" in formats and len(images) > 1:
        s = render.sheet(images, columns)
        if s:
            s.save(base + "_sheet.png")
            written.append(base + "_sheet.png")
    if "apng" in formats and len(images) > 1:
        render.save_apng(images, base + "_anim.png", fps)
        written.append(base + "_anim.png")
    if "gif" in formats and len(images) > 1:
        render.save_gif(images, base + ".gif", fps)
        written.append(base + ".gif")

    rec["files"] = len(written)
    return rec


def cmd_sprites(args):
    archives = he.find_archives(args.data)
    formats = set(f.strip() for f in args.formats.split(",") if f.strip())
    phoneme = parse_phoneme(args.phoneme)
    tasks = []
    for path, zf, info in he.iter_members(archives, args.pattern, he.IMAGE_EXTS):
        tasks.append((path, info.filename, args.out, formats, phoneme,
                      args.fps, args.columns))
        if args.limit and len(tasks) >= args.limit:
            break
    print("%d animations -> %s" % (len(tasks), args.out), file=sys.stderr)

    records, errors = [], 0
    if args.jobs > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=args.jobs) as ex:
            for i, rec in enumerate(ex.map(_job, tasks, chunksize=4)):
                records.append(rec)
                errors += "error" in rec
                if (i + 1) % 200 == 0:
                    print("  %d/%d (%d errors)" % (i + 1, len(tasks), errors), file=sys.stderr)
    else:
        for i, t in enumerate(tasks):
            rec = _job(t)
            records.append(rec)
            errors += "error" in rec
            if (i + 1) % 200 == 0:
                print("  %d/%d (%d errors)" % (i + 1, len(tasks), errors), file=sys.stderr)

    os.makedirs(args.out, exist_ok=True)
    index = os.path.join(args.out, "index.json")
    with open(index, "w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=1)
    png = sum(r.get("files", 0) for r in records)
    print("done: %d animations, %d images, %d errors\nindex: %s" % (
        len(records), png, errors, index), file=sys.stderr)
    for r in records:
        if "error" in r:
            print("  ERROR %s: %s" % (r["member"], r["error"]), file=sys.stderr)


def cmd_raw(args):
    archives = he.find_archives(args.data)
    n = 0
    for path, zf, info in he.iter_members(archives, args.pattern, args.ext):
        dest = os.path.join(args.out, os.path.splitext(os.path.basename(path))[0],
                            *info.filename.replace("\\", "/").split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(zf.read(info))
        n += 1
        if args.limit and n >= args.limit:
            break
    print("extracted %d files to %s" % (n, args.out), file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=DEFAULT_DATA, help="folder holding the .he files")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("archives", help="list .he archives and what is in them")
    p.set_defaults(func=cmd_archives)

    p = sub.add_parser("ls", help="list archive members")
    p.add_argument("--pattern", help="glob against the member path")
    p.add_argument("--ext", nargs="*", help="filter by extension, e.g. --ext .mng .rle")
    p.add_argument("--limit", type=int, default=0)
    p.set_defaults(func=cmd_ls)

    p = sub.add_parser("info", help="dump the frame/layer structure of an animation")
    p.add_argument("pattern", help="glob against the member path")
    p.add_argument("--frames", type=int, default=3, help="frames to print")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("sprites", help="decode .mng/.rle to PNG")
    p.add_argument("--pattern", help="glob against the member path")
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--formats", default="frames",
                   help="comma-separated: frames,layers,sheet,apng,gif")
    p.add_argument("--phoneme", default="rest",
                   help="which lipsync pose to draw: rest (default, closed mouth), "
                        "all (every mouth stacked), none (no masked layers, so no "
                        "head), a phoneme name such as A/EE/OH, or a mask value")
    p.add_argument("--fps", type=int, default=15)
    p.add_argument("--columns", type=int, default=0, help="sheet columns")
    p.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    p.add_argument("--limit", type=int, default=0)
    p.set_defaults(func=cmd_sprites)

    p = sub.add_parser("raw", help="copy members out of the archives untouched")
    p.add_argument("--pattern")
    p.add_argument("--ext", nargs="*")
    p.add_argument("--out", default=os.path.join(DEFAULT_OUT, "raw"))
    p.add_argument("--limit", type=int, default=0)
    p.set_defaults(func=cmd_raw)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
