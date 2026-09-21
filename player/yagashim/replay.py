"""Record a session and replay it exactly: the same engine calls, in the same
order, every time.

This is what makes the trace log usable as an oracle.  Anyone reimplementing
the engine -- a ScummVM Yaga engine, say -- can replay a recording here and in
their own engine and compare the two call by call.

    run_game.py --record session.oyr      play; every frame is saved
    run_game.py --replay session.oyr      the same session again, unattended

A game is deterministic given three things, and a recording holds all three:

  * **Input**, per frame.  Not pygame's events but the engine's own: the
    (class, type, elementID, value) events the game's input manager receives.
    That is the interface any engine has to feed, and it keeps a recording
    independent of SDL, pygame and window size.
  * **Time.**  Animations, lipsync, movies, sound lengths and the scripts'
    own waits (`time.clock()` in script.py) all read the clock.  While
    recording or replaying, `time.time` and `time.clock` are one virtual clock
    that stands still within a frame and advances between frames -- by the
    real elapsed time when recording, and by the recorded step when replaying.
  * **Randomness.**  The game seeds `g_Random` from the OS; here every
    unseeded `random.Random` gets the recording's seed, and so does the
    module-level generator the engine blinks characters with.

And one thing the engine itself decides: whether a sound is still playing.
The mixer would answer that in real time, so under record and replay it is
answered from the virtual clock and the sound's length instead (see
yagasound.ISound.isPlaying).

The file is JSON lines: a header, then one line per frame, `[dt, events]`,
each event `[class, type, elementID, value]` or the marker "skip-video".
"""

import json
import random
import time

import _stub

FORMAT = "openyaga-replay"
VERSION = 1
EPOCH = 1000.0           # virtual clocks start here, recorded or replayed

mode = None              # None, "record" or "replay"
_now = EPOCH
_real_time = time.time
_real_clock = time.clock
_last_wall = None
_out = None
_frames = []             # replay: [(dt, events)]
_index = 0
header = {}


def active():
    return mode is not None


def now():
    return _now


def _virtual_time():
    return _now


def _patch(seed):
    """Point the clock and the random generators at the recording."""
    time.time = _virtual_time
    time.clock = _virtual_time

    original_seed = random.Random.seed

    def seed_or_recorded(self, a=None, *args, **kw):
        return original_seed(self, seed if a is None else a, *args, **kw)

    random.Random.seed = seed_or_recorded
    random.seed(seed)


def start_recording(path, **info):
    global mode, _out, _last_wall, header
    seed = int(_real_time() * 1000) & 0x7FFFFFFF
    header = dict(format=FORMAT, version=VERSION, seed=seed, **info)
    _out = open(path, "w")
    _out.write(json.dumps(header) + "\n")
    _last_wall = _real_time()
    mode = "record"
    _patch(seed)
    _stub.LOG.note("recording to %s (seed %d)" % (path, seed))


def start_replay(path):
    global mode, _frames, header
    with open(path) as fh:
        header = json.loads(fh.readline())
        if header.get("format") != FORMAT:
            raise SystemExit("%s is not an openyaga recording" % path)
        if header.get("version") != VERSION:
            raise SystemExit("%s is recording format %s; this player reads %s"
                             % (path, header.get("version"), VERSION))
        _frames = [json.loads(line) for line in fh if line.strip()]
    mode = "replay"
    _patch(header["seed"])
    _stub.LOG.note("replaying %s: %d frames (seed %d)"
                   % (path, len(_frames), header["seed"]))
    return header


def frame_count():
    return len(_frames)


def begin_frame():
    """Advance the virtual clock to this frame's time."""
    global _now, _last_wall
    if mode == "record":
        wall = _real_time()
        _pending["dt"] = round(wall - _last_wall, 6)
        _last_wall = wall
        _now += _pending["dt"]
    elif mode == "replay" and _index < len(_frames):
        _now += _frames[_index][0]


_pending = {"dt": 0.0}


def frame_inputs(live):
    """The engine events for this frame: the live ones (and saved, when
    recording), or the recorded ones when replaying."""
    global _index
    if mode == "replay":
        if _index >= len(_frames):
            return []
        events = _frames[_index][1]
        _index += 1
        return events
    if mode == "record":
        _out.write(json.dumps([_pending["dt"], live]) + "\n")
    return live


def finished():
    return mode == "replay" and _index >= len(_frames)


def close():
    global _out
    if _out is not None:
        _out.close()
        _out = None
