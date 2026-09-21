"""Prepare a Yaga game for the player: locate it, unpack its scripts, recover
source, and record what was found.

This runs ONCE per install, under Python 3, because the decompiler is a Python 3
tool.  The player itself then runs under Python 2.7 against the cache this
produces -- the game's code is Python 2, and converting it would silently change
integer division (the game is full of `a / b` on ints, which means floor
division in the language it was written in).

Nothing derived from the game is redistributable, so the cache is written next
to the player on the user's own machine and stays there.  The player ships no
game code; it reads the copy the user already owns.
"""

from __future__ import annotations

import hashlib
import json
import os
import time

from . import pyz

# ScummVM-style identification: md5 of the first 5000 bytes of a key data file.
# These match the detection entries on the ScummVM 'yaga' branch.
KNOWN_GAMES = {
    ("rooms.he", "4ad491932a603d639bad658695d0827d"):
        ("pajama4", "Pajama Sam 4: Life Is Rough When You Lose Your Stuff"),
}

MD5_BYTES = 5000


def partial_md5(path: str, count: int = MD5_BYTES) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        h.update(fh.read(count))
    return h.hexdigest()


def find_data_dirs(exe_dir: str):
    """Directories holding .he archives, for this install.

    A retail install splits them: the small ones sit beside the executable,
    the bulk live in a sibling folder (MaxFiles).
    """
    found = []
    parent = os.path.dirname(os.path.abspath(exe_dir))
    for candidate in [exe_dir] + [os.path.join(exe_dir, d) for d in _subdirs(exe_dir)] \
                               + [os.path.join(parent, d) for d in _subdirs(parent)]:
        try:
            if any(f.lower().endswith(".he") for f in os.listdir(candidate)):
                real = os.path.abspath(candidate)
                if real not in found:
                    found.append(real)
        except OSError:
            continue
    return found


def _subdirs(path: str):
    try:
        return [d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))]
    except OSError:
        return []


def identify(data_dirs):
    """(game_id, title) if this is a game we know, else (None, None)."""
    for d in data_dirs:
        for filename, md5 in list(KNOWN_GAMES):
            path = os.path.join(d, filename)
            if os.path.isfile(path) and partial_md5(path) == md5:
                return KNOWN_GAMES[(filename, md5)]
    return None, None


def extract_pyc(exe_path: str, out_dir: str):
    """Write every module from the PYZ as a .pyc.  Returns the count.

    The PYZ stores marshalled code with no .pyc header, so one is added here.
    """
    os.makedirs(out_dir, exist_ok=True)
    modules = 0
    for name, is_pkg, code, magic in pyz.read_modules(exe_path):
        rel = name.replace(".", "/") + ("/__init__" if is_pkg else "") + ".pyc"
        dest = os.path.join(out_dir, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(magic + b"\x00\x00\x00\x00")  # pyc header: magic + mtime
            fh.write(code)
        modules += 1
    return modules


def extract_boot(exe_path: str, pyc_dir: str, src_dir: str):
    """Bootstrap entries from the outer archive.  Returns (compiled, source).

    Unlike the PYZ, these are NOT uniform: 'm' entries are complete .pyc files
    with their header already in place, and 's' entries are plain source text.
    boot.py is an 's', so the game's entry point needs no decompiling at all.
    """
    compiled = source = 0
    for name, kind, blob in pyz.read_boot_scripts(exe_path):
        if kind == "s":
            dest = os.path.join(src_dir, "_boot", name + ".py")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(blob.rstrip(b"\x00"))   # drop NUL padding
            source += 1
        else:
            dest = os.path.join(pyc_dir, "_boot", name + ".pyc")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(blob)                   # header already present
            compiled += 1
    return compiled, source


def clean_source(path: str) -> int:
    """Remove decompiler artifacts that make the output unparseable.

    uncompyle6 ends every module with a bare `return` at column 0, which is a
    syntax error outside a function -- all 183 modules of Pajama Sam 4 have
    exactly one.  Dropping it is safe: a module-level return does nothing in
    the original bytecode either.
    """
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()
    kept = [ln for ln in lines if ln.rstrip("\r\n").rstrip() != "return"
            or ln.startswith((" ", "\t"))]
    removed = len(lines) - len(kept)
    if removed:
        with open(path, "w", encoding="utf-8") as fh:
            fh.writelines(kept)
    return removed


def decompile(pyc_dir: str, src_dir: str, verbose: bool = False):
    """Recover .py source from the extracted .pyc files.

    Returns (ok, failures) where failures is a list of (module, reason).
    """
    try:
        from uncompyle6.main import decompile_file
    except ImportError:
        raise SystemExit(
            "The decompiler is missing.  Install it with:\n"
            "    pip install uncompyle6\n"
            "It is only needed for this one-time setup, not to play.")

    ok, failures = 0, []
    for dirpath, _dirs, files in os.walk(pyc_dir):
        for f in sorted(files):
            if not f.endswith(".pyc"):
                continue
            src = os.path.join(dirpath, f)
            rel = os.path.relpath(src, pyc_dir)[:-1]          # .pyc -> .py
            dest = os.path.join(src_dir, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            try:
                with open(dest, "w", encoding="utf-8") as out:
                    decompile_file(src, out)
                clean_source(dest)
                ok += 1
                if verbose:
                    print("   %s" % rel)
            except Exception as exc:
                failures.append((rel, "%s: %s" % (type(exc).__name__, exc)))
                if os.path.exists(dest):
                    os.remove(dest)
    return ok, failures


def prepare(game_dir: str, cache_dir: str, verbose: bool = False):
    """Full one-time setup.  Returns the manifest dict it also writes to disk.

    The cache is rebuilt from scratch each time: a stale file from an earlier
    run is worse than no file, because it will be decompiled and believed.
    """
    if os.path.isdir(cache_dir):
        import shutil
        shutil.rmtree(cache_dir, ignore_errors=True)
    exes = pyz.find_executable(game_dir)
    if not exes:
        raise SystemExit(
            "No Yaga executable found in %s\n"
            "Expected a game .exe with an embedded Python archive." % game_dir)
    exe = exes[0]
    info = pyz.describe(exe)
    exe_dir = os.path.dirname(exe)
    data_dirs = find_data_dirs(exe_dir)
    game_id, title = identify(data_dirs)

    print("executable : %s" % os.path.basename(exe))
    print("archive    : %s (%.0f KB, Python %s bytecode)"
          % (info["archive"], info["archive_bytes"] / 1024, info["python_version"]))
    print("data dirs  : %s" % ", ".join(os.path.basename(d) or d for d in data_dirs))
    print("game       : %s" % (title or "unrecognised (continuing anyway)"))

    pyc_dir = os.path.join(cache_dir, "pyc")
    src_dir = os.path.join(cache_dir, "scripts")
    n = extract_pyc(exe, pyc_dir)
    bc, bs = extract_boot(exe, pyc_dir, src_dir)
    print("extracted  : %d modules, %d bootstrap .pyc, %d bootstrap source" % (n, bc, bs))

    total_pyc = sum(1 for _d, _s, fs in os.walk(pyc_dir) for f in fs if f.endswith(".pyc"))
    print("decompiling...")
    ok, failures = decompile(pyc_dir, src_dir, verbose)
    print("recovered  : %d of %d compiled modules" % (ok, total_pyc))
    for mod, why in failures:
        print("   FAILED %s -- %s" % (mod, why))

    manifest = {
        "prepared": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "game_id": game_id,
        "title": title,
        "executable": exe,
        "data_dirs": data_dirs,
        "python_version": info["python_version"],
        "modules_extracted": n,
        "boot_compiled": bc,
        "boot_source": bs,
        "modules_recovered": ok,
        "failures": failures,
        "scripts": os.path.abspath(src_dir),
    }
    os.makedirs(cache_dir, exist_ok=True)
    with open(os.path.join(cache_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    return manifest
