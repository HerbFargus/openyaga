# Yaga player

A standalone player for the Humongous/Atari Yaga games, built around the game's
*own* Python scripts rather than a reimplementation of its logic.

**Status: Pajama Sam 4 and Putt-Putt: Pep's Birthday Surprise both play start
to finish**, on Windows and Linux,
with SDL2 window scaling, saves interchangeable with the original, and
exact record/replay.

## How it works

Yaga games are a C++ engine (`yaga*.dll`) driving Python 2.2 game scripts. The
scripts are bundled inside the game executable by McMillan Installer, the tool
that became PyInstaller.

That means the game's *logic* doesn't need reimplementing — only the engine
underneath it. So this project:

1. reads the scripts out of the executable **the user already owns**,
2. recovers them as source on the user's machine,
3. and provides the eleven `yaga*` modules the scripts import (`yagashim/`),
   backed by SDL.

[../ENGINE_API.md](../ENGINE_API.md) lists that interface as the game uses it,
with the rules behind it; [../FORMATS.md](../FORMATS.md) covers the data
formats.

## What ships and what doesn't

This project contains **no game code**, and must stay that way. The user supplies
their own installed copy; everything derived from it is written to `gamecache/`
on their machine and never travels. `gamecache/` is gitignored — keep it that
way, it holds a reconstruction of the game's copyrighted source.

## Setup on Linux and macOS

One script does everything, inside `player/` and without `sudo`:

```bash
player/setup.sh "/path/to/Pajama Sam LRS"
player/play.sh
```

The folder is an installed copy of the game -- from a Windows install, or a
Wine prefix (`~/.wine/drive_c/Program Files (x86)/Atari/Pajama Sam LRS`).
`setup.sh` recovers the scripts (below), builds the runtime -- Python 2.7 with
pygame 2.0.3 -- and finds ffmpeg, using what the system has first: python3
with venv, a `python2.7` on PATH (or `PYTHON27`), ffmpeg on PATH. Whatever is
missing comes from conda-forge through micromamba, a single-file conda
installer fetched into `player/.tools`. It ends with a short headless run to
check the player starts, and says if SDL cannot open a sound device.

Tested on a stock Ubuntu 26.04 (WSL) with no `python3-venv`, no Python 2, no
ffmpeg and no bzip2: setup completes without a password, the game runs in a
window, movies and dialogue decode, and a session recorded on Windows
replays on Linux with an identical trace (75,597 lines). Minimal installs
like that one lack the system audio libraries (`libasound2t64 libpulse0` on
Ubuntu); setup names them.

| Platform | Status |
|---|---|
| Linux x86_64 | tested (Ubuntu 26.04 under WSL): picture, music, dialogue, effects, replay |
| macOS, Intel | prebuilt Python 2.7 and pygame; untested |
| macOS, Apple Silicon | the Intel build under Rosetta; neither Python 2.7 nor its pygame exists for arm64; untested |
| Linux ARM | Python 2.7 is prebuilt, pygame builds from source (needs the SDL2 dev packages); untested |

`play.sh` takes every `run_game.py` flag.

## Setup on Windows (one time, Python 3)

```bash
pip install uncompyle6
python setup_game.py "C:/Program Files (x86)/Atari/Pajama Sam LRS"
```

This finds the executable by scanning for the archive cookie (so it works for
any Yaga title, not just Pajama Sam 4), identifies the game by a ScummVM-style
partial MD5, unpacks the archive and recovers the source:

```
executable : PajamaLRS.exe
archive    : out1.pyz (800 KB, Python 2.2 bytecode)
data dirs  : Pajama Sam LRS, MaxFiles
game       : Pajama Sam 4: Life Is Rough When You Lose Your Stuff
extracted  : 183 modules, 2 bootstrap .pyc, 3 bootstrap source
recovered  : 185 of 185 compiled modules
```

Results land in `gamecache/`: `pyc/` (raw extracted bytecode), `scripts/`
(recovered source), and `manifest.json` (what was found, where the data lives).

## Why Python 2.7 for the player

The game's code is Python 2 and it is full of integer division —
`print_manager.py` has `c_FrameRateMod = 3 / 2`, which is `1` in Python 2 and
`1.5` in Python 3. No automatic converter can fix that, because it needs types
to know which `/` should become `//`. Running under 2.7 keeps the semantics the
code was written against.

Setup runs under Python 3 because the decompiler is a Python 3 tool; the player
will run under 2.7 against the cache. Porting the player to 3.x later is
possible but means auditing every division in 183 modules.

## Notes on the archive format

Three things here are easy to get wrong, all found the hard way:

- The **PYZ table of contents** is a Python 2 marshal dict, which Python 3's
  `marshal` cannot read. The type codes it uses are decoded by hand in
  `yagaboot/pyz.py`, including `l` (long) for the file offsets.
- The PYZ's TOC offset field is **little-endian** here while the outer archive
  is big-endian, so the reader takes whichever value lands inside the blob.
- Outer archive entries are **not uniform**. `'m'` entries are complete `.pyc`
  files with headers already present; `'s'` entries are plain source text. And
  the per-entry compression flag lies — `_mountzlib` is flagged compressed but
  stored raw — so decompression is attempted and falls back to the raw bytes.

`boot.py` is an `'s'` entry, which means the game's entry point comes out as
original source, comments intact. It is where `true`/`false` are defined:

```python
__builtin__.false = __builtin__.False
__builtin__.true  = __builtin__.True
```

They appear nowhere in the game's own modules, so anything that runs these
scripts must execute `boot.py` first.

## Playing

```bash
C:\Python27\python.exe -m pip install pygame==2.0.3
C:\Python27\python.exe run_game.py
```

Opens a window and boots the game the way it boots itself: Atari logo,
Humongous logo, then the first room. Close the window to quit. Escape is the
game's: it opens the options menu, as it did in the original.

**The window.** The game draws its fixed 640x480 picture and the player
scales it to the window, keeping the 4:3 shape (`yagashim/display.py`). The
window opens at the largest whole multiple of 640x480 that fits the screen,
and can be resized freely.

| key | flag | |
|---|---|---|
| F11 or Alt+Enter | `--fullscreen` / `--windowed` | borderless fullscreen at the desktop's resolution |
| F10 | `--integer` / `--fit` | whole multiples only (2x, 3x) for crisp pixels, or fill the window |
| F12 | `--smooth` / `--sharp` | filtered or nearest-neighbour scaling |
| | `--scale N` | starting window size, N x 640x480 |

Choices made with the keys are remembered in `player/display.json`. The game
itself uses F2 and F6-F9, so none of these take a key it listens for. The
player declares itself DPI aware, so on a high-DPI screen the picture is
scaled once, by the player, instead of again by Windows.

**Saving and loading** work as in the original: Escape, then Save, and the
game photographs the room onto your cursor -- drop it in a slot, type a name,
press Enter. Load shows the photos back. Saves go to `player/rundir/SaveGames`
(`.dat` for the game, `.img` for the thumbnail), not into the install.

Saves are interchangeable with the original game, in both directions --
confirmed by loading the original's saves here and these in the original.
Copy the `.dat` and `.img` pair between the two `SaveGames` folders to carry
a playthrough across; the original's is in its install folder, so copying
into it needs administrator rights.

| key | does |
|---|---|
| Escape | the options menu (not on the map, the logos, the TV room or a few minigames) |
| Space or `.` | cut the current line of dialogue short |
| any key or click | cut a movie short |

**Dialogue and movies need ffmpeg.** SDL cannot open either format the game
ships them in, so both go through ffmpeg. Nothing is bundled and nothing is
downloaded behind your back; on Windows there is a script that will fetch it:

```bash
python get_ffmpeg.py
```

That downloads one pinned LGPL build from BtbN/FFmpeg-Builds, checks it
against a SHA-256 recorded in the script, and puts `ffmpeg.exe` beside
`run_game.py`. On macOS or Linux you do not need it: `brew install ffmpeg` or
`apt install ffmpeg` puts ffmpeg on `PATH`, which is searched anyway.

The player looks in `OPENYAGA_FFMPEG`, then on `PATH`, then at
`player/ffmpeg.exe`, then in the usual install directories. Without any of
them it still runs, with the old behaviour described below each heading.

openyaga stays MIT and is not a derivative work of ffmpeg -- it runs it as a
separate program over a pipe. The binary is under its own licence. We only
decode, and `binkvideo`, `binkaudio_dct` and `mp3` are all native ffmpeg code
in the LGPL core, so nothing here needs a GPL build.

*Dialogue.* SDL_mixer 1.2 decodes MP3 only on its single music channel, and
this game's 1,389 lines of dialogue are MP3 -- as is the score. Left to
collide, a line kills the music, the music manager restarts the score on the
next tick, and the line dies in the frame it began. So dialogue is decoded to
PCM and mixed as an ordinary sound, which is what the original engine did.
Lines are cached under `player/cache/audio` at about 115 KB each: ~57 ms the
first time a line is spoken, nothing after that. *Without ffmpeg:* lines cut
the music and each other.

*Movies.* The 40 `.da2` files are Bink 1 (`BIKi`), 640x480, which ffmpeg
decodes. Frames are streamed in as raw RGB and blitted straight to the screen
-- caching them would cost 1.5 GB for the intro alone -- while the soundtrack
is decoded once to `player/cache/movies` and played as a chunk. Frames are
timed off the wall clock, so a slow moment costs one frame instead of putting
a 172-second movie out of step with its own audio. It costs about 1.6 ms a
frame. *Without ffmpeg:* a movie is a black screen for its real running time.

Either way a click or a key cuts a movie short, and `--skip-video` treats every
movie as zero length, which takes you straight to the bedroom.

**When something goes wrong.** The game catches its own errors and stops, and
it prints the traceback into its log file rather than the console -- so a
crash used to look like the window simply closing. It now says so on the
console, with the traceback, and saves it to `player/crash.log`.

Every run also keeps the previous two, so relaunching no longer destroys the
evidence:

| | |
|---|---|
| `player/trace.log` | every engine call this run, in order; `.1` and `.2` are the runs before |
| `player/crash.log` | the traceback, if this run crashed; `.1` and `.2` likewise |
| `player/rundir/*.log` | the game's own log, where its printed messages go |

To report a problem, the useful things are the last fifty or so lines of
`trace.log` from the run that went wrong, `crash.log` if there is one, and
what you had just clicked.

| | |
|---|---|
| move the mouse | the pointer changes over anything clickable, as it does in the original: an outline arrow normally, a filled one over a clickpoint, a direction arrow at an exit, an hourglass while the game is busy, and nothing at all during a cutscene |
| move to the bottom of the screen | raises the inventory |
| click a door | walks to the next room |
| click an inventory item | uses it -- the card holder opens the album |

Useful while developing:

| flag | |
|---|---|
| `--skip-video` | movies end instantly; the quickest way into the game |
| `--scene NAME` | start in a room instead of the logos, e.g. `--scene bedroom` |
| `--frames N` | stop after N frames instead of running until you quit |
| `--screenshot F` | save the last frame |
| `--click X,Y@FRAME` | inject a click; repeatable, for scripted sequences |
| `--hover X,Y@FRAME` | move the pointer without clicking, to exercise rollover |
| `--key NAME@FRAME` | press a key, e.g. `escape@40`, `space@90`, `k@60` |
| `--subtitles` | show the dialogue text; the game defaults it off |
| `--debug-hit` | log every sprite hit test and which bound rejected it |

Everything the game asks of the engine is written to `trace.log`.

## Recording and replaying: the trace as an oracle

Every run writes `trace.log`, one line per engine call the game makes -- what
it created, set, called and loaded, in order. A recording makes that trace
reproducible:

```bash
C:\Python27\python.exe run_game.py --record session.oyr
C:\Python27\python.exe run_game.py --replay session.oyr --headless
python compare_traces.py trace_of_recording.log trace_of_replay.log
```

A replay makes exactly the same engine calls as the session it recorded --
checked on a 1,500-frame session from boot, through the intro movies, music,
dialogue and clicks: 75,598 trace lines, identical, and identical again on a
second replay. `--headless` runs with no window and no sound.

That is what makes the trace useful to anyone reimplementing the engine. Replay
the same recording in another engine, log the same calls, and
`compare_traces.py` shows the first place the two disagree.

A recording (`yagashim/replay.py`) holds what the game depends on:

- **input**, as the engine events the game's input manager receives --
  `[class, type, elementID, value]` per event, per frame -- so a recording
  does not depend on SDL, pygame or the window size;
- **time**: `time.time` and `time.clock` become one virtual clock, advanced
  per frame by the recorded step, which covers animation, lipsync, movies and
  the scripts' own waits;
- **the random seed**, for the game's `g_Random` and everything else.

Two things the engine decides are made deterministic while recording or
replaying: whether a sound is still playing is judged from the virtual clock
and the sound's length rather than asked of the sound card, and sprites at the
same depth draw in creation order rather than memory-address order (Python 2
compares objects by address, which changes from run to run).

A replay needs the same install and the same saved games. Start recordings
with `--scene` to skip the menus, or from boot.

## How it runs

`yagashim/` stands in for the eleven native modules. Nothing is hand-written per
module: names spring into existence on first use and every access, call and
assignment is logged to `trace.log`, so a name we never anticipated gets
recorded rather than raising. `yagagraphics` is the exception — boot.py refuses
to start without a graphics device that reports a 640x480 mode in a 16-bit
format, so that much is real.

The game currently reaches:

```
Loading scenes from data/scenes.xml...
Loading scene leavins...
Loading scene trading_cards...
Loaded 36 scenes
```

and stops when it asks the engine to load its first sprite -- the mouse cursor.

## The worklist, in the game's own startup order

1. **`yagagraphics`** — `GraphicsSystem()` singleton, `PixelFormat`,
   `VideoMode`, a device with `.modes`/`.currentMode`, `CreateRenderTarget`,
   `CreateCamera`. *Minimally implemented.*
2. **`yaga.System()`** — `systemMemoryTotal`, `systemMemoryAvail`.
3. **`yagares.ResourceManager`** — `RegisterFormatHandler`, called eight times.
   The engine is a resource manager with one pluggable handler per asset type:
   `PngHandler`, `MngHandler`, `RleHandler`, `TargaHandler` (yagagraphics),
   `BinkHandler` (yagasprite), `EvtHandler`, `EvbHandler` (yagaevents).
   The Mng and Rle handlers are the decoders already written in `../tools`.
4. **`yagaevents`** — `EventManager`, `KeyCodes`, and `IEventReciever` as a
   subclassable base.
5. **`yagascene`** — `SceneManager`, `CreateScene`, `Point`, `ISceneEventSink`.
6. **`yagaxml`** — `Parser`, `IContentHandler`. *Implemented* on expat, which
   is what the original used too. All 36 scenes now load.
7. **`yagares.ResourceManager.Load`** — **next up.** Returns a resource the
   sprite manager wraps in `yagagraphics.IImageAnim`. This is where the MNG
   and RLE decoders in `../tools` plug in.
8. `yagasound.SoundSystem`, `yagafont`, `yagasprite` proper — not yet reached.

## Resource paths

The engine addresses content through paths whose first component is an
**archive name**, not a folder: `data/scenes.xml` means `scenes.xml` inside
`data.he`. Failing that it falls back to a real file on disk, which is how the
loose `interface/` and `movies/` folders are reached. Lookups are
case-insensitive in both directions -- the scripts lowercase paths before
asking, the archives store mixed case. `resources.py` implements this.

One engine behaviour worth knowing: `LoadAnim` asks for `<name>.rle` **before**
`<name>.mng` and only falls back if the RLE is missing. In Pajama Sam 4 the two
sets are completely disjoint -- 2,290 MNG and 435 RLE with no shared base name
-- so the substitution never actually fires, but the engine supports it.

## Python 2.2 vs 2.7

Differences found by running the code, each fixed in the loader:

- **String exceptions.** `raise "message"` was legal in 2.2 and removed in 2.6.
  15 of them survive, in three forms: bare, `raise "msg", value`, and
  `raise "msg" % value`. Under 2.7 they raise TypeError instead of what the
  author meant.
- **No encoding declaration.** 2.2 predates PEP 263, so `boot.py` — which has a
  (c) in its banner — is a SyntaxError under 2.7. Note `py_compile` accepts it
  and `execfile` does not, so a parse check will not catch this.
- **Decompiler artifact.** Every recovered module ends with a bare `return` at
  column 0, which is a syntax error outside a function.

## Next steps

Pajama Sam 4 plays through to the end (tagged `v0.1`, SDL 1.2). This branch
moves to SDL2 for window scaling; once it has been played through, the other
Yaga games.
