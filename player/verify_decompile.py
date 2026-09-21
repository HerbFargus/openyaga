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

    def walk(co, path, out):
        strings = []
        for c in co.co_consts:
            if isinstance(c, (bytes, bytearray)):
                strings.append(bytes(c).decode("latin-1"))
            elif isinstance(c, str):
                strings.append(c)
        out.setdefault(path, []).extend(strings)
        for c in co.co_consts:
            if hasattr(c, "co_name"):
                walk(c, path + "/" + c.co_name, out)

    result = {}
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
            out = {}
            walk(code, "", out)
            result[rel] = out
    return result


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
    orig = originals(pyc_dir)
    print("recompiling recovered source under Python 2...")
    recov = recovered(src_dir, args.python2)

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
                bad.append((module, path or "<module>", lost, b))

    print()
    print("functions checked : %d" % checked)
    print("modules missing   : %d" % missing)
    print("MISMATCHES        : %d" % len(bad))
    for module, path, lost, got in bad[:args.show]:
        print()
        print("   %s  %s" % (module, path))
        if isinstance(lost, str):
            print("      %s" % lost)
        else:
            print("      strings lost : %s" % (lost[:6],))
    if len(bad) > args.show:
        print()
        print("   ... and %d more" % (len(bad) - args.show))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
