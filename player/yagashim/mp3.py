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

Decoding needs ffmpeg.  Nothing here ships it, and it is looked for in this
order:

    OPENYAGA_FFMPEG         an explicit path, if you have one
    PATH                    the usual case
    player/ffmpeg.exe       drop one next to run_game.py
    a few common install directories

Results are cached as .wav under player/cache/audio, mirroring the game's own
paths, so a line is decoded once per install and not once per playing.

Without ffmpeg the player still runs: dialogue falls back to the music
channel, which is the old behaviour -- lines cut the music and each other.
"""

import os
import subprocess
import sys

import _stub

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(os.path.dirname(HERE), "cache", "audio")

# Where ffmpeg tends to live on Windows when it is not on PATH.  Checked in
# order; the first that exists wins.
_LIKELY = [
    # Dropped in beside run_game.py, which needs no configuration at all.
    os.path.join(os.path.dirname(HERE), "ffmpeg.exe"),
    os.path.join(os.path.dirname(HERE), "ffmpeg"),
    r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
    os.path.expanduser(r"~\scoop\shims\ffmpeg.exe"),
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    r"C:\ffmpeg\bin\ffmpeg.exe",
]

_ffmpeg = None           # None = not looked for yet, False = not found
_warned = False


def _find_ffmpeg():
    """Locate ffmpeg once, and say in the log what happened."""
    global _ffmpeg
    if _ffmpeg is not None:
        return _ffmpeg

    candidates = []
    explicit = os.environ.get("OPENYAGA_FFMPEG")
    if explicit:
        candidates.append(explicit)

    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if directory:
            candidates.append(os.path.join(directory, "ffmpeg.exe"))
            candidates.append(os.path.join(directory, "ffmpeg"))

    candidates.extend(_LIKELY)

    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            _ffmpeg = candidate
            _stub.LOG.record("call", "yagasound.mp3", "decoder: %s" % candidate)
            return _ffmpeg

    _ffmpeg = False
    return _ffmpeg


def available():
    return bool(_find_ffmpeg())


def _no_window():
    """Keep ffmpeg from flashing a console window on Windows."""
    if not sys.platform.startswith("win"):
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 0      # SW_HIDE
    return info


def _cache_path(path):
    """player/cache/audio/talkies/sam/pj4pc_sam_00055.wav, and so on."""
    clean = path.replace("\\", "/").lstrip("/")
    root, _ext = os.path.splitext(clean)
    return os.path.join(CACHE, *(root.split("/"))) + ".wav"


def decode(path, data, mixer_format=None):
    """MP3 bytes -> a path to PCM WAV on disk, or None if it cannot be done.

    mixer_format is (frequency, channels) from pygame.mixer.get_init().  Only
    the frequency is matched: resampling is the expensive conversion and worth
    doing once, here, while the talkies are mono and the mixer is stereo --
    widening that at load costs almost nothing and halves what sits on disk.
    """
    global _warned

    target = _cache_path(path)
    if os.path.isfile(target) and os.path.getsize(target) > 44:
        return target

    binary = _find_ffmpeg()
    if not binary:
        if not _warned:
            _warned = True
            _stub.LOG.record("call", "yagasound.mp3",
                             "no ffmpeg: dialogue falls back to the music "
                             "channel and will cut the score")
            print ("openyaga: ffmpeg not found -- dialogue will interrupt the "
                   "music.  Set OPENYAGA_FFMPEG to an ffmpeg binary to fix.")
        return None

    directory = os.path.dirname(target)
    if not os.path.isdir(directory):
        try:
            os.makedirs(directory)
        except OSError:
            pass

    command = [binary, "-hide_banner", "-loglevel", "error", "-y",
               "-i", "pipe:0", "-vn"]
    if mixer_format:
        frequency = mixer_format[0]
        command += ["-ar", str(int(frequency))]
    command += ["-acodec", "pcm_s16le", target]

    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE,
                                   startupinfo=_no_window())
        _out, err = process.communicate(bytes(data))
    except Exception, exc:
        _stub.LOG.record("call", "yagasound.mp3",
                         "(%s) could not run ffmpeg: %s" % (path, exc))
        return None

    if process.returncode != 0 or not os.path.isfile(target):
        _stub.LOG.record("call", "yagasound.mp3",
                         "(%s) ffmpeg failed: %s" % (path, (err or "").strip()[:120]))
        return None
    return target
