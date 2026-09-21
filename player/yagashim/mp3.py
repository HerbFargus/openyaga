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


# -- lengths -----------------------------------------------------------------
_BITRATES = {  # (MPEG-1?, layer) -> kbps by index
    (True, 3): (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    (True, 2): (0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384),
    (True, 1): (0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448),
    (False, 3): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
    (False, 2): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
    (False, 1): (0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256),
}
_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}


def length(data):
    """Seconds of audio in an MP3, by walking its frames -- right for variable
    bitrate too, where size/bitrate is not.  None if no frames are found.

    Replay needs it: whether the score is still playing decides when the music
    manager restarts it, and a replayed session has to decide that from the
    clock, identically, rather than ask the sound card."""
    data = bytearray(data)
    pos, end, seconds, frames = 0, len(data), 0.0, 0
    if data[:3] == b"ID3" and end > 10:
        pos = 10 + ((data[6] & 0x7F) << 21 | (data[7] & 0x7F) << 14 |
                    (data[8] & 0x7F) << 7 | (data[9] & 0x7F))
    while pos + 4 <= end:
        if data[pos] != 0xFF or (data[pos + 1] & 0xE0) != 0xE0:
            pos += 1
            continue
        version = (data[pos + 1] >> 3) & 3          # 3 = MPEG-1, 2 = 2, 0 = 2.5
        layer = 4 - ((data[pos + 1] >> 1) & 3)      # 1, 2 or 3
        b_index = data[pos + 2] >> 4
        r_index = (data[pos + 2] >> 2) & 3
        padding = (data[pos + 2] >> 1) & 1
        if version == 1 or layer == 4 or b_index in (0, 15) or r_index == 3:
            pos += 1
            continue
        mpeg1 = version == 3
        bitrate = _BITRATES[(mpeg1, layer)][b_index] * 1000
        rate = _RATES[version][r_index]
        if layer == 1:
            samples = 384
            size = (12 * bitrate // rate + padding) * 4
        else:
            samples = 1152 if (layer == 2 or mpeg1) else 576
            size = samples // 8 * bitrate // rate + padding
        if size < 4:
            pos += 1
            continue
        seconds += float(samples) / rate
        frames += 1
        pos += size
    return seconds if frames else None


def wav_length(data):
    """Seconds of audio in a PCM or ADPCM WAV, from its header."""
    import struct
    data = bytes(data)
    if data[:4] != "RIFF" or data[8:12] != "WAVE":
        return None
    pos, byte_rate, size = 12, None, None
    while pos + 8 <= len(data):
        tag, n = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        if tag == "fmt ":
            byte_rate = struct.unpack("<I", data[pos + 16:pos + 20])[0]
        elif tag == "data":
            size = min(n, len(data) - pos - 8)
            break
        pos += 8 + n + (n & 1)
    if not byte_rate or size is None:
        return None
    return float(size) / byte_rate
