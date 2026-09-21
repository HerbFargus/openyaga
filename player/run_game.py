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


def install_hit_probe():
    """Wrap utility.CursorOverSprite and report which bound rejects a sprite.

    The four comparisons are all strict:
        x > rect.x  and  x < rect.x + w  and  y > rect.y  and  y < rect.y + h
    so a sprite can be rejected for a reason that is not obvious from outside.
    """
    import __builtin__
    __builtin__.False, __builtin__.True = 0, 1
    __builtin__.false, __builtin__.true = 0, 1

    import _stub
    from python_shared.utility import utility as _u
    original = _u.CursorOverSprite
    seen = {}

    def probe(sprite, rectOnly=0):
        import globals as game_globals
        result = original(sprite, rectOnly)
        try:
            rect = sprite.renderRect
            x = game_globals.g_Cursor.screenX()
            y = game_globals.g_Cursor.screenY()
            rx, ry = rect.x, rect.y
            rw, rh = rect.width, rect.height
            checks = [("x>rect.x", x > rx), ("x<rect.right", x < rx + rw),
                      ("y>rect.y", y > ry), ("y<rect.bottom", y < ry + rh)]
            failed = [name for name, ok in checks if not ok]
            locator = getattr(getattr(sprite, "anim", None), "locator", "?")
            key = (locator, tuple(failed))
            if key not in seen:
                seen[key] = True
                _stub.LOG.record("call", "hit.CursorOverSprite",
                                 "%s cursor=(%s,%s) rect=(%s,%s %sx%s) "
                                 "failed=%s enabled=%s -> %s"
                                 % (locator, x, y, rx, ry, rw, rh,
                                    failed or "none",
                                    game_globals.g_Cursor.enabled, result))
        except Exception, exc:
            _stub.LOG.record("call", "hit.probe", "error: %s" % exc)
        return result

    _u.CursorOverSprite = probe


def install_click_probe():
    """Report what the room saw when a mouse button went down.

    room_manager.DefaultInputHandler walks every interactive object in the
    room, keeps the ones whose InBounds() is true, and clicks the topmost.
    A click that does nothing failed at one of those steps, and from outside
    they are indistinguishable.
    """
    import _stub
    from python_shared.adventure import room_manager as _rm
    import yagaevents
    original = _rm.CRoomManager.DefaultInputHandler

    def probe(self, message):
        import globals as game_globals
        down = (message.eventClass == yagaevents.EEventClass.CLASS_MOUSE
                and message.eventType == yagaevents.EInputEvent.IEVENT_BUTTON_DOWN)
        if down:
            cursor = game_globals.g_Cursor
            names, inbounds = [], []
            for obj in self.interactiveObjects:
                name = getattr(obj, "debugName", None) or obj.__class__.__name__
                names.append(name)
                try:
                    if obj.InBounds():
                        inbounds.append("%s@z%s" % (name, obj.position.z))
                except Exception, exc:
                    inbounds.append("%s!%s" % (name, type(exc).__name__))
            _stub.LOG.record("call", "click.DefaultInputHandler",
                             "cursor=(%s,%s) enabled=%s hourglass=%s item=%s "
                             "objects=%d hit=%s"
                             % (cursor.screenX(), cursor.screenY(),
                                cursor.enabled, cursor.hourglassCursor,
                                cursor.itemOnCursor, len(names),
                                inbounds or "none"))
        return original(self, message)

    _rm.CRoomManager.DefaultInputHandler = probe

    # Rollover: what the room found under a moving pointer, and whether it
    # got as far as changing the cursor.
    move_original = _rm.CRoomManager.HandleMouseMoveEvent
    seen_move = {}

    def move_probe(self):
        import globals as game_globals
        cursor = game_globals.g_Cursor
        inbounds = []
        for obj in self.interactiveObjects:
            try:
                if obj.InBounds():
                    inbounds.append(getattr(obj, "debugName", None)
                                    or obj.__class__.__name__)
            except Exception, exc:
                inbounds.append("!%s" % type(exc).__name__)
        key = tuple(inbounds)
        if key not in seen_move:
            seen_move[key] = True
            _stub.LOG.record("call", "hover.HandleMouseMoveEvent",
                             "cursor=(%s,%s) type=%s over=%s"
                             % (cursor.screenX(), cursor.screenY(),
                                cursor.GetCursorType(), inbounds or "nothing"))
        return move_original(self)

    _rm.CRoomManager.HandleMouseMoveEvent = move_probe

    from python_shared.adventure import clickpoint as _cp2
    roll_original = _cp2.CClickPoint.Rollover
    seen_roll = [0]

    def roll_probe(self):
        import globals as game_globals
        if seen_roll[0] < 4:
            seen_roll[0] += 1
            _stub.LOG.record("call", "hover.Rollover",
                             "%s myRegion=%s itemOnCursor=%r"
                             % (self.__class__.__name__,
                                getattr(self, "myRegion", "?"),
                                game_globals.g_Cursor.itemOnCursor))
        return roll_original(self)

    _cp2.CClickPoint.Rollover = roll_probe

    from python_shared.adventure import cursor as _cursor_mod
    change_original = _cursor_mod.CCursor.ChangeCursor
    seen_change = [0]

    def change_probe(self, cursorType, itemName=None):
        if seen_change[0] < 6:
            seen_change[0] += 1
            _stub.LOG.record("call", "hover.ChangeCursor",
                             "%r item=%r hourglass=%r"
                             % (cursorType, itemName, self.hourglassCursor))
        return change_original(self, cursorType, itemName)

    _cursor_mod.CCursor.ChangeCursor = change_probe

    # And the clickpoint instances, which advance their own animation on a
    # counter rather than through the sprite's clock.
    from python_shared.adventure import clickpoint as _cp
    inst_tick = _cp.CClickPointInstance.Tick
    seen_tick = [0]

    def tick_probe(self):
        private = lambda n: getattr(self, "_CClickPointInstance__" + n, "?")
        if seen_tick[0] < 8:
            seen_tick[0] += 1
            sprite = private("sprite")
            try:
                speed = self.GetTickSpeed()
            except Exception, exc:
                speed = "%s: %s" % (type(exc).__name__, exc)
            _stub.LOG.record("call", "click.InstanceTick",
                             "onScreen=%s speed=%s animTick=%s frame=%s/%s"
                             % (private("onScreen"), speed,
                                private("animationTick"),
                                getattr(sprite, "currentFrame", "?"),
                                getattr(sprite, "frameCount", "?")))
        return inst_tick(self)

    _cp.CClickPointInstance.Tick = tick_probe

    # And every write to cursor.enabled, with the line that made it.  A
    # cutscene disables the cursor and re-enables it when it ends; if the
    # cursor stays off, the game is still waiting for something.
    from python_shared.adventure import cursor as _cursor
    import traceback as _tb

    stack_log = os.path.join(HERE, "cursor_enabled.log")
    open(stack_log, "w").close()

    def cursor_setattr(self, name, value):
        if name == "enabled":
            _stub.LOG.record("set", "cursor.enabled",
                             "= %s (stack in cursor_enabled.log)" % (value,))
            f = open(stack_log, "a")
            f.write("=== enabled = %s ===" % (value,) + chr(10))
            f.writelines(_tb.format_stack()[:-1])
            f.close()
        self.__dict__[name] = value

    _cursor.CCursor.__setattr__ = cursor_setattr

    # And the script items, which is what a cutscene waits on before it hands
    # control back.
    from script_system import script as _script
    was_playing = _script.CPlayListItem.isPlaying
    seen_item = {}

    def playing_probe(self):
        result = was_playing(self)
        sound = getattr(self, "soundObj", 0)
        key = (id(self), bool(result))
        if key not in seen_item:
            seen_item[key] = True
            _stub.LOG.record("call", "script.isPlaying",
                             "%s -> %s  wait=%s sound=%s sound.isPlaying=%s "
                             "anim=%s time=%s/%s"
                             % (getattr(self, "soundFile", "?"), result,
                                getattr(self, "wait", "?"),
                                _stub._brief(sound),
                                getattr(sound, "isPlaying", "-") if sound else "-",
                                _stub._brief(getattr(self, "animObj", 0)),
                                _stub._brief(getattr(getattr(self, "speakerObj", 0), "time", "-")),
                                _stub._brief(getattr(getattr(self, "speakerObj", 0), "duration", "-"))))
        return result

    _script.CPlayListItem.isPlaying = playing_probe


def _exit_quietly():
    """Leave without running the interpreter's shutdown.

    Python 2 clears module globals and then runs whatever __del__ methods
    remain, so the game's destructors all fail on globals that are suddenly
    None and print pages of

        Exception AttributeError: "'NoneType' object has no attribute ..."
        in <bound method CPJInventoryItem.__del__ ...> ignored

    Filtering sys.stderr does not help: by then sys itself has been torn down
    and Python writes to the C stderr directly.  So flush everything that
    matters and leave via os._exit, which skips finalisation entirely.  The
    game has already finished by this point -- boot.py has printed its "Fin."
    -- so there is nothing left to tear down that we care about.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    # The game's own log is an ordinary file object somewhere in its module
    # graph; flush any that are still open so the log is complete.
    import gc
    for obj in gc.get_objects():
        if isinstance(obj, file) and not obj.closed and obj.mode.startswith("w"):
            try:
                obj.flush()
            except Exception:
                pass
    os._exit(0)


_pending = {}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=0,
                    help="stop after this many rendered frames")
    ap.add_argument("--screenshot", help="save the last frame here")
    ap.add_argument("--scene", help="start in this scene instead of the logo")
    ap.add_argument("--skip-video", action="store_true",
                    help="treat movies as zero length (we cannot draw them)")
    ap.add_argument("--debug-hit", action="store_true",
                    help="log every CursorOverSprite test and which bound failed")
    ap.add_argument("--click", action="append", default=[],
                    help="inject a click: X,Y or X,Y@FRAME (repeatable)")
    ap.add_argument("--hover", action="append", default=[],
                    help="move the pointer without clicking: X,Y@FRAME")
    ap.add_argument("--subtitles", action="store_true",
                    help="show the dialogue text (the game defaults it off)")
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

    # The game ships its own Python 2.2 standard library (PyInstaller bundled
    # os, re, string, tempfile and friends), and those sit on the path ahead of
    # the real ones.  The game is welcome to them -- it was built against them
    # -- but our shims are not: the 2.2 tempfile has no mkstemp, for one.
    # Importing them here, before the game's directory joins the path, puts the
    # real modules in sys.modules where every later import will find them.
    import struct, zlib, zipfile, tempfile, time, re, hashlib  # noqa: F401
    import xml.parsers.expat  # noqa: F401

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
    _stub.SKIP_VIDEO = args.skip_video
    _stub.TRACE_STATE = args.debug_hit
    for n, spec in enumerate(args.click):
        coords, _, frame = spec.partition("@")
        x, y = (int(v) for v in coords.split(","))
        _stub.CLICKS.append((int(frame) if frame else 5 + n * 25, x, y))
    for n, spec in enumerate(args.hover):
        coords, _, frame = spec.partition("@")
        x, y = (int(v) for v in coords.split(","))
        _stub.HOVERS.append((int(frame) if frame else 5 + n * 25, x, y))

    # Run from our own directory, not the game's.  The game writes its saves
    # to "./SaveGames" and its log to "./<project>.log", both relative to the
    # working directory, so running from the install would litter -- and
    # mutate -- a copy the player owns.  Assets do not care: the resource
    # layer resolves them through absolute paths from the manifest.
    rundir = os.path.join(HERE, "rundir")
    if not os.path.isdir(rundir):
        os.makedirs(rundir)
    os.chdir(rundir)

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

    if args.subtitles:
        # The game keeps this off by default and offers it in the options
        # menu; its 't' shortcut is behind DEBUG_BUILD, which retail sets to
        # 0.  Setting the flag rather than calling EnableSubtitles: that also
        # reaches for the current line's text sprite, and at this point there
        # is no scene yet to have one.
        def enable_subtitles():
            import globals as game_globals
            game_globals.g_GameOptions.display.subtitlesOn = 1
            _stub.LOG.record("call", "options.subtitlesOn", "= 1")
        _stub.FIRST_FRAME_HOOKS.append(enable_subtitles)

    if args.debug_hit:
        install_hit_probe()
        _stub.FIRST_FRAME_HOOKS.append(install_click_probe)

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
        # Only now: the game's Release() runs after the loop and still uses
        # the mixer, so tearing pygame down any earlier breaks it.
        try:
            import yagasound, yagagraphics
            yagasound.cleanup()
            yagagraphics.shutdown()
        except Exception:
            pass

    report(_stub.LOG, outcome, log_path)
    _exit_quietly()



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
