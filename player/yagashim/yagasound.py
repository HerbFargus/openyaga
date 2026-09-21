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
  there is exactly one.  Dialogue and music are both MP3, so the last one
  started wins.  The original engine used Miles Sound System and had no such
  limit; this is the first place the player is meaningfully less capable than
  the real thing.

ISound is a plain object rather than a Stub subclass: `volume` has to be a
real property so setting it reaches the mixer, and Stub's __setattr__ would
swallow it.  Unknown attributes still fall back to a stub.
"""

import os
import sys
import tempfile
import time

import pygame

import _stub

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
            _mixer_ready = True
        except pygame.error, exc:
            _stub.LOG.record("call", "yagasound.mixer", "unavailable: %s" % exc)
            _mixer_ready = False
    return _mixer_ready


def _temp_mp3(path, data):
    """SDL_mixer's music loader wants a real file."""
    existing = _mp3_cache.get(path)
    if existing and os.path.isfile(existing):
        return existing
    handle, name = tempfile.mkstemp(suffix=".mp3", prefix="yaga_")
    os.write(handle, data)
    os.close(handle)
    _mp3_cache[path] = name
    return name


class ISound(object):
    def __init__(self, res=None):
        object.__setattr__(self, "_ready", False)
        self.resource = res
        self.path = str(getattr(res, "path", "") or "")
        self.is_music = self.path.lower().endswith(".mp3")
        self.chunk = None
        self.channel = None
        self._started = None
        self.volume = 1.0
        object.__setattr__(self, "_ready", True)

        data = getattr(res, "data", None)
        if data is None or not _ensure_mixer():
            return
        if not self.is_music:
            try:
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
        if self.chunk is not None:
            return bool(self.channel and self.channel.get_busy())
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

    def Run(self, scene=None, *a, **kw):
        global _music_owner
        if not _ensure_mixer():
            return
        if self.chunk is not None:
            self.channel = self.chunk.play()
        elif self.is_music:
            data = getattr(self.resource, "data", None)
            if data is None:
                return
            try:
                pygame.mixer.music.load(_temp_mp3(self.path, bytes(data)))
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
        if self.chunk is not None and self.channel:
            self.channel.stop()
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
