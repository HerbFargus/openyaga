# -*- coding: latin-1 -*-
"""Turn the game's MP3 dialogue into PCM, so it can play as an ordinary sound.

SDL_mixer 1.2 decodes MP3 only on the music channel, and there is exactly one
of those.  The game has 1,389 talkie MP3s and 41 music MP3s, so dialogue and
score collide: whichever starts last wins, and the music manager restarts the
score the moment it notices its track stopped -- cutting the line off in the
same frame it began.

The original engine mixed them, which is plain in the game's own settings:

    self.musicVolume = 0.3

music has its own slider, defaulted low, so it sits *under* everything else.

So dialogue is decoded to PCM here and handed to the mixer as a chunk, which
plays on any of the ordinary channels alongside the music.  Music itself stays
on the streaming channel: a three-minute track would decode to tens of
megabytes for no benefit.

Results are cached as .wav under player/cache/audio, mirroring the game's own
paths, so a line is decoded once per install and not once per playing.
Without ffmpeg (see ffmpeg.py) dialogue falls back to the music channel, which
is the old behaviour -- lines cut the music and each other.
"""

import os

import _stub
import ffmpeg

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(os.path.dirname(HERE), "cache", "audio")


def cache_path(path, root=CACHE, extension=".wav"):
    """player/cache/audio/talkies/sam/pj4pc_sam_00055.wav, and so on."""
    clean = str(path).replace("\\", "/").lstrip("/")
    stem, _ext = os.path.splitext(clean)
    return os.path.join(root, *(stem.split("/"))) + extension


def ensure_directory(target):
    directory = os.path.dirname(target)
    if directory and not os.path.isdir(directory):
        try:
            os.makedirs(directory)
        except OSError:
            pass


def decode(path, data, mixer_format=None):
    """MP3 bytes -> a path to PCM WAV on disk, or None if it cannot be done.

    mixer_format is (frequency, channels) from pygame.mixer.get_init().  Only
    the frequency is matched: resampling is the expensive conversion and worth
    doing once, here, while the talkies are mono and the mixer is stereo --
    widening that at load costs almost nothing and halves what sits on disk.
    """
    target = cache_path(path)
    if os.path.isfile(target) and os.path.getsize(target) > 44:
        return target

    if not ffmpeg.available():
        ffmpeg.warn_once("dialogue will interrupt the music")
        return None

    ensure_directory(target)
    arguments = ["-i", "pipe:0", "-vn"]
    if mixer_format:
        arguments += ["-ar", str(int(mixer_format[0]))]
    arguments += ["-acodec", "pcm_s16le", target]

    ok, err = ffmpeg.run(arguments, stdin_data=bytes(data))
    if not ok or not os.path.isfile(target):
        _stub.LOG.record("call", "yagasound.mp3",
                         "(%s) ffmpeg failed: %s" % (path, err.strip()[:120]))
        return None
    return target
