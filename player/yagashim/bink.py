# -*- coding: latin-1 -*-
"""Play the game's Bink movies, by streaming them through ffmpeg.

The 40 .da2 files are Bink 1 -- their magic is `BIKi` -- which ffmpeg has
decoded for years.  (The version it cannot read is Bink 2, `KB2`, which
postdates this game by a decade.)  They probe as:

    Video: binkvideo (BIKi), yuv420p, 640x480, 10 fps
    Audio: binkaudio_dct, 22050 Hz, mono

which is a happy set of numbers: 640x480 is exactly the window, and 10 fps is
exactly the rate the game's own loop runs at, so nothing needs rescaling or
resampling in time.

Video is streamed rather than cached.  Raw frames are 640*480*3 bytes, so the
172-second intro would be about 1.5 GB on disk and rather more if it were held
in memory; at 10 fps the pipe carries roughly 9 MB/s, which costs nothing.
Audio is the other way round: it is small, ffmpeg wants to write a seekable
WAV, and the mixer wants a whole chunk, so it is decoded once and cached.

Frames are timed off the wall clock, not off the number of ticks that have
gone by.  A dropped frame or a slow moment then costs one frame rather than
pushing the whole movie out of step with its own soundtrack -- over 172
seconds that difference is the difference between lip-sync and nonsense.
"""

import os
import time

import pygame

import _stub
import ffmpeg
import mp3

CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "cache", "movies")


class Movie(object):
    """One movie, decoding while it plays.

    The caller owns the clock: `surface_at(elapsed)` hands back the frame due
    that many seconds in, reading and discarding any frames that fell behind.
    """

    def __init__(self, path, data=None, width=640, height=480, fps=10.0):
        self.path = path
        self.width = int(width) or 640
        self.height = int(height) or 480
        self.fps = float(fps) or 10.0
        self.frame_bytes = self.width * self.height * 3

        self._data = data
        self._source = None        # a real file for ffmpeg to read
        self._temp = None          # ...which we may have had to write ourselves
        self._process = None
        self._surface = None
        self._index = -1           # index of the frame currently in _surface
        self._channel = None
        self._sound = None
        self._finished = False

    # -- setting up --------------------------------------------------------

    def _source_file(self):
        """Bink comes from loose files on disk, so ffmpeg can usually read it
        in place; only fall back to a temp copy if it came from an archive."""
        if self._source:
            return self._source
        try:
            import resources
            located = resources.locate(self.path)
        except Exception:
            located = None
        if located:
            self._source = located
            return self._source
        if self._data:
            import tempfile
            handle, name = tempfile.mkstemp(suffix=".bik", prefix="yaga_")
            os.write(handle, bytes(self._data))
            os.close(handle)
            self._temp = self._source = name
            return self._source
        return None

    def _audio(self):
        """Decode the soundtrack once and keep it; returns a Sound or None."""
        target = mp3.cache_path(self.path, root=CACHE)
        source = self._source_file()
        if source is None:
            return None
        if not (os.path.isfile(target) and os.path.getsize(target) > 44):
            if not ffmpeg.available():
                return None
            mp3.ensure_directory(target)
            init = pygame.mixer.get_init()
            arguments = ["-i", source, "-vn"]
            if init:
                arguments += ["-ar", str(int(init[0]))]
            arguments += ["-acodec", "pcm_s16le", target]
            ok, err = ffmpeg.run(arguments)
            if not ok or not os.path.isfile(target):
                # Not every movie has a soundtrack -- the Atari logo does not.
                _stub.LOG.record("call", "yagasprite.bink",
                                 "(%s) no audio: %s" % (self.path, err.strip()[:80]))
                return None
        try:
            return pygame.mixer.Sound(target)
        except Exception, exc:
            _stub.LOG.record("call", "yagasprite.bink",
                             "(%s) audio load failed: %s" % (self.path, exc))
            return None

    def Start(self):
        """Begin decoding.  Safe to call when ffmpeg is missing: nothing
        happens and the movie plays as a black screen, as it used to."""
        if self._process is not None or self._finished:
            return False
        source = self._source_file()
        if source is None or not ffmpeg.available():
            ffmpeg.warn_once("movies will be a black screen")
            self._finished = True
            return False

        self._process = ffmpeg.stream(["-i", source,
                                       "-f", "rawvideo", "-pix_fmt", "rgb24",
                                       "pipe:1"])
        if self._process is None:
            self._finished = True
            return False

        self._sound = self._audio()
        if self._sound is not None:
            try:
                self._channel = self._sound.play()
            except Exception:
                self._channel = None
        _stub.LOG.record("call", "yagasprite.bink.Start",
                         "(%s) %dx%d at %.1f fps%s"
                         % (self.path, self.width, self.height, self.fps,
                            "" if self._sound is None else " with audio"))
        return True

    # -- playing -----------------------------------------------------------

    def _read_frame(self):
        """One frame off the pipe, or None at the end of the movie."""
        wanted = self.frame_bytes
        chunks = []
        got = 0
        while got < wanted:
            try:
                block = self._process.stdout.read(wanted - got)
            except Exception:
                block = ""
            if not block:
                # End of the movie: let go of the pipes now rather than
                # holding a handle open for each of the game's 40 movies.
                self._finished = True
                self._reap()
                return None
            chunks.append(block)
            got += len(block)
        return "".join(chunks)

    def surface_at(self, elapsed):
        """The frame due `elapsed` seconds in, as a pygame Surface.

        Frames that fell behind are read and thrown away rather than shown
        late: the soundtrack is the thing to stay level with.
        """
        if self._process is None or self._finished:
            return self._surface
        due = int(elapsed * self.fps)
        while self._index < due:
            raw = self._read_frame()
            if raw is None:
                break
            self._index += 1
            if self._index >= due:
                try:
                    self._surface = pygame.image.fromstring(
                        raw, (self.width, self.height), "RGB")
                except Exception, exc:
                    _stub.LOG.record("call", "yagasprite.bink",
                                     "(%s) bad frame: %s" % (self.path, exc))
                    self._finished = True
                    break
        return self._surface

    def _reap(self):
        """Close the pipes and collect the process, if it is still around."""
        if self._process is None:
            return
        for stream in (self._process.stdout, self._process.stderr):
            try:
                stream.close()
            except Exception:
                pass
        try:
            self._process.poll()
            if self._process.returncode is None:
                self._process.kill()
            self._process.wait()
        except Exception:
            pass
        self._process = None

    def SetVolume(self, level):
        if self._sound is not None:
            try:
                self._sound.set_volume(max(0.0, min(1.0, float(level))))
            except (TypeError, ValueError):
                pass

    def Stop(self):
        if self._channel is not None:
            try:
                self._channel.stop()
            except Exception:
                pass
            self._channel = None
        self._reap()
        self._finished = True
        if self._temp:
            try:
                os.remove(self._temp)
            except OSError:
                pass
            self._temp = None
