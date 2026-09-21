# -*- coding: latin-1 -*-
"""The .evb event streams -- lipsync, and the sounds an animation fires.

These were the last unread format in the game, and linyaga does not read them
either.  There are 2,884: 1,284 beside the talkie audio, 1,525 in the rooms,
75 in the interface.

The game asks for `.evt` and there is not one on the disc:

    evtFilename = self.ConvertPathUsingCodeLikeLoadSound(soundPath)   # .evt
    eventResource = globals.g_ResourceManager.Load(evtFilename)

and registers a handler for each -- `EvtHandler()` and `EvbHandler()` -- so
the pair is plainly a text source and its compiled form, with only the binary
one shipped.  Asking for .evt therefore has to fall back to .evb.

It is one format, not two.  Little-endian throughout:

    uint32  file size, which always equals the real length
    uint32  event count
    then `count` events:
        float32  time, seconds from the start
        uint32   event type
        uint32   parameter
        float32  always 1.0
        uint32   stale -- see below
        uint32   0
        uint32   group count
        then `group count` groups:
            uint32  name length
            uint32  field count
            char    name, NUL terminated
            then `field count` fields:
                uint32  key length
                uint32  value length
                char    key, NUL terminated
                char    value, NUL terminated

Every one of the 2,884 files parses to exactly its own length under that --
no slack, no shortfall.  The talkie streams are simply the case where the
group count is zero.

The fifth field is not data.  It holds 199 distinct values across the talkie
records alone, some heap-looking (0x01a10730) and some plainly ASCII
(0x30303061, "a000"); in the room files it turns up holding "anim".  It is an
uninitialised pointer in a struct written out whole, and the engine cannot be
reading it either.

Two event types exist:

**31415, lipsync** (36,402 events).  The parameter is a phoneme mask -- the
same bits the .mng layers carry in their flAG chunks.  Across 213 talkie
animations the naming is consistent:

    0x001 ROOT   0x002 A    0x004 EE   0x008 OH    0x010 U
    0x020 D (C)  0x080 M    0x100 TH   0x200 F     0x400 UH

An event sets the mouth and it holds until the next one -- these are state
changes, not pulses.  Mask 0 is the closed mouth between words.  The last
event always lands just inside the audio: 1.80s against 1.95s, 2.47s against
2.63s, 2.33s against 2.47s.

Two loose ends there, both real.  Bit 0x040 is used by nothing, in any
animation or any event.  Mask 0x800 appears in 30 events and matches no layer
in any animation in the game -- a mouth shape cut from the art but left in
the tracks; those events draw no mouth.

**15500, animation events** (2,384), which is `globals.TYPE_ANIMATION_EVENT`.
These carry the groups.  Every room stream opens with one at t=0 naming its
own animation, and the rest cue sound effects:

    0.0  AnimName  'Agi_broke1_op_demo'
    0.3  SoundName 'agi_crane'      Channel '1'
    0.8  SoundName 'agi_metalthud'  Channel '2'

SoundName and Channel always come in pairs -- 784 of each -- and Channel is
only ever '1' or '2'.  The single field key is always 'value'.
character.CAnimReciever.Raise is what consumes these, playing
`sfx/<SoundName>.wav`.
"""

import struct

import _stub

EVENT_LIPSYNC = 31415
EVENT_ANIMATION = 15500      # globals.TYPE_ANIMATION_EVENT
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


class Element(object):
    """One group: `element.name` and `element.attrs`, which is what
    character.CAnimReciever walks looking for 'SoundName'."""

    def __init__(self, name, attrs):
        self.name = name
        self.attrs = attrs

    def __repr__(self):
        return "<%s %s>" % (self.name, [a.value for a in self.attrs])


class Attr(object):
    def __init__(self, key, value):
        self.key = key
        self.name = key
        self.value = value


class Event(object):
    def __init__(self, when, kind, param, elements):
        self.time = when
        self.type = kind
        self.param = param
        self.elements = elements

    def named(self, name):
        """Values of every group with this name, e.g. 'SoundName'."""
        return [a.value for e in self.elements if e.name == name for a in e.attrs]


def _string(data, offset, length):
    """A NUL-terminated string of `length` characters, and what follows it."""
    return data[offset:offset + length], offset + length + 1


def parse(data):
    """[Event, ...], or None if this is not an event stream at all.

    Strict on purpose: the length in the header has to match, and the events
    have to consume the file exactly.  Every shipped .evb does both, so
    anything that does not is not this format and guessing at it would be
    worse than saying so.
    """
    if not data or len(data) < 8:
        return None
    try:
        size, count = struct.unpack_from("<II", data, 0)
        if size != len(data) or count < 0:
            return None
        offset = 8
        events = []
        for _event in range(count):
            when, kind, param, _one, _stale, _zero, groups = (
                struct.unpack_from("<fIIfIII", data, offset))
            offset += RECORD
            elements = []
            for _group in range(groups):
                name_len, fields = struct.unpack_from("<II", data, offset)
                offset += 8
                name, offset = _string(data, offset, name_len)
                attrs = []
                for _field in range(fields):
                    key_len, value_len = struct.unpack_from("<II", data, offset)
                    offset += 8
                    key, offset = _string(data, offset, key_len)
                    value, offset = _string(data, offset, value_len)
                    attrs.append(Attr(key, value))
                elements.append(Element(name, attrs))
            events.append(Event(when, kind, param, elements))
    except (struct.error, IndexError, TypeError), exc:
        _stub.LOG.record("call", "yagaevents.evb", "unreadable: %s" % exc)
        return None
    if offset != len(data):
        _stub.LOG.record("call", "yagaevents.evb",
                         "%d bytes left over, not an event stream"
                         % (len(data) - offset))
        return None
    return events
