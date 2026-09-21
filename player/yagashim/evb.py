# -*- coding: latin-1 -*-
"""The .evb event streams -- which is where the lipsync lives.

These were the last unread format in the game, and linyaga does not read them
either.  There are 2,884 of them: 1,284 beside the talkie audio, 1,525 in the
rooms, 75 in the interface.

The game asks for `.evt` and there is not one on the disc:

    evtFilename = self.ConvertPathUsingCodeLikeLoadSound(soundPath)   # .evt
    eventResource = globals.g_ResourceManager.Load(evtFilename)

and registers a handler for each -- `EvtHandler()` and `EvbHandler()` -- so
the pair is plainly a text source and its compiled form, with only the binary
one shipped.  Asking for .evt therefore has to fall back to .evb.

Layout, little-endian throughout:

    uint32  file size, which always equals the real length
    uint32  event count
    then `count` records of 28 bytes:
        float32  time, seconds from the start of the line
        uint32   event type, always 31415
        uint32   phoneme mask
        float32  always 1.0
        uint32   stale -- see below
        uint32   0
        uint32   0

All 1,284 talkie files fit that exactly (8 + count * 28 == file size, and no
file disagrees), times never go backwards, and the last event always lands
just inside the audio: 1.80s against 1.95s, 2.47s against 2.63s, 2.33s
against 2.47s.

The fifth field is not data.  It holds 199 distinct values across 10,810
records, some of them heap-looking addresses (0x01a10730) and some plainly
ASCII (0x30303061, "a000") -- an uninitialised pointer in a struct that was
written to disc whole.  The engine cannot be reading it either.

The mask is the interesting field, and it is the same bitmask the .mng layers
carry in their flAG chunks.  Across 213 talkie animations the naming is
consistent:

    0x001 ROOT   0x002 A    0x004 EE   0x008 OH    0x010 U
    0x020 D (C)  0x080 M    0x100 TH   0x200 F     0x400 UH

so an event says "show this mouth shape now", and a sprite draws the layers
whose mask it matches.  Mask 0 means show none of them, which is the closed
mouth between words.

Two loose ends, both harmless and both real:

* Bit 0x040 is never used, by any animation or any event.
* Mask 0x800 appears in 30 events and matches no layer in any animation in
  the game -- a mouth shape that was cut from the art but left in the tracks.
  Those events simply draw no mouth, which is what the original must have
  done too.

The 1,600 room and interface files do NOT fit the 28-byte shape: their
records are ragged, around 80 bytes, which is what a record carrying a name
looks like.  Those are the animation event streams that fire sounds -- what
`CAnimReciever` and `StopEventSounds` walk -- and they are not read here.
"""

import struct

import _stub

EVENT_LIPSYNC = 31415
RECORD = 28

# Layer names for each bit, read off the animations rather than guessed.
PHONEMES = {
    0x001: "ROOT", 0x002: "A", 0x004: "EE", 0x008: "OH", 0x010: "U",
    0x020: "D", 0x080: "M", 0x100: "TH", 0x200: "F", 0x400: "UH",
}


def describe(mask):
    """'M', or 'A|OH', or 'closed' -- for logs and for reading traces."""
    if not mask:
        return "closed"
    names = [n for bit, n in sorted(PHONEMES.items()) if mask & bit]
    return "|".join(names) if names else "0x%x" % mask


def parse(data):
    """[(time, mask), ...] for a lipsync stream, or None for anything else.

    None means "this is not the fixed-size form" rather than "this is broken":
    the room streams are a different, ragged shape that carries names, and
    they are nothing to do with mouths.
    """
    if not data or len(data) < 8:
        return None
    try:
        size, count = struct.unpack_from("<II", data, 0)
    except struct.error:
        return None
    if size != len(data) or count <= 0:
        return None
    if 8 + count * RECORD != len(data):
        return None

    events = []
    for i in range(count):
        try:
            when, kind, mask = struct.unpack_from("<fII", data, 8 + i * RECORD)
        except struct.error:
            return None
        if kind != EVENT_LIPSYNC:
            # Nothing in the shipped data does this; if something did, the
            # record would mean something other than a mouth shape and
            # guessing would be worse than skipping it.
            _stub.LOG.record("call", "yagaevents.evb",
                             "unknown event type %d, skipped" % kind)
            continue
        events.append((when, mask))
    return events
