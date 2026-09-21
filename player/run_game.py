# -*- coding: utf-8 -*-
"""Run the game's own boot script against the stub engine, and record what it asks for.

    C:\\Python27\\python.exe run_game.py

This is step 2 of the player: nothing renders.  The game's scripts execute for
real, against stand-ins that log every engine call, so the order in which the
engine is actually needed comes from the game itself.

Requires Python 2.7 -- the game's code is Python 2.
"""

import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
SHIMS = os.path.join(HERE, "yagashim")
CACHE = os.path.join(HERE, "gamecache")


_pending = {}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=0,
                    help="stop after this many rendered frames")
    ap.add_argument("--screenshot", help="save the last frame here")
    ap.add_argument("--scene", help="start in this scene instead of the logo")
    ap.add_argument("--click", help="inject a click at X,Y (for testing)")
    args = ap.parse_args()

    if sys.version_info[0] != 2:
        sys.exit("run_game.py needs Python 2.7 (found %d.%d).  Try:\n"
                 "    C:\\Python27\\python.exe run_game.py"
                 % sys.version_info[:2])

    manifest_path = os.path.join(CACHE, "manifest.json")
    if not os.path.isfile(manifest_path):
        sys.exit("No prepared game found.  Run setup_game.py first (Python 3).")
    manifest = json.load(open(manifest_path))

    scripts = manifest["scripts"]
    boot = os.path.join(scripts, "_boot", "boot.py")
    if not os.path.isfile(boot):
        sys.exit("boot.py missing from %s" % scripts)

    # Stubs first so `import yagascene` finds ours, then the game's own modules.
    sys.path.insert(0, scripts)
    sys.path.insert(0, SHIMS)

    import _stub
    log_path = os.path.join(HERE, "trace.log")
    _stub.LOG.open(log_path)
    _stub.LOG.note("=== %s ===" % manifest.get("title", "unknown game"))

    # The engine resolves paths like "data/scenes.xml" against the .he archives.
    import resources
    n = resources.init(manifest["data_dirs"])
    _stub.LOG.note("indexed %d archives" % n)

    # Resolve output paths before the chdir below, so nothing lands in the
    # player's game folder.
    _stub.FRAME_LIMIT = args.frames
    _stub.SCREENSHOT = os.path.abspath(args.screenshot) if args.screenshot else None
    if args.click:
        _stub.CLICK_AT = tuple(int(v) for v in args.click.split(","))

    # The game resolves data paths relative to the executable's folder.
    exe_dir = os.path.dirname(manifest["executable"])
    if os.path.isdir(exe_dir):
        os.chdir(exe_dir)

    if args.scene:
        # globals.py needs the true/false builtins boot.py installs; set them
        # early so it can be imported before boot runs.  boot.py sets them
        # again, harmlessly.
        import __builtin__
        __builtin__.False, __builtin__.True = 0, 1
        __builtin__.false, __builtin__.true = 0, 1
        import globals as game_globals
        print "starting in scene %r instead of %r" % (args.scene, game_globals.INITIAL_SCENE)
        game_globals.INITIAL_SCENE = args.scene

    real_stdout, real_stderr = sys.stdout, sys.stderr
    sys.argv = ["boot.py"]

    outcome = "ran to completion"
    try:
        execfile(boot, {"__name__": "__main__", "__file__": boot, "__builtins__": __builtins__})
    except SystemExit, exc:
        outcome = "sys.exit(%r)" % (exc.code,)
    except Exception, exc:
        outcome = "%s: %s" % (type(exc).__name__, exc)
        _stub.LOG.note("STOPPED: %s\n%s" % (outcome, traceback.format_exc()))
    finally:
        # boot.py replaces stdout with its own redirector; take it back.
        sys.stdout, sys.stderr = real_stdout, real_stderr

    report(_stub.LOG, outcome, log_path)


def report(log, outcome, log_path):
    print
    print "stopped after %d engine calls: %s" % (log.seq, outcome)
    print

    by_module = {}
    for _seq, kind, target, _detail in log.events:
        mod = target.split(".")[0]
        by_module.setdefault(mod, set()).add(target)
    print "engine surface actually touched:"
    for mod in sorted(by_module, key=lambda m: -len(by_module[m])):
        print "   %-20s %3d distinct names" % (mod, len(by_module[mod]))

    print
    print "first 25 engine calls, in the order the game made them:"
    shown = 0
    for seq, kind, target, detail in log.events:
        if kind not in ("call", "new"):
            continue
        print "   %-6s %-44s %s" % (kind, target, detail[:40])
        shown += 1
        if shown >= 25:
            break

    print
    print "most requested:"
    for target, n in sorted(log.counts.items(), key=lambda kv: -kv[1])[:12]:
        print "   %-48s x%d" % (target, n)

    print
    print "full trace: %s" % log_path
    log.close()


if __name__ == "__main__":
    main()
