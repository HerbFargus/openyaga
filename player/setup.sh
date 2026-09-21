#!/usr/bin/env bash
# One-time setup for Linux and macOS.
#
#     player/setup.sh "/path/to/Pajama Sam LRS"
#
# The folder is your installed copy of the game: the one holding
# PajamaLRS.exe and its data (from a Windows install, or a Wine prefix such as
# ~/.wine/drive_c/Program Files (x86)/Atari/Pajama Sam LRS).
#
# Everything goes inside player/ -- nothing is installed system wide and
# nothing needs sudo:
#
#   .venv-setup   Python 3 + uncompyle6, to recover the game's scripts once
#   .venv-sdl2    Python 2.7 + pygame 2 (SDL2), the runtime the game needs
#   .tools        micromamba, and ffmpeg if the system has none
#
# What the system already has is used first: python3 with venv, a python2.7
# on PATH (or named by $PYTHON27), ffmpeg on PATH.  Whatever is missing comes
# from conda-forge through micromamba, a single-file conda installer fetched
# into player/.tools -- so a stock install with no python3-venv, no Python 2
# and no ffmpeg still works without asking for a password.  On Apple Silicon
# the Python 2.7 runtime is the Intel build under Rosetta: no arm64 build of
# Python 2.7 or its pygame exists.
#
# Safe to re-run: finished steps are skipped.  Delete player/.venv-sdl2 to
# rebuild the runtime.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS="$HERE/.tools"
SETUP_ENV="$HERE/.venv-setup"
RUNTIME="$HERE/.venv-sdl2"
PYGAME_VERSION="2.0.3"          # the last pygame for Python 2.7
UNCOMPYLE6_VERSION="3.9.3"

say()  { printf '\n==> %s\n' "$*"; }
note() { printf '    %s\n' "$*"; }
die()  { printf '\nerror: %s\n' "$*" >&2; exit 1; }

GAME_DIR="${1:-}"
[ -n "$GAME_DIR" ] || die "usage: $0 \"/path/to/the installed game folder\""
[ -d "$GAME_DIR" ] || die "no such folder: $GAME_DIR"

OS="$(uname -s)"
ARCH="$(uname -m)"
case "$OS/$ARCH" in
    Linux/x86_64)              HOST=linux-64 ;;
    Linux/aarch64|Linux/arm64) HOST=linux-aarch64 ;;
    Darwin/x86_64)             HOST=osx-64 ;;
    Darwin/arm64)              HOST=osx-arm64 ;;
    Linux/*|Darwin/*)          die "unsupported machine: $OS/$ARCH" ;;
    *) die "this script is for Linux and macOS; on Windows follow player/README.md" ;;
esac

# -- micromamba: whatever the system lacks ------------------------------------
MAMBA="$TOOLS/bin/micromamba"

fetch_micromamba() {
    [ -x "$MAMBA" ] && return
    command -v curl >/dev/null || die "curl not found"
    mkdir -p "$TOOLS"
    note "fetching micromamba ($HOST) into player/.tools"
    local archive="$TOOLS/micromamba.tar.bz2"
    curl -fsSL -o "$archive" "https://micro.mamba.pm/api/micromamba/$HOST/latest" ||
        die "could not download micromamba"
    if command -v bzip2 >/dev/null 2>&1; then
        tar -xjf "$archive" -C "$TOOLS" bin/micromamba
    elif command -v python3 >/dev/null 2>&1; then
        # No bzip2 (stock Ubuntu has none); Python can read the archive itself.
        python3 - "$archive" "$TOOLS" <<'PY'
import sys, tarfile
with tarfile.open(sys.argv[1], "r:bz2") as t:
    t.extract(t.getmember("bin/micromamba"), sys.argv[2])
PY
    else
        die "cannot unpack micromamba: install bzip2 or python3"
    fi
    rm -f "$archive"
    chmod +x "$MAMBA"
}

# mamba_env PREFIX PLATFORM PACKAGE...
mamba_env() {
    local prefix="$1" platform="$2"
    shift 2
    fetch_micromamba
    MAMBA_ROOT_PREFIX="$TOOLS/mamba" "$MAMBA" create --yes --quiet \
        --prefix "$prefix" --platform "$platform" -c conda-forge "$@" >/dev/null
}

# -- 1. recover the scripts (Python 3) ----------------------------------------
say "Recovering the game's scripts"
if [ -f "$HERE/gamecache/manifest.json" ]; then
    note "already done (player/gamecache exists; delete it to redo)"
else
    if [ ! -x "$SETUP_ENV/bin/python" ]; then
        rm -rf "$SETUP_ENV"
        if command -v python3 >/dev/null 2>&1 && python3 -m venv "$SETUP_ENV" >/dev/null 2>&1; then
            note "using $(command -v python3)"
        else
            rm -rf "$SETUP_ENV"
            note "no usable python3 venv here; getting Python 3 from conda-forge"
            mamba_env "$SETUP_ENV" "$HOST" "python=3.12" pip ||
                die "micromamba could not install Python 3"
        fi
    fi
    "$SETUP_ENV/bin/python" -m pip install --quiet --upgrade pip
    "$SETUP_ENV/bin/python" -m pip install --quiet "uncompyle6==$UNCOMPYLE6_VERSION"
    "$SETUP_ENV/bin/python" "$HERE/setup_game.py" "$GAME_DIR"
fi

# -- 2. the Python 2.7 runtime -------------------------------------------------
say "Python 2.7 runtime with pygame $PYGAME_VERSION (SDL2)"

find_python27() {
    if [ -n "${PYTHON27:-}" ]; then
        echo "$PYTHON27"; return
    fi
    local candidate
    for candidate in python2.7 python2; do
        if command -v "$candidate" >/dev/null 2>&1 &&
           "$candidate" -c 'import sys; sys.exit(sys.version_info[:2] != (2, 7))' 2>/dev/null; then
            command -v "$candidate"; return
        fi
    done
    return 0
}

if [ -x "$RUNTIME/bin/python" ] &&
   "$RUNTIME/bin/python" -c "import pygame; assert pygame.version.ver == '$PYGAME_VERSION'" >/dev/null 2>&1; then
    note "already done (player/.venv-sdl2)"
else
    rm -rf "$RUNTIME"
    PY27="$(find_python27)"
    if [ -n "$PY27" ]; then
        note "using $PY27"
        if ! "$PY27" -m virtualenv --version >/dev/null 2>&1; then
            "$PY27" -m pip install --user --quiet "virtualenv<20.22" ||
                die "could not install virtualenv for $PY27 -- or unset PYTHON27 to use conda-forge"
        fi
        "$PY27" -m virtualenv --quiet "$RUNTIME"
    else
        PLATFORM="$HOST"
        case "$HOST" in
            osx-arm64)
                # Python 2.7 only exists for Intel Macs: run that under Rosetta.
                PLATFORM=osx-64
                /usr/bin/arch -x86_64 /usr/bin/true 2>/dev/null ||
                    die "Python 2.7 needs Rosetta on Apple Silicon: softwareupdate --install-rosetta" ;;
        esac
        note "installing Python 2.7 ($PLATFORM) from conda-forge"
        mamba_env "$RUNTIME" "$PLATFORM" "python=2.7" pip ||
            die "micromamba could not install Python 2.7"
    fi
    "$RUNTIME/bin/python" -m pip install --quiet --disable-pip-version-check "pygame==$PYGAME_VERSION" ||
        die "pygame $PYGAME_VERSION did not install.  Prebuilt wheels exist for x86_64
       Linux and Intel macOS; elsewhere pip builds from source, which needs the
       SDL2 development packages (libsdl2-dev, libsdl2-image-dev,
       libsdl2-mixer-dev, libsdl2-ttf-dev on Debian/Ubuntu)."
fi

# -- 3. ffmpeg -----------------------------------------------------------------
say "ffmpeg (for dialogue and movies)"
if command -v ffmpeg >/dev/null 2>&1; then
    note "found $(command -v ffmpeg)"
elif [ -x "$HERE/ffmpeg" ]; then
    note "found player/ffmpeg"
else
    # The player looks for player/ffmpeg before giving up, so a private copy
    # linked there is enough.
    note "none on PATH; installing ffmpeg from conda-forge into player/.tools"
    if mamba_env "$TOOLS/ffmpeg" "$HOST" ffmpeg && [ -x "$TOOLS/ffmpeg/bin/ffmpeg" ]; then
        ln -sf "$TOOLS/ffmpeg/bin/ffmpeg" "$HERE/ffmpeg"
        note "linked player/ffmpeg"
    else
        note "could not install it -- the game runs, but dialogue and movies"
        note "will be silent/black.  Your package manager has it (apt, dnf,"
        note "pacman: ffmpeg; macOS: brew install ffmpeg)."
    fi
fi

# -- 4. check it runs ----------------------------------------------------------
say "Checking the player starts"
if "$RUNTIME/bin/python" "$HERE/run_game.py" --headless --scene bedroom \
        --skip-video --frames 30 >"$HERE/setup-check.log" 2>&1 &&
   grep -q "ran to completion" "$HERE/setup-check.log"; then
    note "ok: 30 frames in Sam's bedroom, headless"
    rm -f "$HERE/setup-check.log"
    # The check runs with a dummy sound driver, so ask SDL about the real
    # one: pygame's SDL loads the system's audio libraries at run time, and
    # minimal installs (WSL's Ubuntu, containers) have none.
    if ! "$RUNTIME/bin/python" -c "
import os, pygame
os.environ.pop('SDL_AUDIODRIVER', None)
pygame.mixer.init()" >/dev/null 2>&1; then
        say "No sound device"
        note "SDL could not open the audio -- the game will play silently."
        if [ "$OS" = Linux ]; then
            if command -v apt-get >/dev/null 2>&1; then
                note "install the audio libraries with:"
                note "    sudo apt install libasound2t64 libpulse0"
                note "(on older Debian/Ubuntu: libasound2 instead of libasound2t64)"
            elif command -v dnf >/dev/null 2>&1; then
                note "install them with:  sudo dnf install alsa-lib pulseaudio-libs"
            elif command -v pacman >/dev/null 2>&1; then
                note "install them with:  sudo pacman -S alsa-lib libpulse"
            else
                note "install ALSA and PulseAudio client libraries (libasound, libpulse)"
            fi
        fi
    fi
else
    note "the check run did not finish cleanly -- see player/setup-check.log"
    exit 1
fi

say "Ready.  Play with:  player/play.sh"
