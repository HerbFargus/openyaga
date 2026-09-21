#!/usr/bin/env python3
"""Fetch the ffmpeg build the player uses for dialogue and movies (Windows).

    python get_ffmpeg.py

openyaga does not ship ffmpeg and this script is not run for you.  It is here
because Windows has no package manager in the picture: on macOS or Linux,
`brew install ffmpeg` or `apt install ffmpeg` puts ffmpeg on PATH and the
player finds it with no help.

What it does: downloads one pinned zip, checks it against a SHA-256 recorded
here, takes the single file `ffmpeg.exe` out of it, and puts it beside
run_game.py where the player looks.  The hash is the point -- an unverified
download of an executable is not something to do twice.

Why this build:

* **LGPL.**  We only ever decode, and the three decoders we need -- binkvideo,
  binkaudio_dct and mp3 -- are native ffmpeg code in the LGPL core.  Nothing
  here wants the GPL variants, which exist for encoders like x264.  openyaga
  stays MIT and is not a derivative work of ffmpeg: it runs it as a separate
  program over a pipe.  You are downloading it for yourself; nobody is
  redistributing anything.
* **Static.**  BtbN's `-shared` zips are less than half the size but need
  their DLLs alongside, and a lone ffmpeg.exe lifted out of one will not
  start.  One self-contained file is worth the extra download.
* **A dated tag.**  BtbN's `latest` release is rebuilt daily, so it cannot be
  pinned; `autobuild-YYYY-MM-DD-HH-MM` tags do not move.

Source, and the corresponding ffmpeg source, are at
https://github.com/BtbN/FFmpeg-Builds -- see LICENSE there for the terms the
binary comes under, which are not openyaga's.
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from urllib.request import urlopen

HERE = os.path.dirname(os.path.abspath(__file__))

# Pinned 2026-09-21.  To move to a newer build: pick a dated release from
# https://github.com/BtbN/FFmpeg-Builds/releases, take the win64-lgpl zip
# (not -shared), and copy its name, size and sha256 from the GitHub API --
# the releases endpoint reports a `digest` for every asset, so the hash below
# never has to come from the download it is meant to be checking.
RELEASE = "autobuild-2026-09-21-13-55"
ARCHIVE = "ffmpeg-n8.1.3-win64-lgpl-8.1.zip"
SHA256 = "ef320b236065afe9a8dfd5f2b5aeca0fd0f0196c6dd77958b735fcbb74c10f58"
SIZE = 169515608                       # reported before anything is written
URL = ("https://github.com/BtbN/FFmpeg-Builds/releases/download/%s/%s"
       % (RELEASE, ARCHIVE))

TARGET = os.path.join(HERE, "ffmpeg.exe")


def already_on_path():
    """The player searches PATH before player/ffmpeg.exe, so say so."""
    return shutil.which("ffmpeg")


def download(url, into):
    """Stream to disk, reporting progress, and return the SHA-256."""
    digest = hashlib.sha256()
    done = 0
    with urlopen(url) as response, open(into, "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        while True:
            block = response.read(1 << 20)
            if not block:
                break
            out.write(block)
            digest.update(block)
            done += len(block)
            if total:
                sys.stdout.write("\r  %5.1f%%  %6.1f / %.1f MB"
                                 % (done * 100.0 / total, done / 1048576.0,
                                    total / 1048576.0))
                sys.stdout.flush()
    print()
    return digest.hexdigest(), done


def extract_ffmpeg(archive, target):
    """Pull just bin/ffmpeg.exe out, whatever the top-level folder is called."""
    with zipfile.ZipFile(archive) as zf:
        members = [n for n in zf.namelist()
                   if n.replace("\\", "/").endswith("bin/ffmpeg.exe")]
        if not members:
            raise SystemExit("no bin/ffmpeg.exe inside %s" % os.path.basename(archive))
        with zf.open(members[0]) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)
    return members[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true",
                    help="replace an existing player/ffmpeg.exe")
    ap.add_argument("--keep-archive", action="store_true",
                    help="leave the downloaded zip in place")
    args = ap.parse_args()

    if os.path.isfile(TARGET) and not args.force:
        print("Already here: %s" % TARGET)
        print("Nothing to do.  Use --force to replace it.")
        return 0

    found = already_on_path()
    if found:
        print("Note: ffmpeg is already on PATH at")
        print("    %s" % found)
        print("The player will use that and this download is not needed;")
        print("carrying on because you asked for it.")
        print()

    print("Downloading   %s" % ARCHIVE)
    print("from          %s" % URL)
    print("size          %.1f MB" % (SIZE / 1048576.0))
    print("sha256        %s" % SHA256)
    print()

    handle, archive = tempfile.mkstemp(suffix=".zip", prefix="openyaga_ffmpeg_")
    os.close(handle)
    try:
        got, size = download(URL, archive)
        if got != SHA256:
            # Do not unpack, do not keep: this is either a corrupted transfer
            # or not the file this script was written against.
            os.remove(archive)
            print("CHECKSUM MISMATCH -- nothing was installed.", file=sys.stderr)
            print("  expected %s" % SHA256, file=sys.stderr)
            print("  got      %s" % got, file=sys.stderr)
            return 1
        print("  checksum ok (%.1f MB)" % (size / 1048576.0))

        member = extract_ffmpeg(archive, TARGET)
        print("  extracted %s" % member)
    finally:
        if not args.keep_archive and os.path.isfile(archive):
            os.remove(archive)

    try:
        banner = subprocess.run([TARGET, "-version"], capture_output=True,
                                text=True, timeout=30).stdout.splitlines()
        print("  %s" % (banner[0] if banner else "(no version banner)"))
    except Exception as exc:
        print("  installed, but it would not run: %s" % exc, file=sys.stderr)
        return 1

    print()
    print("Installed: %s" % TARGET)
    print("The player will find it there with no further configuration.")
    print("It is ffmpeg, under its own licence -- see")
    print("https://github.com/BtbN/FFmpeg-Builds for the terms and the source.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
