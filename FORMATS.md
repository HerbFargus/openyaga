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

## Event streams (`.evb`, 2,884 files)

The masks above say *what* the mouth shapes are; `.evb` says *when* — and also
what sounds an animation fires. 1,284 of these sit beside the talkie audio,
1,525 in the rooms, 75 in the interface. linyaga lists lipsync as its one
missing feature.

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
| 8 | — | `count` events |

and each event:

| offset | type | meaning |
|---|---|---|
| 0 | f32 | time, seconds from the start |
| 4 | u32 | event type |
| 8 | u32 | parameter |
| 12 | f32 | always `1.0` |
| 16 | u32 | stale memory, see below |
| 20 | u32 | `0` |
| 24 | u32 | group count |

followed by that many groups, each:

| type | meaning |
|---|---|
| u32 | name length |
| u32 | field count |
| char[] | name, NUL terminated |

and then that many fields, each:

| type | meaning |
|---|---|
| u32 | key length |
| u32 | value length |
| char[] | key, NUL terminated |
| char[] | value, NUL terminated |

**Every one of the 2,884 files parses to exactly its own length under this** —
no slack, no shortfall. It is one format, not two: the talkie streams are
simply the case where the group count is zero.

### Type 31415 — lipsync (36,402 events)

The parameter is a phoneme mask, the same bits the layers carry. Times never
go backwards, and the last event always lands just inside its audio (1.80s
against 1.95s; 2.47s against 2.63s; 2.33s against 2.47s).

An event sets the mouth and it holds until the next one — these are state
changes, not pulses. Mask `0` means show no mouth layer at all, which is the
closed mouth between words.

### Type 15500 — animation events (2,384 events)

`globals.TYPE_ANIMATION_EVENT`. These are the ones carrying groups. Every room
stream opens with one at t=0 naming its own animation, and the rest cue sound
effects, e.g. `agi_broke1_op_demo.evb`:

```
0.0  AnimName  'Agi_broke1_op_demo'
0.3  SoundName 'agi_crane'      Channel '1'
0.8  SoundName 'agi_metalthud'  Channel '2'
```

`SoundName` and `Channel` always come in pairs — 784 of each — and `Channel` is
only ever `'1'` or `'2'`. The field key is always `'value'`.
`character.CAnimReciever.Raise` consumes these, playing `sfx/<SoundName>.wav`;
it keeps its own running index and asks the stream for each event in turn, so
a reader has to raise exactly one event per stream event, in order.

These carry the incidental sound of the game: footsteps, bounces, a yawn, a
cape being tossed. Cue counts by room run to 76 in `shoetree`, 74 in
`happy_farm`, 50 in `dressing_room`.

**The field at +16 is not data.** It holds 199 distinct values across the
talkie records alone, some resembling heap addresses (`0x01a10730`), some
plainly ASCII (`0x30303061`, `"a000"`); in the room files it turns up holding
`"anim"`. It is an uninitialised pointer in a struct written out whole, and
the engine cannot be reading it either.

Two loose ends, both real:

- Bit `0x040` is used by nothing — no animation layer, no event.
- Mask `0x800` appears in 30 events and matches no layer in any animation in
  the game: a mouth shape cut from the art but left in the tracks. Those
  events draw no mouth.

## Not yet reversed

- The **`.xml` schema**. The files are plain text and readable as-is, but the
  scene/inventory structure and the 212 KB master script are not documented
  here.
- The Python 2.2 game scripts are inside the executable, not on the disc; see
  `player/README.md` for how they are recovered.
