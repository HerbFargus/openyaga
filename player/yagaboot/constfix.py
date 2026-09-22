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


# -- lists the bytecode can vouch for -----------------------------------------
#
# The rule above needs a run of four or more indices that all resolve to
# strings.  Putt-Putt has the same fault in a shape that rule cannot see: a
# table of rows mixing names with constants, some of them ints --
#
#     c_visorButtons = [[None, CVisorButtons, 1, 2, 3, 4], ...]
#
# where the bytecode loads 'interface/visor/bg_visor.mng', 5000,
# 'interface_visor', 0 -- constants 1 to 4.  Here the bytecode decides, not a
# guess: every list the code object builds is rebuilt from its LOAD_CONST /
# LOAD_NAME / BUILD_LIST sequence, and a source list is replaced only if it
# has the same length, the same names in the same places, and at each number
# the *index* of the constant the bytecode loads there -- with at least one
# index that differs from its value, or there is nothing to fix.

_FLAT_LIST = re.compile(r"\[([^\[\]]*)\]")
_ELEMENT = re.compile(r"^(?:-?\d+|[A-Za-z_]\w*)$")


def _built_lists(code):
    """Every list a code object builds from plain loads: a list of items,
    each ('c', index, value) or ('n', name)."""
    from .lostelse import _instructions
    lists, stack = [], []
    for ins in _instructions(code):
        op = ins.opname
        if op == "LOAD_CONST":
            stack.append(("c", ins.arg, ins.argval))
        elif op in ("LOAD_NAME", "LOAD_GLOBAL", "LOAD_FAST"):
            stack.append(("n", ins.argval))
        elif op == "BUILD_LIST" and ins.arg is not None and len(stack) >= ins.arg:
            items = stack[len(stack) - ins.arg:] if ins.arg else []
            del stack[len(stack) - ins.arg:]
            if all(item[0] in ("c", "n") for item in items):
                lists.append(items)
            stack.append(("l",))
        elif op == "SET_LINENO":
            continue
        else:
            stack = []
    return lists


def _matches(elements, items):
    """The corrected elements if the source list is this bytecode list with
    constant indices for constants, else None."""
    if len(elements) != len(items):
        return None
    out, differs = [], False
    for text, item in zip(elements, items):
        if item[0] == "n":
            if text != item[1]:
                return None
            out.append(text)
            continue
        _kind, index, value = item
        if text == "None" and value is None:
            out.append(text)
            continue
        if not re.match(r"^-?\d+$", text) or int(text) != index:
            return None
        if isinstance(value, (bytes, bytearray)):
            value = bytes(value).decode("latin-1")
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            return None
        literal = repr(value)
        differs = differs or literal != text
        out.append(literal)
    return out if differs else None


def repair_tables(source: str, code) -> tuple:
    """Returns (source, fixes) for index-filled lists the bytecode proves."""
    by_path = _code_by_path(code)
    built = {}
    fixes = []

    def lists_for(path):
        if path not in built:
            target = by_path.get(path)
            built[path] = _built_lists(target) if target is not None else []
        return built[path]

    marks = _paths_by_offset(source)

    def substitute(match):
        elements = [e.strip() for e in match.group(1).split(",") if e.strip()]
        if not elements or not all(_ELEMENT.match(e) for e in elements):
            return match.group(0)
        if not any(re.match(r"^-?\d+$", e) for e in elements):
            return match.group(0)
        path = _path_at(marks, match.start())
        candidates = []
        while True:
            candidates.append(path)
            if not path:
                break
            path = path.rsplit("/", 1)[0]
        for candidate in candidates:
            found = set()
            for items in lists_for(candidate):
                fixed = _matches(elements, items)
                if fixed:
                    found.add(tuple(fixed))
            if len(found) == 1:
                fixed = list(found.pop())
                fixes.append("%s [%s] -> [%s]" % (candidate or "<module>",
                                                  ", ".join(elements)[:40],
                                                  ", ".join(fixed)[:60]))
                return "[" + ", ".join(fixed) + "]"
            if found:
                return match.group(0)     # ambiguous: leave it
        return match.group(0)

    return _FLAT_LIST.sub(substitute, source), fixes
