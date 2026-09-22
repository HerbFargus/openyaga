#!/usr/bin/env python3
"""Extract the speech from a Humongous Entertainment SCUMM game's talkie bank.

    python tools/he_talkies.py PAJAMA.HE2 out_dir

The earlier Humongous games (Pajama Sam 1-3, Putt-Putt 1-5, Freddi Fish,
Spy Fox) are SCUMM "HE" games, not Yaga, and keep every spoken line in one
file, the talkie bank (.HE2):

    TLKB <size>                     the bank
      TALK <size>                   one line
        HSHD <size>  16 bytes       +6: sample rate (little-endian u16);
                                    the audio is always 8-bit, as ScummVM
                                    reads it -- the other bytes vary
        SBNG <size>                 lipsync data (mouth shapes over time)
        SDAT <size>                 the audio: unsigned 8-bit mono PCM

Chunk sizes are big-endian and include the 8-byte header.  The scripts
refer to a line by its offset in the bank, so each WAV is named by that
offset.  An index.csv lists offset, sample rate and duration.

Every character's lines are in the one bank, untagged; telling them apart
is a separate job.
"""

import argparse
import csv
import os
import struct
import sys
import wave


def talks(data):
    """Yield (offset, sample_rate, bits, pcm) for each TALK in a bank."""
    if data[:4] != b"TLKB":
        raise SystemExit("not a talkie bank (no TLKB header)")
    end = min(len(data), struct.unpack(">I", data[4:8])[0])
    pos = 8
    while pos + 8 <= end:
        tag = data[pos:pos + 4]
        size = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        if size < 8:
            break
        if tag == b"TALK":
            rate, bits, pcm = 11025, 8, None
            sub, stop = pos + 8, pos + size
            while sub + 8 <= stop:
                t2 = data[sub:sub + 4]
                s2 = struct.unpack(">I", data[sub + 4:sub + 8])[0]
                if s2 < 8:
                    break
                body = data[sub + 8:sub + s2]
                if t2 == b"HSHD" and len(body) >= 8:
                    found = struct.unpack("<H", body[6:8])[0]
                    if 4000 <= found <= 48000:
                        rate = found
                elif t2 == b"SDAT":
                    pcm = body
                sub += s2
            if pcm:
                yield pos, rate, bits, pcm
        pos += size


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("bank", help="the talkie bank, e.g. PAJAMA.HE2")
    ap.add_argument("out", help="folder for the WAVs and index.csv")
    args = ap.parse_args(argv)

    data = open(args.bank, "rb").read()
    os.makedirs(args.out, exist_ok=True)
    total, count = 0.0, 0
    with open(os.path.join(args.out, "index.csv"), "w", newline="") as fh:
        index = csv.writer(fh)
        index.writerow(["file", "offset", "rate", "bits", "seconds"])
        for offset, rate, bits, pcm in talks(data):
            if bits != 8:
                print("skipping %d: %d-bit audio" % (offset, bits), file=sys.stderr)
                continue
            name = "talk_%09d.wav" % offset
            with wave.open(os.path.join(args.out, name), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(1)          # WAV's 8-bit is unsigned, as SDAT is
                w.setframerate(rate)
                w.writeframes(pcm)
            seconds = len(pcm) / float(rate)
            index.writerow([name, offset, rate, bits, "%.3f" % seconds])
            total += seconds
            count += 1
    print("%d lines, %.1f minutes, from %s" % (count, total / 60, args.bank))


if __name__ == "__main__":
    main(sys.argv[1:])
