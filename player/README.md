# Yaga player

A standalone player for the Humongous/Atari Yaga games, built around the game's
*own* Python scripts rather than a reimplementation of its logic.

**Status: step 2 — the game's own boot script runs against tracing stubs.
Nothing renders yet.**

## How it works

Yaga games are a C++ engine (`yaga*.dll`) driving Python 2.2 game scripts. The
scripts are bundled inside the game executable by McMillan Installer, the tool
that became PyInstaller.

That means the game's *logic* doesn't need reimplementing — only the engine
underneath it. So this project:

1. reads the scripts out of the executable **the user already owns**,
2. recovers them as source on the user's machine,
3. and (not yet built) provides the eleven `yaga*` modules the scripts import,
   backed by SDL and the sprite decoders in [`../tools`](../tools).

The API surface to implement is 56 module-level names, 6 subclassable engine
classes, and roughly 100–120 methods. See [../FORMATS.md](../FORMATS.md) for the
data formats.

## What ships and what doesn't

This project contains **no game code**, and must stay that way. The user supplies
their own installed copy; everything derived from it is written to `gamecache/`
on their machine and never travels. `gamecache/` is gitignored — keep it that
way, it holds a reconstruction of the game's copyrighted source.

## Setup (one time, Python 3)

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
C:\Python27\python.exe run_game.py
```

Opens a 640x480 window and boots the game the way it boots itself: Atari logo,
Humongous logo, then the first room. Escape or closing the window quits.

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
| `--debug-hit` | log every sprite hit test and which bound rejected it |

Everything the game asks of the engine is written to `trace.log`.

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

3. Implement `yagaxml` on top of Python's own XML parser, feeding
   `IContentHandler` subclasses, so the scene table loads.
4. Then enough of `yagascene` + `yagasprite` + `yagagraphics` to composite one
   room, reusing the decoders in `../tools`.
