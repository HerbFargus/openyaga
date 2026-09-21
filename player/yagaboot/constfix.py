# -*- coding: utf-8 -*-
"""Repair list literals that the decompiler filled with constant-pool indices.

uncompyle6 sometimes loses a list of string constants and emits the *indices*
into `co_consts` instead of the strings themselves:

    statusOf.InitializeTradingCards   [1, 2, ... 24]    co_consts[1..24]
    scene_trading_cards  (module)     [7, 8, ... 30]    co_consts[7..30]

both of which really hold 'trading_card1' ... 'trading_card24'.  The giveaway
is that the integers are consecutive and, read as indices into some code
object's constant pool, land exactly on a run of strings.

The output is valid Python, so nothing downstream notices -- statusOf raised
`TypeError: int + str` and scene_trading_cards raised `KeyError: 7`, both far
from the cause.  verify_decompile.py catches this class by comparing string
constants; this fixes it.

A substitution is only made when the run resolves unambiguously: every index
must be in range and map to a string, in exactly one code object of the module.
Anything else is left alone and reported.
"""

from __future__ import annotations

import re

# A list of at least four consecutive integers, possibly wrapped across lines.
_INT_LIST = re.compile(r"\[\s*(\d+(?:\s*,\s*\d+){3,})\s*,?\s*\]", re.S)


def _code_objects(code):
    yield code
    for const in code.co_consts:
        if hasattr(const, "co_consts"):
            for inner in _code_objects(const):
                yield inner


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
        elif not isinstance(value, str):
            return None
        out.append(value)
    return out


def repair(source: str, code) -> tuple:
    """Returns (source, fixes) where fixes describes each substitution made."""
    objects = list(_code_objects(code))
    fixes = []

    def substitute(match):
        indices = [int(n) for n in re.split(r"\s*,\s*", match.group(1).strip())]
        if indices != list(range(indices[0], indices[0] + len(indices))):
            return match.group(0)          # not a consecutive run

        candidates = []
        for obj in objects:
            resolved = _resolve(indices, obj)
            if resolved:
                candidates.append(resolved)
        # Ambiguous or unresolvable: leave it be rather than guess.
        unique = set(tuple(c) for c in candidates)
        if len(unique) != 1:
            return match.group(0)

        strings = candidates[0]
        fixes.append("[%d..%d] -> %s ... %s (%d strings)"
                     % (indices[0], indices[-1], strings[0], strings[-1], len(strings)))
        return "[" + ", ".join("'%s'" % s.replace("'", "\\'") for s in strings) + "]"

    return _INT_LIST.sub(substitute, source), fixes
