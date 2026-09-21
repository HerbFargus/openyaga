#!/usr/bin/env bash
# Play the game on Linux or macOS, after player/setup.sh.
#
#     player/play.sh                       from the start
#     player/play.sh --fullscreen          any run_game.py flag works
#     player/play.sh --replay session.oyr --headless
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$HERE/.venv-sdl2/bin/python"
[ -x "$PYTHON" ] || { echo "run player/setup.sh first" >&2; exit 1; }
exec "$PYTHON" "$HERE/run_game.py" "$@"
