# -*- coding: latin-1 -*-
"""Resolving the game's virtual paths to bytes.

The engine addresses everything through paths whose FIRST component is an
archive name, not a folder:

    data/scenes.xml          -> scenes.xml inside data.he
    rooms/bedroom/bg.mng     -> bedroom/bg.mng inside rooms.he
    interface/cursors/x.cur  -> a loose file on disk, since there is no
                                interface.he member matching it

So a lookup tries the matching .he archive first and falls back to a real file.
Matching is case-insensitive throughout: the scripts lowercase paths before
asking (scene_manager does `path = path.lower()`), while the archives store
mixed case.

The .he files are ordinary ZIP archives with everything stored uncompressed --
see ../../FORMATS.md.
"""

import os
import zipfile

_archives = {}      # "rooms" -> (ZipFile, {lowercase member: real member})
_loose = []         # data dirs, searched for real files
_missing = set()    # paths asked for and not found, for reporting


def init(data_dirs):
    """Index every .he archive in the given directories."""
    for d in data_dirs:
        if not os.path.isdir(d):
            continue
        _loose.append(d)
        for name in sorted(os.listdir(d)):
            if not name.lower().endswith(".he"):
                continue
            stem = os.path.splitext(name)[0].lower()
            if stem in _archives:
                continue
            try:
                zf = zipfile.ZipFile(os.path.join(d, name))
            except zipfile.BadZipFile:
                continue
            index = {}
            for member in zf.namelist():
                index[member.replace("\\", "/").lower()] = member
            _archives[stem] = (zf, index)
    return len(_archives)


def _normalise(path):
    return str(path).replace("\\", "/").lstrip("/")


def read(path):
    """The bytes at a game path, or None if nothing matches."""
    p = _normalise(path)

    if "/" in p:
        head, rest = p.split("/", 1)
        entry = _archives.get(head.lower())
        if entry:
            zf, index = entry
            member = index.get(rest.lower())
            if member is not None:
                return zf.read(member)

    # Not in an archive: a real file, either as given or relative to a data dir.
    for root in [None] + _loose:
        candidate = p if root is None else os.path.join(root, p)
        if os.path.isfile(candidate):
            with open(candidate, "rb") as fh:
                return fh.read()

    # Last resort: case-insensitive walk of the loose directories.
    wanted = p.lower()
    for root in _loose:
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                full = os.path.join(dirpath, f)
                rel = os.path.relpath(full, root).replace("\\", "/").lower()
                if rel == wanted:
                    with open(full, "rb") as fh:
                        return fh.read()

    _missing.add(p)
    return None


def exists(path):
    return read(path) is not None


def missing():
    """Paths that were asked for and could not be found."""
    return sorted(_missing)
