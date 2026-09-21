#!/usr/bin/env python
"""Compare two trace logs call by call, and show where they part company.

    python compare_traces.py recorded.log replayed.log

Meant for replays (run_game.py --replay): a replay of a session makes the
same engine calls as the session did, so its trace should match the
recording's line for line -- and a second engine replaying the same file
should match too, as far as it implements the same calls.

A few things differ between runs without meaning anything, and are masked
before comparing: memory addresses (`0x...`), Python object ids, and the
names of temporary files.  Lines that only say how the run was driven --
"recording to", "replaying", and the test.click/test.key/test.hover lines of
scripted input, whose effect is recorded anyway -- are dropped, as are "const"
lines (when the shim first defined a constant) and
the summary at the end of a trace.

Exits 0 if the traces match, 1 with the first difference if not.  Runs under
Python 2.7 or 3.
"""

import re
import sys

_MASKS = [
    (re.compile(r"^\d+(\s)"), r"\1"),      # sequence numbers shift with dropped lines
    (re.compile(r"\b0x[0-9A-Fa-f]+"), "0x?"),   # \b: not the 0x480 in 640x480
    (re.compile(r"@ [0-9A-Fa-f]{8,}\b"), "@ ?"),  # ffmpeg's pointers, no 0x
    (re.compile(r"(_anim_id\s+=\s+)\d+L?"), r"\1?"),
    (re.compile(r"yaga_[A-Za-z0-9_]+\.(mp3|wav)"), r"yaga_?.\1"),
    (re.compile(r"trace-\d+\.log"), "trace-?.log"),
    # The game runs its file names through os.path.normpath, which spells
    # them with the host's separator: interface\\cursors on Windows,
    # interface/cursors elsewhere.  Same file either way.
    (re.compile(r"\\\\|\\"), "/"),
    # ffmpeg's own wording of why a movie has no soundtrack varies by build
    (re.compile(r"(\) no audio): .*"), r"\1"),
    # how the window is shown is the viewer's choice, not the game's
    (re.compile(r"(window \d+x\d+, )?(windowed|fullscreen), (fit|integer) scaling, (sharp|smooth)"),
     "display ?"),
]
_DRIVING = re.compile(r"^\s*(recording to |replaying |.*replay finished after |"
                      r"\d+\s+call\s+test\.(click|key|hover)|"
                      # the first use of an undeclared constant: when the shim
                      # happened to define it, not a call the game made
                      r"\d+\s+const\s|"
                      # where ffmpeg was found: logged on first need, which a
                      # warm decode cache moves
                      r"\d+\s+call\s+yagasound\.ffmpeg\s)")


def calls(path):
    """The trace's call lines, masked, without the closing summary."""
    out = []
    with open(path) as fh:
        for line in fh:
            if line.startswith("most requested") or line.startswith("full trace"):
                break
            line = line.rstrip("\n")
            if _DRIVING.match(line):
                continue
            for pattern, repl in _MASKS:
                line = pattern.sub(repl, line)
            out.append(line)
    return out


def main(argv):
    if len(argv) != 3:
        sys.stderr.write(__doc__)
        return 2
    a, b = calls(argv[1]), calls(argv[2])
    for n, (x, y) in enumerate(zip(a, b)):
        if x != y:
            print("traces differ at line %d:" % (n + 1))
            for m in range(max(0, n - 4), n):
                print("    %s" % a[m])
            print("  - %s" % x)
            print("  + %s" % y)
            return 1
    if len(a) != len(b):
        longer = argv[1] if len(a) > len(b) else argv[2]
        print("traces match for %d lines, then %s goes on for %d more"
              % (min(len(a), len(b)), longer, abs(len(a) - len(b))))
        return 1
    print("traces match: %d lines" % len(a))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
