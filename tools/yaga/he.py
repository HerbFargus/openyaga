"""The .he data files are ordinary ZIP archives with every member stored
uncompressed, so the stdlib reads them as-is.  This module just finds them and
gives back (archive, member) pairs."""

from __future__ import annotations

import fnmatch
import os
import zipfile

IMAGE_EXTS = (".mng", ".rle")


def find_archives(root: str):
    """Every .he under `root`, sorted by name."""
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if f.lower().endswith(".he"):
                out.append(os.path.join(dirpath, f))
    return sorted(out)


def iter_members(archives, pattern=None, exts=None):
    """Yield (archive_path, zipfile.ZipFile, ZipInfo) for matching members."""
    for path in archives:
        try:
            zf = zipfile.ZipFile(path)
        except zipfile.BadZipFile:
            continue
        for info in zf.infolist():
            name = info.filename
            if exts and not name.lower().endswith(tuple(exts)):
                continue
            if pattern and not fnmatch.fnmatch(name.lower(), pattern.lower()):
                continue
            yield path, zf, info
