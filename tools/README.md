# yaga_extract

Extractor for the Yaga engine data files used by *Pajama Sam 4: Life Is Rough
When You Lose Your Stuff* (and, untested, *Putt-Putt: Pep's Birthday Surprise*).

Format notes live in [../FORMATS.md](../FORMATS.md). Needs Python 3 and Pillow;
everything else is stdlib.

```
yaga/anim.py    frame/layer model + the phoneme (lipsync) visibility rule
yaga/he.py      finds .he archives and walks their members
yaga/mng.py     decoder for the MNG-based sprites
yaga/rle.py     decoder for the Yaga .rle sprites
yaga/render.py  compositing, sprite sheets, APNG/GIF output
yaga_extract.py CLI
```

By default it looks for the data under
`../stock-game-files/program files/Atari`; point `--data` at any folder holding
`.he` files (an installed copy of the game works too).

## Commands

```bash
# what is in the archives
python yaga_extract.py archives

# list members, optionally filtered
python yaga_extract.py ls --ext .rle
python yaga_extract.py ls --pattern "bedroom/*" --limit 20

# frame/layer structure of an animation, layer names and phoneme masks
python yaga_extract.py info "*aqu_diver_talkie*"

# decode sprites to PNG
python yaga_extract.py sprites --pattern "bedroom/*" --formats frames,sheet

# pull non-image members out untouched
python yaga_extract.py raw --ext .xml .mp3
```

## `sprites` options

| option | meaning |
|---|---|
| `--formats` | comma-separated: `frames` (one PNG per frame, or a single PNG for a one-frame animation), `layers` (every layer separately, unflattened), `sheet` (grid), `apng`, `gif`, `none` (decode only) |
| `--phoneme` | which lipsync pose to draw: `rest` (default, closed mouth), `all`, `none`, a phoneme name (`A`, `EE`, `OH`, `U`, `C`, `M`, `TH`, `F`, `UH`), or a raw mask like `0x531` |
| `--pattern` | glob against the member path |
| `--out` | output root, default `../extracted` |
| `--fps`, `--columns`, `--jobs`, `--limit` | animation speed, sheet width, worker processes, cap on animations |

Every frame of one animation is composited onto a **shared canvas** sized to the
animation's bounding box, so frames stay registered with each other and can be
dropped straight into a sheet or an APNG. The box, in original 640×480 screen
coordinates, is recorded per animation in `index.json` alongside layer names,
frame count and any decode warnings.

`--phoneme none` is almost never what you want: masked layers include the
character's head, not just the mouth. See FORMATS.md.

## Full-run result on the retail data

2,725 animations → 34,091 PNGs (582 MB). Every animation decodes; the only five
failures are `.mng` members that ship zero-byte in the retail game. A
decode-only pass (`--formats none`) over all of them takes about 9 seconds.
