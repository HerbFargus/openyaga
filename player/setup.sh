#!/usr/bin/env bash
# One-time setup for Linux and macOS.
#
#     player/setup.sh "/path/to/Pajama Sam LRS"
#
# The folder is your installed copy of the game: the one holding
# PajamaLRS.exe and its data (from a Windows install, or a Wine prefix such as
# ~/.wine/drive_c/Program Files (x86)/Atari/Pajama Sam LRS).
#
# It sets up two things, both inside player/ -- nothing is installed system
# wide and nothing needs sudo:
#
#   .venv-setup   Python 3 + uncompyle6, to recover the game's scripts once
#   .venv-sdl2    Python 2.7 + pygame 2 (SDL2), the runtime the game needs
#
# Python 2.7: a python2.7 already on PATH (or named by $PYTHON27) is used if
# there is one.  Otherwise micromamba -- a single-file conda installer -- is
# fetched into player/.tools and installs a prebuilt Python 2.7 from
# conda-forge.  On Apple Silicon that Python is x86_64 and runs under Rosetta,
# since no arm64 build of Python 2.7 or its pygame exists.
#
# ffmpeg (dialogue and movies) comes from your package manager; the script
# says how if it is missing.
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
case "$OS" in
    Linux|Darwin) ;;
    *) die "this script is for Linux and macOS; on Windows follow player/README.md" ;;
esac

# -- 1. recover the scripts (Python 3) ----------------------------------------
say "Recovering the game's scripts"
command -v python3 >/dev/null || die "python3 not found -- install it from your package manager"
if [ -f "$HERE/gamecache/manifest.json" ]; then
    note "already done (player/gamecache exists; delete it to redo)"
else
    if [ ! -x "$SETUP_ENV/bin/python" ]; then
        python3 -m venv "$SETUP_ENV" || die "python3 -m venv failed -- on Debian/Ubuntu: sudo apt install python3-venv"
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
    for candidate in python2.7 python2; do
        if command -v "$candidate" >/dev/null 2>&1 &&
           "$candidate" -c 'import sys; sys.exit(sys.version_info[:2] != (2, 7))' 2>/dev/null; then
            command -v "$candidate"; return
        fi
    done
}

micromamba_platform() {
    case "$OS/$ARCH" in
        Linux/x86_64)          echo linux-64 ;;
        Linux/aarch64|Linux/arm64) echo linux-aarch64 ;;
        Darwin/x86_64)         echo osx-64 ;;
        Darwin/arm64)          echo osx-64 ;;     # Python 2.7 only exists for Intel: Rosetta
        *) die "no prebuilt Python 2.7 for $OS/$ARCH; install python2.7 yourself and set PYTHON27" ;;
    esac
}

fetch_micromamba() {
    local host
    case "$OS/$ARCH" in
        Linux/x86_64) host=linux-64 ;;
        Linux/aarch64|Linux/arm64) host=linux-aarch64 ;;
        Darwin/x86_64) host=osx-64 ;;
        Darwin/arm64) host=osx-arm64 ;;
    esac
    if [ ! -x "$TOOLS/bin/micromamba" ]; then
        command -v curl >/dev/null || die "curl not found"
        mkdir -p "$TOOLS"
        note "fetching micromamba ($host) into player/.tools"
        curl -fsSL "https://micro.mamba.pm/api/micromamba/$host/latest" |
            tar -xj -C "$TOOLS" bin/micromamba ||
            die "could not download micromamba"
    fi
}

if [ -x "$RUNTIME/bin/python" ] &&
   "$RUNTIME/bin/python" -c "import pygame; assert pygame.version.ver == '$PYGAME_VERSION'" >/dev/null 2>&1; then
    note "already done (player/.venv-sdl2)"
else
    rm -rf "$RUNTIME"
    PY27="$(find_python27 || true)"
    if [ -n "$PY27" ]; then
        note "using $PY27"
        if ! "$PY27" -m virtualenv --version >/dev/null 2>&1; then
            "$PY27" -m pip install --user --quiet "virtualenv<20.22" ||
                die "could not install virtualenv for $PY27 -- or unset PYTHON27 to use micromamba"
        fi
        "$PY27" -m virtualenv --quiet "$RUNTIME"
    else
        PLATFORM="$(micromamba_platform)"
        if [ "$OS/$ARCH" = "Darwin/arm64" ]; then
            /usr/bin/arch -x86_64 /usr/bin/true 2>/dev/null ||
                die "Python 2.7 needs Rosetta on Apple Silicon: softwareupdate --install-rosetta"
        fi
        fetch_micromamba
        note "installing Python 2.7 ($PLATFORM) from conda-forge"
        MAMBA_ROOT_PREFIX="$TOOLS/mamba" "$TOOLS/bin/micromamba" create --yes --quiet \
            --prefix "$RUNTIME" --platform "$PLATFORM" -c conda-forge "python=2.7" pip ||
            die "micromamba could not install Python 2.7"
    fi
    "$RUNTIME/bin/python" -m pip install --quiet "pygame==$PYGAME_VERSION" ||
        die "pygame $PYGAME_VERSION did not install.  Prebuilt wheels exist for x86_64
       Linux and Intel macOS; elsewhere pip builds from source, which needs the
       SDL2 development packages (libsdl2-dev, libsdl2-image-dev,
       libsdl2-mixer-dev, libsdl2-ttf-dev on Debian/Ubuntu)."
fi

# -- 3. ffmpeg -----------------------------------------------------------------
say "ffmpeg (for dialogue and movies)"
if command -v ffmpeg >/dev/null 2>&1; then
    note "found $(command -v ffmpeg)"
else
    note "not found -- the game runs, but dialogue and movies will be silent/black."
    if [ "$OS" = Darwin ]; then
        note "install it with:  brew install ffmpeg"
    elif command -v apt-get >/dev/null 2>&1; then
        note "install it with:  sudo apt install ffmpeg"
    elif command -v dnf >/dev/null 2>&1; then
        note "install it with:  sudo dnf install ffmpeg   (Fedora: from RPM Fusion)"
    elif command -v pacman >/dev/null 2>&1; then
        note "install it with:  sudo pacman -S ffmpeg"
    else
        note "install ffmpeg from your package manager"
    fi
fi

# -- 4. check it runs ----------------------------------------------------------
say "Checking the player starts"
if "$RUNTIME/bin/python" "$HERE/run_game.py" --headless --scene bedroom \
        --skip-video --frames 30 >"$HERE/setup-check.log" 2>&1 &&
   grep -q "ran to completion" "$HERE/setup-check.log"; then
    note "ok: 30 frames in Sam's bedroom, headless"
    rm -f "$HERE/setup-check.log"
else
    note "the check run did not finish cleanly -- see player/setup-check.log"
    exit 1
fi

say "Ready.  Play with:  player/play.sh"
