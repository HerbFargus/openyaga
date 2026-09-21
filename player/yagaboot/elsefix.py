# -*- coding: utf-8 -*-
"""Remove `else:` clauses the decompiler invented after `except:`.

uncompyle6 sometimes turns

    try:
        lineCount = str(globals.HeDbg.GetLineCount()) + ' - '
    except:
        pass
    <the rest of the function>

into

    try:
        ...
    except:
        pass
    else:
        <the rest of the function>

which is catastrophic when the try is expected to fail.  In main.py the entire
game loop -- including `globals.g_InputManager.DispatchInput()` -- ended up in
that else, and `HeDbg` is a debug module the retail build does not ship, so the
try always raised, the except always fired, and the loop body never ran once.

The bytecode tells the two apart.  Without an `else`, both paths converge:

    100  SETUP_EXCEPT   to 135
    131  POP_BLOCK
    132  JUMP_FORWARD   to 148      <- normal path
    135  (handler)
    144  JUMP_FORWARD   to 148      <- handler, same target

With a real `else`, the handler jumps past the else body instead, so the two
targets differ.  A de-indent is only applied where the enclosing function
contains a convergent structure like the one above.
"""

from __future__ import annotations

import re

from .constfix import _code_by_path, _paths_by_offset, _path_at

# `except ...:` / `pass` / `else:` at the same indent.
_EXCEPT_ELSE = re.compile(
    r"^(?P<indent>[ \t]*)except[^\n]*:[ \t]*\n"
    r"(?P=indent)[ \t]+pass[ \t]*\n"
    r"(?P=indent)else:[ \t]*\n", re.M)


def _convergent_excepts(code):
    """How many try/except structures in this code object have no else.

    Needs xdis, which arrives with uncompyle6; without it, report none and
    leave the source alone.
    """
    try:
        from xdis.bytecode import Bytecode
        from xdis.op_imports import get_opcode_module
    except ImportError:
        return 0

    try:
        insts = list(Bytecode(code, get_opcode_module(2.2)))
    except Exception:
        return 0

    count = 0
    for i, inst in enumerate(insts):
        if inst.opname != "SETUP_EXCEPT":
            continue
        handler = inst.argval
        # The jump that leaves the try body normally.
        normal = None
        for j in range(i + 1, len(insts)):
            if insts[j].offset >= handler:
                break
            if insts[j].opname == "JUMP_FORWARD":
                normal = insts[j].argval
        # The jump that leaves the handler.
        from_handler = None
        for j in range(len(insts)):
            if insts[j].offset >= handler and insts[j].opname == "JUMP_FORWARD":
                from_handler = insts[j].argval
                break
        if normal is not None and normal == from_handler:
            count += 1
    return count


def repair(source: str, code) -> tuple:
    """Returns (source, fixes).  Only de-indents where the bytecode agrees."""
    by_path = _code_by_path(code)
    fixes = []

    while True:
        marks = _paths_by_offset(source)
        for match in _EXCEPT_ELSE.finditer(source):
            path = _path_at(marks, match.start())
            target = by_path.get(path) or by_path.get("")
            if target is None or not _convergent_excepts(target):
                continue

            indent = match.group("indent")
            head = source[:match.start()]
            # Keep the try/except, drop the `else:` line.
            kept = match.group(0)[:match.group(0).rindex(indent + "else:")]
            rest = source[match.end():]

            body, tail, lines = [], None, rest.splitlines(True)
            for n, line in enumerate(lines):
                if line.strip() and not line.startswith(indent + " "):
                    tail = "".join(lines[n:])
                    break
                body.append(line[4:] if line.startswith(indent + "    ") else line)
            else:
                tail = ""

            source = head + kept + "".join(body) + tail
            fixes.append("%s: dropped an invented `else:` after `except:`"
                         % (path or "<module>"))
            break
        else:
            return source, fixes
