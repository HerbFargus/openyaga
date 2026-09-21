"""Read the Python archive embedded in a Yaga game's executable.

Yaga games were packaged with McMillan Installer (the tool that later became
PyInstaller).  The .exe ends with a 24-byte cookie:

    4D 45 49 0C 0B 0A 0B 0E   "MEI" + version bytes
    <package length>          big-endian uint32
    <TOC offset>              big-endian uint32, relative to the package
    <TOC length>              big-endian uint32
    ...

The package's own table of contents lists entries by type -- 'z' is the PYZ
archive holding the game's Python modules, 'm' and 's' are the bootstrap
scripts.  The PYZ then has its own header:

    "PYZ\\0"                   magic
    <pyc magic>               4 bytes; 2D ED 0D 0A means Python 2.2
    <TOC offset>              uint32 -- endianness varies by packager version

and its TOC is a **Python 2 marshal** dict of {name: (is_package, pos, length)},
each entry zlib-compressed marshalled code.  Python 3's marshal cannot read
Python 2's format, so the handful of type codes actually used are decoded here.

Nothing in this module writes to the game directory; it only reads.
"""

from __future__ import annotations

import os
import struct
import zlib

MEI_COOKIE = bytes([0x4D, 0x45, 0x49, 0x0C, 0x0B, 0x0A, 0x0B, 0x0E])
COOKIE_SIZE = 24

PYC_MAGIC_NAMES = {
    b"\x2d\xed\x0d\x0a": "2.2",
    b"\x87\xc6\x0d\x0a": "2.1",
    b"\x3b\xf2\x0d\x0a": "2.3",
    b"\x6d\xf2\x0d\x0a": "2.4",
}


class PyzError(Exception):
    pass


class _Marshal2:
    """Just enough of the Python 2 marshal format to read a PYZ table."""

    def __init__(self, data: bytes):
        self.d, self.p = data, 0

    def _byte(self) -> int:
        if self.p >= len(self.d):
            raise PyzError("truncated marshal data")
        c = self.d[self.p]
        self.p += 1
        return c

    def _i32(self) -> int:
        v = struct.unpack_from("<i", self.d, self.p)[0]
        self.p += 4
        return v

    def load(self):
        t = chr(self._byte())
        if t in "0N":                       # NULL / None
            return None
        if t == "i":
            return self._i32()
        if t == "l":                        # long: base-2**15 digits
            n = self._i32()
            sign = -1 if n < 0 else 1
            v = 0
            for k in range(abs(n)):
                digit = struct.unpack_from("<H", self.d, self.p)[0]
                self.p += 2
                v |= digit << (15 * k)
            return sign * v
        if t in "st":                       # string / interned string
            n = self._i32()
            s = self.d[self.p:self.p + n]
            self.p += n
            return s.decode("latin-1")
        if t == "R":
            return self._i32()
        if t == "(":
            return tuple(self.load() for _ in range(self._i32()))
        if t == "[":
            return [self.load() for _ in range(self._i32())]
        if t == "{":                        # dict, NULL-terminated
            out = {}
            while True:
                k = self.load()
                if k is None:
                    return out
                out[k] = self.load()
        raise PyzError("unhandled marshal type %r at offset %d" % (t, self.p - 1))


def find_executable(game_dir: str):
    """The .exe in `game_dir` that carries an embedded Python archive.

    Scans rather than matching a filename, so this works for any Yaga game
    (PajamaLRS.exe, Putt-Putt, the Backyard Sports titles) without a table.
    """
    candidates = []
    for name in sorted(os.listdir(game_dir)):
        if not name.lower().endswith(".exe"):
            continue
        path = os.path.join(game_dir, name)
        try:
            with open(path, "rb") as fh:
                fh.seek(-COOKIE_SIZE, os.SEEK_END)
                if fh.read(8) == MEI_COOKIE:
                    candidates.append(path)
        except OSError:
            continue
    return candidates


def _read_toc(data: bytes):
    """Every entry in the executable's outer archive.

    Entry layout: length(4), offset(4), compressed size(4), real size(4),
    compression flag(1), type code(1), NUL-padded name -- all big-endian.
    Type 'z' is the PYZ of game modules; 'm' and 's' are the bootstrap
    scripts, and 's' includes boot.py, the entry point the game starts from.
    """
    idx = data.rfind(MEI_COOKIE)
    if idx < 0:
        raise PyzError("no McMillan/PyInstaller cookie found")
    pkg_len, toc_off, toc_size = struct.unpack_from(">III", data, idx + 8)
    base = len(data) - pkg_len

    entries, pos, end = [], base + toc_off, base + toc_off + toc_size
    while pos < end:
        entry_len = struct.unpack_from(">I", data, pos)[0]
        if entry_len <= 0:
            break
        item_pos, item_len, real_len = struct.unpack_from(">III", data, pos + 4)
        compressed = data[pos + 16]
        kind = chr(data[pos + 17])
        name = data[pos + 18:pos + entry_len].split(b"\x00")[0].decode("latin-1")
        entries.append({
            "name": name, "kind": kind, "offset": base + item_pos,
            "size": item_len, "real_size": real_len, "compressed": bool(compressed),
        })
        pos += entry_len
    return entries, base


def _read_package(data: bytes):
    """Locate the PYZ blob inside the executable."""
    entries, _base = _read_toc(data)
    for e in entries:
        if e["kind"] == "z":
            return e["offset"], e["size"], e["name"]
    raise PyzError("no PYZ archive in the executable's table of contents")


def read_boot_scripts(exe_path: str):
    """Yield (name, kind, blob) for the bootstrap entries in the outer archive.

    The two kinds are stored differently, which is easy to get wrong:
      'm' -- a complete .pyc, magic header already present, no wrapper
      's' -- plain Python SOURCE text, no compilation involved
    boot.py is an 's' entry, so the game's entry point comes out readable
    without decompiling anything.  script_system refuses to run without it.
    """
    with open(exe_path, "rb") as fh:
        data = fh.read()
    entries, _base = _read_toc(data)
    for e in entries:
        if e["kind"] not in ("m", "s"):
            continue
        blob = data[e["offset"]:e["offset"] + e["size"]]
        # The compression flag is not trustworthy for these entries -- in
        # PajamaLRS.exe _mountzlib is flagged compressed but stored raw -- so
        # try to inflate and fall back to the bytes as they are.
        try:
            blob = zlib.decompress(blob)
        except zlib.error:
            pass  # the compression flag is not trustworthy; most are stored raw
        yield e["name"], e["kind"], blob


def read_modules(exe_path: str):
    """Yield (module_name, is_package, marshalled_code_bytes, pyc_magic).

    The code is the raw marshalled code object as the packager stored it --
    a .pyc without its 8-byte header.
    """
    with open(exe_path, "rb") as fh:
        data = fh.read()

    offset, length, archive_name = _read_package(data)
    blob = data[offset:offset + length]
    if blob[:4] != b"PYZ\x00":
        raise PyzError("expected a PYZ archive, found %r" % blob[:4])

    magic = blob[4:8]
    # Packager versions disagree on this field's endianness; take whichever
    # reading lands inside the blob.
    be, le = struct.unpack(">I", blob[8:12])[0], struct.unpack("<I", blob[8:12])[0]
    toc_pos = be if be < len(blob) else le
    if toc_pos >= len(blob):
        raise PyzError("PYZ table of contents offset out of range")

    toc = _Marshal2(blob[toc_pos:]).load()
    if not isinstance(toc, dict):
        raise PyzError("PYZ table of contents is not a dict")

    for name in sorted(toc):
        is_pkg, pos, size = toc[name]
        try:
            code = zlib.decompress(blob[pos:pos + size])
        except zlib.error as exc:
            raise PyzError("could not decompress module %s: %s" % (name, exc))
        yield name, bool(is_pkg), code, magic


def describe(exe_path: str):
    """Summary of what an executable contains, without extracting it."""
    with open(exe_path, "rb") as fh:
        data = fh.read()
    offset, length, archive_name = _read_package(data)
    blob = data[offset:offset + length]
    magic = blob[4:8]
    return {
        "exe": exe_path,
        "archive": archive_name,
        "archive_bytes": length,
        "pyc_magic": magic.hex(),
        "python_version": PYC_MAGIC_NAMES.get(magic, "unknown"),
    }
