# -*- coding: latin-1 -*-
"""Real stand-in for the native yagasound module.

sound_manager wants very little from a sound:

    sound = yagasound.ISound(res)      # res from the resource manager
    sound.volume = 0.0 .. 1.0
    sound.Run(soundScene)              # start
    sound.Stop(soundScene)             # stop
    sound.isPlaying                    # drives Tick, which fires callbacks
                                       # and forgets finished sounds

The game ships two kinds of audio and they take different routes through
SDL_mixer:

* **WAV** -- loaded as a Mix chunk, so any number can play at once.  This is
  every sound effect and clickpoint noise.
* **MP3** -- SDL_mixer only decodes MP3 on the *music* channel, of which
  there is exactly one, and both dialogue and score are MP3.  Left at that the
  last sound started wins, so a line of dialogue cuts the music, the music
  manager restarts the score on the next tick, and the line dies in the frame
  it began.

  So only the score streams from that channel.  Dialogue is decoded to PCM
  (see mp3.py) and played as an ordinary chunk, which is what the original
  engine did -- the game mixes music underneath everything else at its own
  volume, defaulted to 0.3.  Without a decoder available the old behaviour is
  the fallback.

ISound is a plain object rather than a Stub subclass: `volume` has to be a
real property so setting it reaches the mixer, and Stub's __setattr__ would
swallow it.  Unknown attributes still fall back to a stub.
"""

import itertools
import os
import sys
import tempfile
import time

import pygame

import _stub
import mp3

try:
    import cStringIO as _io
except ImportError:
    import StringIO as _io

_mod = _stub.StubModule(__name__)

_mixer_ready = None
_music_owner = None      # which ISound currently owns the single music channel
_mp3_cache = {}          # game path -> temp file, since music needs a file


def _ensure_mixer():
    global _mixer_ready
    if _mixer_ready is None:
        try:
            pygame.mixer.init()
            # Eight is the default and the game will exceed it: dialogue,
            # a clickpoint, ambient noise and a room's own effects overlap
            # routinely now that dialogue is a chunk rather than the music.
            pygame.mixer.set_num_channels(32)
            _mixer_ready = True
        except pygame.error, exc:
            _stub.LOG.record("call", "yagasound.mixer", "unavailable: %s" % exc)
            _mixer_ready = False
    return _mixer_ready


def _temp_music(path, data):
    """SDL_mixer's music loader wants a real file -- with the right
    extension: the score is mostly MP3, but the dresser climb's four tracks
    are WAV, and handed a .mp3 name the loader tried to decode PCM as MPEG
    ("Error reading the stream") and the room played no music."""
    existing = _mp3_cache.get(path)
    if existing and os.path.isfile(existing):
        return existing
    suffix = os.path.splitext(path)[1].lower() or ".mp3"
    handle, name = tempfile.mkstemp(suffix=suffix, prefix="yaga_")
    os.write(handle, data)
    os.close(handle)
    _mp3_cache[path] = name
    return name


_sequence = itertools.count(1)


class ISound(object):
    # Hashed by creation order, not address: the sound manager keeps its
    # sounds in a dict keyed by the sound, and iterating that in address
    # order made a replayed session run their callbacks in a different
    # order from the recording.
    def __hash__(self):
        return object.__getattribute__(self, "_seq")

    def __init__(self, res=None):
        object.__setattr__(self, "_seq", next(_sequence))
        object.__setattr__(self, "_ready", False)
        self.resource = res
        self.path = str(getattr(res, "path", "") or "")
        # Only the score belongs on the one streaming channel.  Everything
        # else that happens to be MP3 -- all 1,389 lines of dialogue -- is
        # decoded and mixed like any other sound.
        normalised = self.path.lower().replace("\\", "/").lstrip("/")
        self.is_music = normalised.split("/")[0] == "music"
        self.is_mp3 = normalised.endswith(".mp3")
        self.chunk = None
        self.channel = None
        self._started = None
        self.volume = 1.0
        object.__setattr__(self, "_ready", True)

        data = getattr(res, "data", None)
        if data is None or not _ensure_mixer():
            return
        if self.is_music:
            return
        source = mp3.voice_pack_line(self.path)
        if source is None and self.is_mp3:
            init = pygame.mixer.get_init()
            source = mp3.decode(self.path, data,
                                (init[0], init[2]) if init else None)
            if source is None:
                # No decoder.  Fall back to the streaming channel, which is
                # the old behaviour: audible, but it will cut the music.
                self.is_music = True
                return
        try:
            if source:
                self.chunk = pygame.mixer.Sound(source)
            else:
                self.chunk = pygame.mixer.Sound(_io.StringIO(bytes(data)))
        except Exception, exc:
            _stub.LOG.record("call", "yagasound.ISound",
                             "(%s) could not load: %s" % (self.path, exc))

    # volume has to reach the mixer as soon as it is set
    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)
        if name == "volume" and object.__getattribute__(self, "_ready"):
            self._apply_volume()

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _stub.Stub("yagasound.ISound.%s" % name)

    def _apply_volume(self):
        try:
            level = max(0.0, min(1.0, float(self.volume)))
        except (TypeError, ValueError):
            return
        if self.chunk is not None:
            self.chunk.set_volume(level)
        elif self.is_music and _mixer_ready:
            pygame.mixer.music.set_volume(level)

    @property
    def duration(self):
        """Seconds.  The script reads this to time its subtitles.

        A Mix chunk knows its own length; for MP3 the mixer will not say, so
        estimate from the file size at the 64 kbps these talkies were encoded
        at -- close enough for text timing, and better than zero.
        """
        if self.chunk is not None:
            return self.chunk.get_length()
        data = getattr(self.resource, "data", None)
        if data:
            return len(data) * 8.0 / 64000.0
        return 0.0

    @property
    def isPlaying(self):
        import replay
        if replay.active():
            return self._clock_playing()
        if self.chunk is not None:
            # Busy is not enough: it says the *channel* is playing something.
            # Once this sound ends its channel is free, and the next sound to
            # start takes the first free one -- at Agitator Lake that is the
            # water, which repeats every few seconds.  Asking only get_busy()
            # then reported the crane operator's finished line as playing for
            # ever, and the conversation waiting on it never moved on.  The
            # channel has to be busy with *this* sound.
            if not self.channel or not self.channel.get_busy():
                return False
            return self.channel.get_sound() is self.chunk
        if not (self.is_music and _mixer_ready):
            return False
        # SDL_mixer has ONE music channel, so get_busy() alone says only that
        # *something* is playing.  Reporting that for a finished piece of
        # dialogue is fatal: the script waits for the talkie to end and the
        # game stops responding while the background music keeps going.
        # A sound is playing only while it still owns the channel.
        if _music_owner is not self:
            return False
        if self.duration and time.time() - (self._started or 0) > self.duration + 0.25:
            return False
        return bool(pygame.mixer.music.get_busy())

    def _length(self):
        """Seconds, from the data itself -- the sound card is not asked."""
        known = object.__getattribute__(self, "__dict__").get("_known_length")
        if known is not None:
            return known
        length = None
        if self.chunk is not None:
            length = self.chunk.get_length()
        else:
            data = getattr(self.resource, "data", None)
            if data:
                length = (mp3.length(data) if self.is_mp3
                          else mp3.wav_length(data))
        length = length or 0.0
        object.__setattr__(self, "_known_length", length)
        return length

    def _clock_playing(self):
        """Under record and replay: playing until its length has passed on
        the virtual clock, unless stopped or, for music, replaced.  Asking the
        mixer instead would make the answer depend on real time, and a replay
        would drift from its recording the first time a line ended a frame
        early or late."""
        if not object.__getattribute__(self, "__dict__").get("_clock_started"):
            return False
        if self.is_music and self.chunk is None and _music_owner is not self:
            return False
        return time.time() - self._clock_started < self._length()

    def Run(self, scene=None, *a, **kw):
        global _music_owner
        object.__setattr__(self, "_clock_started", time.time())
        if not _ensure_mixer():
            return
        if self.chunk is not None:
            self.channel = self.chunk.play()
        elif self.is_music:
            data = getattr(self.resource, "data", None)
            if data is None:
                return
            try:
                pygame.mixer.music.load(_temp_music(self.path, bytes(data)))
                pygame.mixer.music.play()
                _music_owner = self
                self._started = time.time()
            except Exception, exc:
                _stub.LOG.record("call", "yagasound.ISound.Run",
                                 "(%s) %s" % (self.path, exc))
                return
        self._apply_volume()
        _stub.LOG.record("call", "yagasound.ISound.Run", "(%s)" % self.path)

    def Stop(self, scene=None, *a, **kw):
        global _music_owner
        object.__setattr__(self, "_clock_started", None)
        if self.chunk is not None:
            # Stop this sound wherever it is playing -- not whatever has since
            # taken the channel it started on.
            self.chunk.stop()
        elif self.is_music and _mixer_ready:
            if _music_owner is self:
                _music_owner = None
            pygame.mixer.music.stop()

    def __nonzero__(self):
        return True

    def __repr__(self):
        return "<ISound %s>" % self.path


class SoundSystem(_stub.Stub):
    def __init__(self):
        _stub.Stub.__init__(self, "yagasound.SoundSystem()")
        _ensure_mixer()
        self.flags = 0

    def __nonzero__(self):
        return True


_system = None


def SoundSystemFactory():
    global _system
    if _system is None:
        _system = SoundSystem()
    return _system


def cleanup():
    for path in _mp3_cache.values():
        try:
            os.remove(path)
        except OSError:
            pass
    _mp3_cache.clear()


_mod.ISound = ISound
_mod.SoundSystem = SoundSystemFactory
_mod.cleanup = cleanup

_mod.__wrapped_module__ = sys.modules[__name__]
sys.modules[__name__] = _mod
