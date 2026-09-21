# -*- coding: latin-1 -*-
"""Finding and running ffmpeg.

Two parts of the player need it, for the same reason: the game ships media in
formats SDL cannot open.  Dialogue is MP3, which SDL_mixer 1.2 will only decode
on its single music channel (see mp3.py), and the movies are Bink, which it
cannot decode at all (see bink.py).

Nothing here ships ffmpeg.  It is looked for in this order:

    OPENYAGA_FFMPEG         an explicit path, if you have one
    PATH                    the usual case
    player/ffmpeg.exe       drop one next to run_game.py
    a few common install directories

Without it the player still runs: dialogue falls back to the music channel and
movies are a black screen for their real duration.
"""

import os
import subprocess
import sys

import _stub

HERE = os.path.dirname(os.path.abspath(__file__))
PLAYER = os.path.dirname(HERE)

# Where ffmpeg tends to live when it is not on PATH.  Checked in order; the
# first that exists wins.
_LIKELY = [
    # Dropped in beside run_game.py, which needs no configuration at all.
    os.path.join(PLAYER, "ffmpeg.exe"),
    os.path.join(PLAYER, "ffmpeg"),
    r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
    os.path.expanduser(r"~\scoop\shims\ffmpeg.exe"),
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    r"C:\ffmpeg\bin\ffmpeg.exe",
    # Homebrew (Apple Silicon, Intel) and the usual Linux places, for when
    # PATH is thin -- a launcher started outside a login shell, say.
    "/opt/homebrew/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    "/usr/bin/ffmpeg",
]

_binary = None           # None = not looked for yet, False = not found
_warned = False


def find():
    """The ffmpeg binary, or False.  Looked for once and remembered."""
    global _binary
    if _binary is not None:
        return _binary

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
            _binary = candidate
            _stub.LOG.record("call", "yagasound.ffmpeg", "decoder: %s" % candidate)
            return _binary

    _binary = False
    return _binary


def available():
    return bool(find())


def warn_once(message):
    """Say once, to the log and to the console, that ffmpeg is missing."""
    global _warned
    if _warned:
        return
    _warned = True
    _stub.LOG.record("call", "yagasound.ffmpeg", "not found: %s" % message)
    # Not `print`: boot.py replaces sys.stdout with its own redirector, which
    # sends this to the game's log file where nobody will read it.  The real
    # stderr is still the console.
    try:
        sys.__stderr__.write(
            "openyaga: ffmpeg not found -- %s\n"
            "          Put ffmpeg.exe beside run_game.py, "
            "or set OPENYAGA_FFMPEG.\n" % message)
        sys.__stderr__.flush()
    except Exception:
        pass


def no_window():
    """Keep ffmpeg from flashing a console window on Windows."""
    if not sys.platform.startswith("win"):
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 0      # SW_HIDE
    return info


def run(arguments, stdin_data=None):
    """Run ffmpeg to completion.  Returns (ok, stderr)."""
    binary = find()
    if not binary:
        return False, "no ffmpeg"
    command = [binary, "-hide_banner", "-loglevel", "error", "-y"] + arguments
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE if stdin_data is not None else None,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            startupinfo=no_window())
        _out, err = process.communicate(stdin_data)
    except Exception, exc:
        return False, str(exc)
    return process.returncode == 0, (err or "")


def stream(arguments, bufsize=1 << 20):
    """Start ffmpeg and hand back the process, for reading its stdout.

    Used for video, where decoding a whole movie up front would cost more
    memory than the machine has any reason to spend: the intro alone is 172
    seconds, which is about 1.5 GB of raw frames.
    """
    binary = find()
    if not binary:
        return None
    command = [binary, "-hide_banner", "-loglevel", "error"] + arguments
    try:
        return subprocess.Popen(command, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, bufsize=bufsize,
                                startupinfo=no_window())
    except Exception, exc:
        _stub.LOG.record("call", "yagasound.ffmpeg", "could not start: %s" % exc)
        return None
