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

# The real checks, captured before install_path_lookup replaces them, so
# nothing in here can recurse through the replacement.
_real_isfile = os.path.isfile
_real_exists = os.path.exists

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
            except getattr(zipfile, 'BadZipFile', getattr(zipfile, 'BadZipfile', Exception)):
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

    # The game asks for .evt and the disc has only .evb.  Both handlers are
    # registered side by side in globals.py -- EvtHandler() then EvbHandler()
    # -- so the pair is a source format and its compiled form, and only the
    # compiled one shipped.  Without this every talkie loses its lipsync and
    # the game prints "Warning: no event stream" for all 1,284 of them.
    if p.lower().endswith(".evt"):
        binary = read(p[:-4] + ".evb")
        if binary is not None:
            return binary

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
        if _real_isfile(candidate):
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


def locate(path):
    """The real file behind a game path, when there is one.

    Bink movies are loose files in the install rather than archive members,
    and ffmpeg would much rather open a file it can seek in than be fed 105 MB
    down a pipe.  Returns None for anything that only exists inside a .he.
    """
    p = _normalise(path)
    for root in [None] + _loose:
        candidate = p if root is None else os.path.join(root, p)
        if _real_isfile(candidate):
            return candidate

    wanted = p.lower()
    for root in _loose:
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                full = os.path.join(dirpath, f)
                rel = os.path.relpath(full, root).replace("\\", "/").lower()
                if rel == wanted:
                    return full
    return None


def has(path):
    """Whether a game path names something, without reading it.

    Archive members and loose files in the data directories count; nothing
    else does.  Cheap enough to answer the game's own existence checks.
    """
    p = _normalise(path)
    if "/" in p:
        head, rest = p.split("/", 1)
        entry = _archives.get(head.lower())
        if entry and rest.lower() in entry[1]:
            return True
    for root in _loose:
        if _real_isfile(os.path.join(root, p)):
            return True
    return False


def install_path_lookup():
    """Let the game's existence checks see its own data.

    The original runs with its install folder as the working directory, so
    a relative game path like interface/shoes_enter.mng is a real file there,
    and the scripts lean on that:

        elif tagName == 'invAnim':
            if os.path.isfile(val) and name != None and name != '':
                self.__curItem.invAnimsDict[name] = val

    The player runs from player/rundir instead, which is what keeps saves
    out of the install -- and every such check quietly failed.  Inventory
    items lost their enter animation, and pj_inventory_manager only shows an
    item `if enterAnim:`, so the inventory never appeared at all.

    A real file is always checked first, so saves behave as before.  Only
    relative paths fall back to the game's data, and never the save folder
    or anything starting with a dot: otherwise saves left in an install by
    the original game could be taken for the player's own.
    """
    def _falls_back(path):
        if not isinstance(path, basestring) or not path:
            return False
        if os.path.isabs(path) or path.startswith("."):
            return False
        first = _normalise(path).split("/", 1)[0].lower()
        return first != "savegames"

    def isfile(path):
        if _real_isfile(path):
            return True
        return _falls_back(path) and has(path)

    def exists(path):
        if _real_exists(path):
            return True
        return _falls_back(path) and has(path)

    os.path.isfile = isfile
    os.path.exists = exists


def exists(path):
    return read(path) is not None


def missing():
    """Paths that were asked for and could not be found."""
    return sorted(_missing)
