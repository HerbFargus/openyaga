# Pajama Sam 4 file formats (Yaga engine)

*Life Is Rough When You Lose Your Stuff*, Humongous Entertainment / Atari, 2003.

This game is **not** a SCUMM game. Humongous' last two titles — this one and
*Putt-Putt: Pep's Birthday Surprise* — run on an in-house engine called **Yaga**,
which is a set of C++ DLLs (`yaga.dll`, `yagagraphics.dll`, `yagasprite.dll`,
`yagaevents.dll`, …) driven by **Python 2.2** scripts (`python22.dll`, `_sre.pyd`)
with XML data files (`expat.dll`). ScummVM does not support it; the reference
open-source implementation is [cyxx/linyaga](https://github.com/cyxx/linyaga),
which is the oracle everything below was checked against.

## Container: `.he`

Nine `.he` files hold 8,360 members. Each one is an **ordinary ZIP archive with
every member stored uncompressed** (compression method 0), so `unzip`, 7-Zip or
Python's `zipfile` open them directly. The engine's own reader
(`zipfile.c` in linyaga) walks the local file headers rather than the central
directory, and resolves a path like `rooms/bedroom/bg_bedroom.mng` by treating
the first component as the archive name.

| archive | entries | contents |
|---|---:|---|
| `MaxFiles/rooms.he` | 3,928 | 238 MB of room art: `.mng`, `.rle`, `.evb`, `.xml` |
| `MaxFiles/talkies.he` | 2,673 | dialogue `.mp3` + `.evb` lipsync |
| `MaxFiles/sfx.he` | 700 | `.wav`, `.mp3` |
| `MaxFiles/clickpoints.he` | 472 | `.wav` |
| `MaxFiles/menus.he` | 177 | menu `.mng` + `.xml` (includes bitmap fonts) |
| `MaxFiles/animation.he` | 8 | `.wav` |
| `Pajama Sam LRS/interface.he` | 347 | cursors, inventory, options `.mng` |
| `Pajama Sam LRS/music.he` | 45 | `.mp3`, `.wav` |
| `Pajama Sam LRS/data.he` | 10 | `.xml`, including `script/pajamasam4_script.xml` (212 KB) |

Loose on disk alongside them: `interface/` (`.cur` cursors, `.mng`, `.evb`),
`movies/` (`.da2`, which are **Bink** videos — magic `BIKi`, playable with
ffmpeg), and `PajamaSamLRS.pdf`.

## Sprites, part 1: `.mng` (2,290 files, 204 MB)

Real MNG streams — signature `8A 4D 4E 47 0D 0A 1A 0A` — but a private subset.
An animation is a list of **frames**; a frame is a list of **layers**; a layer is
an RGBA bitmap placed at an (x, y) offset on a 640×480 screen.

| chunk | size | meaning |
|---|---|---|
| `MHDR` | 28 | header, ignored by the engine |
| `PLTE` | 768 | 256 RGB palette entries |
| `tRNS` | 256 | 256 alpha entries for that palette |
| `FRAM` | 10 | starts the first frame |
| `FRAM` | 0 | starts a subsequent frame (skipped if no layer was defined yet) |
| `DEFI` | 12 | starts a layer; bytes 4..11 are signed big-endian x, y |
| `tEXt` | var | `LAYER\0<name>` — the layer's name |
| `flAG` | 4 | **little-endian** phoneme mask for the layer (non-standard chunk) |
| `IHDR`/`IDAT`/`IEND` | | the layer's bitmap as a normal PNG image stream |
| `MEND` | 0 | end |

Palette rules: `PLTE`/`tRNS` seen **before** the first `FRAM` set the global
palette; each `FRAM` copies it into the frame, and `PLTE`/`tRNS` seen after that
override the copy for that frame only. The default palette is opaque black.

Bitmaps are always 8-bit, non-interlaced, colour type 2 (RGB), 3 (palette) or
6 (RGBA). Row filters are technically present but every shipped image uses
filter 0.

**Quirks in the shipped data** (all 2,725 animations decode once these are
handled):

- linyaga decides "this IDAT is stored raw, not zlib" from size alone
  (`zsize >= buf_size`). That misfires on small images, where a zlib stream is
  *longer* than the pixels it encodes — a 3×3 paletted image is 12 bytes raw and
  needs ~12 compressed. Inflating first and falling back to raw is correct.
- Some tiny images ship with a **truncated zlib stream**: the 3×3 twinkles in
  `elastic_land/ambients/twinkle*.mng` inflate to 9 of 12 bytes, and a handful of
  1×1 layers (`cru_cant_climb.mng`, `sho_cu_horn.mng`,
  `sho_sponge_clean_horn.mng`) are nothing but a 2-byte zlib header. linyaga
  renders these as garbage; padding the missing rows with transparent pixels is
  the sane reading.
- Five `.mng` members are **zero bytes** in the retail data:
  `dressing_room/animation/sam/dre_comic_sprinkler_cu.mng`,
  `dressing_room/animation/sam/dre_comic_talkie.mng`,
  `scaling_game/bg_sca_dresser_top.mng`, `cursors/hw_raisin.mng`,
  `options/options/opt_subtitles_on.mng`.

## Sprites, part 2: `.rle` (435 files, 44 MB)

Yaga's own format, signature `F2 65 6C 72 00 00 20 4D`. Same frame/layer model
as the MNG files. All little-endian:

```
8    signature
u32  frame count
u32  flags        bit 0: a 256-entry BGRA palette (1024 bytes) follows
per frame:
  16   header, layer count at offset +12
  per layer:
    f32  x, f32 y          (IEEE floats, truncated to int by the engine)
    u32  unknown
    u32  phoneme mask
    57   layer name, NUL padded
    4    "rle\0"
    u32  pixel format      0x040012F9 / 0x040012FB paletted, 0x0C0012F9 BGRA
    3    padding
    u32  width, u32 height
    u32  flags             bit 0: a per-layer BGRA palette (1024 bytes) follows
    u32  unknown
    u32  always 1
    u32  compressed size
    [1024 bytes palette]
    <compressed size> bytes of RLE data
```

The RLE itself, one byte per opcode, `count = (code & 0x3F) + 1`:

| code | meaning |
|---|---|
| `(code & 0xC0) == 0xC0` | skip `count` **transparent** pixels |
| `code & 0x80` | repeat the next colour `count` times |
| otherwise | `count` literal colours follow |

A colour is one palette index, or one 32-bit BGRA value in the BGRA format.

## Lipsync: the phoneme mask

Both formats give every layer a 32-bit mask. The engine draws a layer when
`mask == 0`, or when `(mask & current_phoneme) != 0`
(`is_phoneme()`/`Animation_Draw()` in linyaga). A talking character is built as
an unmasked body plus masked mouth shapes named after their phoneme, plus masked
head shapes that each cover a group of them. From
`aquarium/animation/diver/aqu_diver_talkie.mng`:

| bit | layer |
|---|---|
| `0x001` | `ROOT` (closed mouth / rest) |
| `0x002` | `A` |
| `0x004` | `EE` |
| `0x008` | `OH` |
| `0x010` | `U` |
| `0x020` | `C` |
| `0x080` | `M` |
| `0x100` | `TH` |
| `0x200` | `F` |
| `0x400` | `UH` |

and the head shapes `ROOT_HEAD = 0x531` (ROOT+U+C+TH+UH), `STRETCH = 0xA`
(A+OH), `SQUASH = 0x284` (EE+M+F).

This matters for extraction: dropping every masked layer leaves the character
**without a head**, not merely without a mouth. Rendering with phoneme `0x1`
gives the neutral pose.

## Lipsync: the timeline (`.evb`, 2,884 files)

The masks above say *what* the mouth shapes are; `.evb` says *when*. 1,284 of
these sit beside the talkie audio, 1,525 in the rooms, 75 in the interface.
linyaga lists lipsync as its one missing feature.

The game asks for `.evt`, and there is no such file on the disc:

```python
evtFilename = self.ConvertPathUsingCodeLikeLoadSound(soundPath)   # -> .evt
eventResource = globals.g_ResourceManager.Load(evtFilename)
```

`globals.py` registers `EvtHandler()` and `EvbHandler()` side by side, so the
pair is a text source and its compiled form, with only the binary one shipped.
A reader has to fall back from `.evt` to `.evb`.

Little-endian throughout:

| offset | type | meaning |
|---|---|---|
| 0 | u32 | file size — always equals the real length |
| 4 | u32 | event count |
| 8 | — | `count` records of 28 bytes |

and each record:

| offset | type | meaning |
|---|---|---|
| 0 | f32 | time, seconds from the start of the line |
| 4 | u32 | event type, always `31415` |
| 8 | u32 | phoneme mask — the same bits as the layer masks above |
| 12 | f32 | always `1.0` |
| 16 | u32 | stale memory, see below |
| 20 | u32 | `0` |
| 24 | u32 | `0` |

All 1,284 talkie files fit `8 + count * 28 == file size` exactly, times never
go backwards, and the last event always lands just inside its audio (1.80s
against 1.95s; 2.47s against 2.63s; 2.33s against 2.47s).

An event sets the mouth and it holds until the next one — these are state
changes, not pulses. Mask `0` means show no mouth layer at all, which is the
closed mouth between words.

**The field at +16 is not data.** It holds 199 distinct values across 10,810
records, some resembling heap addresses (`0x01a10730`), some plainly ASCII
(`0x30303061`, `"a000"`). It is an uninitialised pointer in a struct written
out whole, and the engine cannot be reading it either.

Two loose ends, both real:

- Bit `0x040` is used by nothing — no animation layer, no event.
- Mask `0x800` appears in 30 events and matches no layer in any animation in
  the game: a mouth shape cut from the art but left in the tracks. Those
  events draw no mouth.

The **room and interface** `.evb` files (1,600 of them) are a *different*
shape: their records are ragged, around 80 bytes, which is what a record
carrying a name looks like. Those are the animation event streams that fire
sounds — what `CAnimReciever` and `StopEventSounds` walk — and they are not
reversed here.

## Not yet reversed

- The **room/interface `.evb` variant** described above — variable-length
  records that appear to carry sound names, used for animation events rather
  than lipsync.
- **`.xml`** files are plain text and readable as-is, but the schema (scenes,
  inventory, the 212 KB master script) is not documented here.
- The Python 2.2 game scripts, if any are shipped compiled, have not been located.
