#!/usr/bin/env python3
"""Prepare an installed Yaga game so the player can run it.

    python setup_game.py "C:/.../Atari/Pajama Sam LRS"

Run once. Needs Python 3 and uncompyle6; the player itself needs neither.
"""
import argparse, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from yagaboot import bootstrap


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game_dir", help="folder holding the game .exe")
    ap.add_argument("--cache", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "gamecache"),
                    help="where to put the prepared scripts (default: ./gamecache)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    m = bootstrap.prepare(args.game_dir, args.cache, args.verbose)
    print()
    print("ready: %s" % m["scripts"])
    if m["failures"]:
        print("%d module(s) could not be recovered -- see manifest.json" % len(m["failures"]))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
