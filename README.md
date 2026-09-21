# openyaga

Tools for the **Yaga engine** — the in-house engine Humongous Entertainment and
Atari used for their last adventure games, after two decades of SCUMM.

Yaga games are **not** SCUMM games and ScummVM does not currently run them. Five
titles shipped on it:

- Pajama Sam 4: Life Is Rough When You Lose Your Stuff (2003)
- Putt-Putt: Pep's Birthday Surprise (2003)
- Backyard Basketball 2004, Backyard Football 2004, Backyard Hockey

Development so far has been against Pajama Sam 4.

![Pajama Sam 4 running under openyaga](docs/screenshot.png)

*Sam's bedroom, rendered by openyaga from the game's own scripts and data, with
the inventory raised.*

## What works today

**`tools/` — asset extraction. Complete and in use.**

Decodes every sprite in the game to PNG: 2,725 animations, 34,091 images, zero
decode failures. Also extracts audio, XML and video, and produces sprite sheets
and animations. See [tools/README.md](tools/README.md).

```bash
python tools/yaga_extract.py sprites --pattern "bedroom/*" --formats frames,sheet
```

**`FORMATS.md` — the format documentation.**

Containers, both sprite codecs, the lipsync/phoneme system, the `.evb` event
streams, and the quirks in the shipped data that break naive decoders.
[XML.md](XML.md) covers the data files: room layouts, menus, the inventory,
and the dialogue script — which carries the full subtitle text for all 1,212
spoken lines.

**`player/` — a standalone player. Pajama Sam 4 plays start to finish.**

Yaga is a C++ engine driving **Python 2.2** game scripts, which are bundled
inside the game executable. So the game's *logic* needs no reimplementation —
only the engine beneath it. The player reads the scripts out of the copy you
own, then provides the eleven `yaga*` modules they import, backed by SDL.

Pajama Sam 4 has been played through to the end on it: rooms, characters,
music, dialogue and sound effects, the inventory, the minigames, the Bink
movies with sound, and saving and loading — saves are interchangeable with
the original game's, both ways.

Characters lip-sync to their dialogue and animations fire their own sound
effects: the `.evb` event streams are read in [FORMATS.md](FORMATS.md), which
linyaga lists as its one missing feature. Subtitles work too (`--subtitles`;
the game defaults them off), drawn with the game's own bitmap fonts.

Setup also repairs the decompiler's mistakes in the recovered scripts, checked
against the original bytecode, and fixes a few bugs in the original game that
could freeze or crash it (see `player/yagaboot/patches.py`).

See [player/README.md](player/README.md) for the design.

## What doesn't work yet

- **The other four Yaga games are untested.** Everything was built against
  Pajama Sam 4; Putt-Putt and the Backyard titles may need more of the engine.
- **SDL 1.2 limits.** The window is a fixed 640x480 with no scaling. An SDL2
  port is next.

## You need your own copy of the game

This repository contains **no game code and no game assets**, and never will.
Everything it produces is derived from the copy on your own machine and stays
there. `.gitignore` denies by default for exactly this reason.

## Prerequisites

| | |
|---|---|
| `tools/` | Python 3, Pillow |
| `player/` setup | Python 3, `uncompyle6` (one-time, per install) |
| `player/` runtime | Python 2.7 + `pygame==1.9.6` — the game's code is Python 2, and converting it would silently change integer division |
| `player/` dialogue and movies | ffmpeg, to decode the MP3 voice tracks and the Bink movies — SDL can open neither. `python player/get_ffmpeg.py` fetches a pinned LGPL build on Windows; elsewhere your package manager has it |

## Prior work

- **[cyxx/linyaga](https://github.com/cyxx/linyaga)** — a C wrapper for the Yaga
  games, and the reference that made the sprite formats legible. Note it targets
  a different build than the retail Windows release: that build's scripts import
  eleven object-oriented `yaga*` modules, while linyaga provides a single flat
  `yagahost`.
- **ScummVM's `yaga` branch** ([bluegr/scummvm](https://github.com/bluegr/scummvm/tree/yaga))
  — an engine skeleton with MNG/RLE decoding and game detection, parked at the
  point where the Python interpreter problem starts.

The two projects have different goals from this one. A ScummVM engine must
embed a Python interpreter in C++ to run the original bytecode; this runs the
scripts under CPython instead, which is far less work and correspondingly less
portable. Nothing here is upstreamable to ScummVM — only the knowledge is.

## Licence

MIT, for the code and documentation here. See [LICENSE](LICENSE).

That covers the code and documentation in this repository only. It does not
cover Pajama Sam 4: Life Is Rough When You Lose Your Stuff, any other Yaga
engine game, or any of their data -- those remain the property of their rights
holders. This repository contains no game code and no game assets, and you
supply your own copy of the game.
