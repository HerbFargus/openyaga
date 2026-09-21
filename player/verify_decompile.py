#!/usr/bin/env python3
"""Check the recovered source against the bytecode it came from.

Decompilers can be confidently wrong.  In Pajama Sam 4, uncompyle6 renders

    self.randomCardList = ['fizzyPoppins', 'evilUnderwear', ... 'pajamaMan']

as

    self.randomCardList = [1, 2, 3, ... 24]

which parses, runs, and produces nonsense -- `val + 'CU'` then raises TypeError
instead of building 'pajamaManCU'.  Nothing downstream can catch that, because
the source is perfectly valid Python.

So this compares the *string constants* of every function in the original .pyc
against the same function recompiled from the recovered .py.  Strings are the
useful signal: they are asset names, dictionary keys and messages, they survive
compilation unchanged, and they are what a mis-decompilation like the above
destroys.  Numeric constants are skipped, since 2.2 and 2.7 fold them
differently.

Needs both interpreters: Python 3 with xdis to read 2.2 bytecode, and Python
2.7 to compile the recovered source.

    python verify_decompile.py [--python2 C:\\Python27\\python.exe]
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "gamecache")

# Run under Python 2.7: compile each recovered module and dump its strings.
PY2_DUMP = r'''
import json, os, sys

def walk(co, path, out):
    # latin-1 so arbitrary bytes survive the JSON round trip
    strings = [c.decode("latin-1") for c in co.co_consts if isinstance(c, str)]
    out.setdefault(path, []).extend(strings)
    for c in co.co_consts:
        if hasattr(c, "co_name"):
            walk(c, path + "/" + c.co_name, out)

root, dest = sys.argv[1], sys.argv[2]
result = {}
for dirpath, _dirs, files in os.walk(root):
    for f in sorted(files):
        if not f.endswith(".py"):
            continue
        full = os.path.join(dirpath, f)
        rel = os.path.relpath(full, root).replace("\\", "/")[:-3]
        try:
            src = open(full, "rb").read().replace("\r\n", "\n")
            co = compile(src, full, "exec")
        except Exception, exc:
            result[rel] = {"__error__": str(exc)}
            continue
        out = {}
        walk(co, "", out)
        result[rel] = out
open(dest, "w").write(json.dumps(result))
'''


def originals(pyc_dir):
    """{module: {function path: [strings]}} straight from the 2.2 bytecode."""
    try:
        from xdis import load_module
    except ImportError:
        sys.exit("needs xdis (comes with uncompyle6): pip install uncompyle6")

    def walk(co, path, out, docs=None):
        if docs is not None:
            first = co.co_consts[0] if co.co_consts else None
            if isinstance(first, (bytes, bytearray)):
                first = bytes(first).decode("latin-1")
            docs[path] = first if isinstance(first, str) else None
        strings = []
        for c in co.co_consts:
            if isinstance(c, (bytes, bytearray)):
                strings.append(bytes(c).decode("latin-1"))
            elif isinstance(c, str):
                strings.append(c)
        out.setdefault(path, []).extend(strings)
        for c in co.co_consts:
            if hasattr(c, "co_name"):
                walk(c, path + "/" + c.co_name, out, docs)

    result, alldocs = {}, {}
    for dirpath, _dirs, files in os.walk(pyc_dir):
        for f in sorted(files):
            if not f.endswith(".pyc"):
                continue
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, pyc_dir).replace("\\", "/")[:-4]
            try:
                code = load_module(full)[3]
            except Exception as exc:
                result[rel] = {"__error__": str(exc)}
                continue
            out, docs = {}, {}
            walk(code, "", out, docs)
            result[rel] = out
            alldocs[rel] = docs
    return result, alldocs


def recovered(src_dir, python2):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(PY2_DUMP)
        script = fh.name
    dest = script + ".json"
    try:
        proc = subprocess.run([python2, script, src_dir, dest],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            sys.exit("Python 2 pass failed:\n%s" % (proc.stderr or proc.stdout))
        with open(dest) as fh:
            return json.load(fh)
    finally:
        for p in (script, dest):
            if os.path.exists(p):
                os.remove(p)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--python2", default=r"C:\Python27\python.exe")
    ap.add_argument("--cache", default=CACHE)
    ap.add_argument("--show", type=int, default=12, help="how many mismatches to detail")
    args = ap.parse_args()

    pyc_dir = os.path.join(args.cache, "pyc")
    src_dir = os.path.join(args.cache, "scripts")
    if not os.path.isdir(pyc_dir):
        sys.exit("no prepared game at %s -- run setup_game.py first" % args.cache)

    print("reading original bytecode...")
    orig, docs = originals(pyc_dir)
    print("recompiling recovered source under Python 2...")
    recov = recovered(src_dir, args.python2)

    # Modules PyInstaller bundled from the Python 2.2 standard library, as
    # opposed to the game's own code.  Both are checked, but only the game's
    # matter for correctness of the player.
    STDLIB = set("""ConfigParser UserDict __future__ codecs copy copy_reg dospath
        getopt linecache macpath ntpath os popen2 posixpath pre random re repr sre
        sre_compile sre_constants sre_parse stat string tempfile traceback types""".split())

    def is_stdlib(module):
        return module.split("/")[0] in STDLIB or module.startswith(("encodings/", "_boot/"))

    def classify(lost, extra, doc):
        """What kind of difference is this?"""
        if lost and not extra and all(s == doc for s in lost):
            return "docstring"
        if not lost and extra:
            return "extra"
        if lost and all(isinstance(s, str) and len(s) < 64 and chr(10) not in s
                        for s in lost):
            return "DATA"          # short identifier-like strings went missing
        return "text"              # prose: messages, docstrings of inner scopes

    bad, checked, missing = [], 0, 0
    for module, funcs in sorted(orig.items()):
        if module not in recov:
            missing += 1
            continue
        other = recov[module]
        if "__error__" in other or "__error__" in funcs:
            bad.append((module, "", "did not compile", ""))
            continue
        for path, strings in sorted(funcs.items()):
            checked += 1
            a, b = sorted(strings), sorted(other.get(path, []))
            if a != b:
                lost = [s for s in a if s not in b]
                extra = [s for s in b if s not in a]
                kind = classify(lost, extra, docs.get(module, {}).get(path))
                bad.append((module, path or "<module>", lost, kind,
                            "stdlib" if is_stdlib(module) else "game"))

    print()
    print("functions checked : %d" % checked)
    print("modules missing   : %d" % missing)
    print("MISMATCHES        : %d" % len(bad))
    print()

    counts = {}
    for _m, _p, _l, kind, origin in bad:
        counts[(origin, kind)] = counts.get((origin, kind), 0) + 1
    print("   %-8s %-10s %s" % ("origin", "kind", "count"))
    for (origin, kind), n in sorted(counts.items()):
        print("   %-8s %-10s %d" % (origin, kind, n))

    # A second, separate failure: Python 2 list comprehensions accumulate into
    # a temporary named `_[1]`.  When uncompyle6 cannot reconstruct the
    # comprehension it emits that raw name, losing the element expression --
    # `[_[1] for vector in vectors]` was `[vector[0] for vector in vectors]`.
    # No strings go missing, so the comparison above cannot see it.
    import re as _re
    broken_comprehensions = []
    for dirpath, _dirs, files in os.walk(src_dir):
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, src_dir).replace("\\", "/")
            with open(full, encoding="utf-8", errors="replace") as fh:
                for n, line in enumerate(fh, 1):
                    if _re.search(r'_\[\d', line):
                        broken_comprehensions.append((rel, n, line.strip()))

    serious = [b for b in bad if b[3] == "DATA"]
    print()
    print("needs attention (short strings lost, not docstrings): %d" % len(serious))
    for module, path, lost, kind, origin in serious[:args.show]:
        print()
        print("   [%s] %s  %s" % (origin, module, path))
        print("      lost: %s%s" % (lost[:8], " ..." if len(lost) > 8 else ""))
    if len(serious) > args.show:
        print()
        print("   ... and %d more" % (len(serious) - args.show))

    print()
    print("lost list comprehensions (`_[1]` left in place): %d"
          % len(broken_comprehensions))
    for rel, n, line in broken_comprehensions[:args.show]:
        print("   %s:%d  %s" % (rel, n, line[:70]))

    return 1 if (serious or broken_comprehensions) else 0


if __name__ == "__main__":
    sys.exit(main())
