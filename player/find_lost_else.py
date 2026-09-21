#!/usr/bin/env python3
"""Check every if/elif chain in the recovered scripts for a lost `else:`.

    python find_lost_else.py [--cache gamecache]

See yagaboot/lostelse.py for what a lost else is and how the bytecode tells
it apart from a genuine elif chain.  Setup repairs every lost else it can
place (lostelse.repair), so on a finished gamecache this should report none;
anything it does print is a case setup could not place or could not judge.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from yagaboot import lostelse  # noqa: E402


def modules(cache):
    scripts = os.path.join(cache, "scripts")
    pyc = os.path.join(cache, "pyc")
    for dirpath, _dirs, files in os.walk(scripts):
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            src = os.path.join(dirpath, f)
            rel = os.path.relpath(src, scripts)[:-3]
            compiled = os.path.join(pyc, rel + ".pyc")
            if os.path.isfile(compiled):
                yield rel.replace("\\", "/"), src, compiled


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache", default=os.path.join(HERE, "gamecache"))
    args = ap.parse_args()

    from xdis import load_module

    results = []
    for rel, src, compiled in modules(args.cache):
        source = open(src, encoding="latin-1").read()
        try:
            code = load_module(compiled)[3]
        except Exception as exc:
            print("skip %s: %s" % (rel, exc))
            continue
        for r in lostelse.scan(source, code):
            results.append((rel, r))

    order = {"lost-else": 0, "undetermined": 1, "ok": 2}
    results.sort(key=lambda x: (order[x[1]["verdict"]], x[0], x[1]["stmt"]))
    counts = {}
    for rel, r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    print("%d candidates: %s" % (len(results), ", ".join(
        "%s %d" % (k, counts.get(k, 0)) for k in ("lost-else", "undetermined", "ok"))))
    for rel, r in results:
        if r["verdict"] == "ok":
            continue
        print("%-12s %s:%d  %s  -- %s" % (r["verdict"], rel, r["stmt"] + 1,
                                           r["stmt_text"][:48], r["why"]))
    return 1 if counts.get("lost-else") else 0


if __name__ == "__main__":
    sys.exit(main())
