# -*- coding: utf-8 -*-
"""Repair list literals that the decompiler filled with constant-pool indices.

uncompyle6 sometimes loses a list of string constants and emits the *indices*
into `co_consts` instead of the strings themselves:

    statusOf.InitializeTradingCards   [1, 2, ... 24]     co_consts[1..24]
    scene_trading_cards  (module)     [7, 8, ... 30]     co_consts[7..30]
    scene_dust_bunny.DisplayBunnies   [1, 2, ... 12]     'Bunny1' ... 'Bunny12'
    scene_leavins  (module)           [6, 7, ... 15]     'FOUR_LEFT' ...

The output is valid Python, so nothing downstream notices -- statusOf raised
`TypeError: int + str`, scene_trading_cards raised `KeyError: 7`, both a long
way from the cause.  verify_decompile.py detects this class by comparing string
constants against the bytecode; this repairs it.

Indices are resolved against the constant pool of the *enclosing* function,
found by tracking `class`/`def` nesting in the source the same way the code
objects nest.  Resolving against "whichever code object happens to fit" is not
good enough: small indices fit many pools at once, and the ambiguity made an
earlier version skip most real cases.
"""

from __future__ import annotations

import re

# A list of at least four integers, possibly wrapped across lines.
_INT_LIST = re.compile(r"\[\s*(\d+(?:\s*,\s*\d+){3,})\s*,?\s*\]", re.S)
_DEF = re.compile(r"^(\s*)(?:class|def)\s+([A-Za-z_]\w*)")


def _code_by_path(code, path="", out=None):
    """{'/Class/method': code object} for every code object in a module."""
    if out is None:
        out = {}
    out[path] = code
    for const in code.co_consts:
        if hasattr(const, "co_consts"):
            _code_by_path(const, path + "/" + const.co_name, out)
    return out


def _paths_by_offset(source):
    """Character offset -> enclosing '/Class/method' path, from the source."""
    marks, stack, offset = [], [], 0
    for line in source.splitlines(True):
        m = _DEF.match(line)
        if m:
            indent = len(m.group(1).expandtabs())
            while stack and stack[-1][0] >= indent:
                stack.pop()
            stack.append((indent, m.group(2)))
        elif line.strip():
            # A line no deeper than a def has left that def's body -- back
            # to the enclosing function after a nested def, or to module
            # level.
            indent = len(line.expandtabs()) - len(line.expandtabs().lstrip())
            while stack and stack[-1][0] >= indent:
                stack.pop()
        marks.append((offset, "/" + "/".join(n for _i, n in stack) if stack else ""))
        offset += len(line)
    return marks


def _path_at(marks, offset):
    found = ""
    for start, path in marks:
        if start > offset:
            break
        found = path
    return found


def _resolve(indices, code):
    """The strings at those constant indices, or None if they do not all fit."""
    consts = code.co_consts
    out = []
    for i in indices:
        if i >= len(consts):
            return None
        value = consts[i]
        if isinstance(value, (bytes, bytearray)):
            value = bytes(value).decode("latin-1")
        if not isinstance(value, str):
            return None
        out.append(value)
    return out


def repair(source: str, code) -> tuple:
    """Returns (source, fixes) where fixes describes each substitution made."""
    by_path = _code_by_path(code)
    marks = _paths_by_offset(source)
    fixes = []

    def substitute(match):
        indices = [int(n) for n in re.split(r"\s*,\s*", match.group(1).strip())]
        path = _path_at(marks, match.start())

        # The enclosing scope first, then the module: a list can sit in a class
        # body whose constants live one level up.
        for candidate in (path, ""):
            target = by_path.get(candidate)
            if target is None:
                continue
            strings = _resolve(indices, target)
            if not strings:
                continue
            # A real list of small integers would resolve too, so require that
            # the strings look like data the game would name things with.
            if any(not s or len(s) > 64 or "\n" in s for s in strings):
                continue
            fixes.append("%s [%d..%d] -> %s ... %s (%d)"
                         % (candidate or "<module>", indices[0], indices[-1],
                            strings[0], strings[-1], len(strings)))
            return "[" + ", ".join("'%s'" % s.replace("'", "\\'") for s in strings) + "]"
        return match.group(0)

    return _INT_LIST.sub(substitute, source), fixes
