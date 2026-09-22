## Rules an engine has to follow

Behaviour the names alone do not tell you. Each was found by the game going
wrong without it; the shim file that implements it has the details.

### The interpreter

- **`True` and `False` are 1 and 0.** The game's `boot.py` sets
  `__builtin__.False = 0` and `True = 1` for its Python 2.2 code, and that
  holds for any engine code running in the same interpreter. Never test
  `x is False`: it never matches (`yagasprite.py`, `display.py`).
- **Integer division.** The scripts are Python 2 and rely on it
  (`c_FrameRateMod = 3 / 2` is 1). Running them under Python 3 changes
  behaviour silently.
- **Python 2 orders unlike objects by address.** The sprite manager sorts
  `(z, sprite)` pairs, so equal-depth sprites are ordered by comparing the
  sprites. The shim compares engine objects by creation order, which is
  stable and usually matches the original's allocation order
  (`yagasprite.ISprite.__cmp__`).

### The loop

- One timer drives everything: `main.py` registers a receiver for
  `TIMER_TICK`, and each tick dispatches input, then ticks sound, sprites,
  rooms, scenes and preloading, in that order.
- **Input is queued, not handled, on arrival.** The game's input manager's
  `Raise` only appends to a queue; `DispatchInput` hands it out at the start of
  the next tick.
- An exception anywhere in a tick makes `main.py` call `StopEventLoop()`:
  a crash and a normal quit look the same unless the engine checks
  (`yagaevents.EventManager.StopEventLoop`).

### Sprites and animation

- **Sprites do not animate until `Run()`**, and `Run()` must be idempotent:
  the game can call it again on a sprite that is already playing, and
  restarting the clock there pins the animation on frame 0. (The call made
  every frame is the sprite manager's `Seek(delta)`, on every sprite.)
- **`SCENE_STOP` is load-bearing.** When an animation with a loop count
  finishes, the sprite's event sinks get `SCENE_STOP`; room changes, walking
  and cutscenes advance on it. A one-frame pose still finishes.
  Characters guard against their own `Stop()` with `ignoreCallback`, which
  only works if the stop is delivered synchronously.
- **`SCENE_RUN` repeats.** It is sent when an animation starts *and every
  time a looping animation starts over*. Scripts poll on it: a character
  looping a talking animation checks `doneTalking` on each `SCENE_RUN` and
  moves on when the line has ended, and Pajama Sam 4's inventory preview
  closes after six of them. Sent only once, Putt-Putt's first conversation
  waits for ever (`yagasprite.ISprite._advance`).
- **`position.z` is the draw order**, and a sprite's position is a value:
  assigning a Point copies it, and so does *reading* one. Scripts read a
  position, adjust the copy and hand it on; a live reference moves the
  original sprite instead -- in Putt-Putt, a save slot onto the slot below,
  which then took its clicks (`yagascene.copy_point`, `ISprite.__getattr__`).
- **`currentFrame` stays within the animation.** Scripts that animate by
  hand step past the end and test for the last frame exactly; unclamped,
  Putt-Putt's bunnies never finished a hop (`ISprite._clamp_frame`).
- **Hit tests are against the picture, drawn or not.** `Intersect` must work
  on a sprite the game never shows: Putt-Putt's bunny maze is a hidden mask
  (`ISprite._layers_at_rest`).
- **`renderRect` is known before the first draw**: the save screen centres
  labels on it the moment a sprite is made (`yagasprite._estimate_rect`).

### Layers

A frame is a stack of named layers, each with a 32-bit phoneme mask.

- A layer draws when `mask & renderMask`, or when `mask == 0` -- **except**:
  - **named alternatives**: `SetLayerFlag(name, LF_LAYER_ON, on)` switches a
    layer by name (eye directions, the bishop's crook). The switch belongs to
    the sprite and survives animation changes; layers default to on;
  - **blinks**: `BLINK1` and `BLINK2` are mask 0 and no script touches them.
    The engine blinks characters itself, unless the sprite's `blinkEnabled`
    is false -- Putt-Putt turns it off while a character talks. The rate is
    not in the data;
  - **lipsync silence**: a mask of 0 in a lipsync stream means "no phoneme"
    and draws the rest pose (`ROOT`), not nothing.
- See `FORMATS.md`, "Lipsync: the phoneme mask".

### Event streams (`.evb`)

- An animation can carry an event stream: sounds to start (type 15500) and
  lipsync (type 31415). Receivers get one `Raise` per stream event, in order,
  with `deviceID` equal to the playback's `identity`; `CAnimReciever` counts
  them itself, so a skipped or repeated event reads the wrong data from then
  on (`yagaevents.EventManager._pump_streams`).
- A finished stream stops driving the mouth.
- The game asks for `.evt`; the shipped files are `.evb` (`resources.py`).

### Input

- **Mouse**: `IEVENT_AXIS_POS_X` and `IEVENT_AXIS_POS_Y` as two events
  carrying the coordinate in `value`; buttons as `IEVENT_BUTTON_DOWN`/`UP`
  with the button index in `elementID`. Coordinates are the game's 640x480.
- **Keyboard**, raw and translated: raw `BUTTON_DOWN`/`UP` carry a virtual-key
  code (letters upper case), and a translated `BUTTON_PRESS` on the way down
  carries the character typed. `KeyCodes` for non-characters start at `0x100`,
  numbered as linyaga numbers them (`yagaevents.KeyCodes`).
- Escape and Enter belong to the game: Escape opens the options menu, Enter
  skips a cutscene.

### Text

- A text sprite's position is an **anchor**: left text starts at it, centred
  text is centred on it, right text ends at it (`yagafont.py`).
- XML strings are byte strings, not unicode: they end up pickled into saves
  (`yagaxml.py`, `returns_unicode = 0`).

### Sound

- Music, dialogue and effects mix; music plays under everything at its own
  volume (0.3 by default).
- **`isPlaying` means this sound, not its channel.** A finished sound's
  channel is reused at once, and reporting the channel's state kept finished
  dialogue "playing" for ever (`yagasound.ISound.isPlaying`).
- Talkie durations time the subtitles.

### Cursor, movies, saves

- The game normally takes the hardware-cursor path: `LoadCursorFile(path,
  id)` with a `.cur`, then `SetCursorByID(id)`; `cursorVisible` hides the
  pointer for cutscenes (`yagagraphics.RenderTarget`).
- **Software cursors draw centre-relative.** Some screens (Putt-Putt's cake
  decorator) turn the hardware cursor off and draw the cursor sprite,
  placed at the mouse in screen pixels. Every cursor picture is authored
  with its hotspot at the canvas centre (320, 240), so cursor art is drawn
  offset by (-320, -240) (`ISprite._origin`).
- Movies (`.da2`, Bink) run for exactly as long as their header says;
  `isPlaying` is timed by that, whether or not frames keep up
  (`yagasprite.IVideoElement`).
- To photograph a room for a save the game points the camera at an image
  buffer and renders again; sprites must draw wherever the camera points
  (`yagagraphics.target_surface`).
- Saves are pickles (`.dat`) plus a thumbnail (`.img`: `[w, h, [BGRA]]`),
  interchangeable with the original game's.

### Checking an implementation

Record a session with `run_game.py --record`, replay it here and in the other
engine, and compare the traces with `compare_traces.py`: a replay makes the
same engine calls as its recording, so the first difference is the first
place the two engines disagree. See `player/README.md`.
