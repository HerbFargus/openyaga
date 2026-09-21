# -*- coding: utf-8 -*-
"""Hand-written repairs for decompiler mistakes that cannot be fixed by rule.

The bulk of what uncompyle6 gets wrong in this game is mechanical and handled
by constfix.py: list literals holding constant-pool indices instead of the
constants themselves.

This file is for the rest.  Currently that is a single class of failure, seven
occurrences: a Python 2 list comprehension accumulates into a temporary named
`_[1]`, and where uncompyle6 cannot rebuild the comprehension it leaves that
name in place -- losing the element expression completely:

    xSum = reduce((lambda x, y: x + y), [_[1] for vector in vectors])

The loop and the condition survive; only the value being collected is gone, so
it cannot be inferred from the source.  Each replacement below was read out of
the original bytecode, where the element expression sits between
`LOAD_FAST _[1]` and the `CALL_FUNCTION` that appends it, e.g.

    41  LOAD_FAST      _[1]
    44  LOAD_FAST      vector
    47  LOAD_ATTR      x          -> vector.x
    50  CALL_FUNCTION  1

Worth noting the obvious reading was wrong: `vector[0]` looks natural for a
sum of x components, but the bytecode says attribute access.

Each patch is checked when applied.  If a pattern does not match exactly the
expected number of times, setup reports it rather than silently doing nothing,
since these are keyed to one build of one game.
"""

from __future__ import annotations

import re

PATCHES = [
    # Not a decompiler mistake: the bytecode really does build an empty list.
    # But every other use of preloadHandles is a dict -- has_key, item
    # assignment, .values() -- and PreloadForRoom itself resets it to {}.  The
    # list only survives until a room is entered the usual way, so the game
    # never trips over it; starting mid-game with --scene does, 21 times in a
    # single room.  A dict from the outset is what the rest of the file means.
    {
        "module": "pj_preload_manager",
        "why": "preloadHandles starts as a list but is used as a dict "
               "everywhere; harmless in normal play, fatal when a room is "
               "entered directly",
        "pattern": re.compile(r"self\.preloadHandles = \[\]"),
        "replacement": "self.preloadHandles = {}",
        "expect": 2,
    },
    # utility.AddVectors -- LOAD_ATTR x / y / z
    {
        "module": "python_shared/utility/utility",
        "why": "AddVectors lost `vector.x` from its comprehension",
        "pattern": re.compile(r"xSum = reduce\(\(lambda x, y: x \+ y\), "
                              r"\[_\[1\] for vector in vectors\]\)"),
        "replacement": "xSum = reduce((lambda x, y: x + y), "
                       "[vector.x for vector in vectors])",
        "expect": 1,
    },
    {
        "module": "python_shared/utility/utility",
        "why": "AddVectors lost `vector.y` from its comprehension",
        "pattern": re.compile(r"ySum = reduce\(\(lambda x, y: x \+ y\), "
                              r"\[_\[1\] for vector in vectors\]\)"),
        "replacement": "ySum = reduce((lambda x, y: x + y), "
                       "[vector.y for vector in vectors])",
        "expect": 1,
    },
    {
        "module": "python_shared/utility/utility",
        "why": "AddVectors lost `vector.z` from its comprehension",
        "pattern": re.compile(r"zSum = reduce\(\(lambda x, y: x \+ y\), "
                              r"\[_\[1\] for vector in vectors\]\)"),
        "replacement": "zSum = reduce((lambda x, y: x + y), "
                       "[vector.z for vector in vectors])",
        "expect": 1,
    },
    # utility.unzip -- LOAD_GLOBAL None, BUILD_LIST 1, LOAD_FAST mlen,
    # BINARY_MULTIPLY  ->  [None] * mlen
    {
        "module": "python_shared/utility/utility",
        "why": "unzip lost `[None] * mlen` from its comprehension",
        "pattern": re.compile(r"newlist = \[_\[1\] for i in range\(tupleSize\)\]"),
        "replacement": "newlist = [[None] * mlen for i in range(tupleSize)]",
        "expect": 1,
    },
    # xml_loader_classes.CClickpointTag.Build -- LOAD_FAST x, LOAD_ATTR sound
    {
        "module": "python_shared/adventure/xml_loader_classes",
        "why": "clickpoint Build lost `x.sound` from its comprehension",
        "pattern": re.compile(r"soundsList = \[_\[1\] for x in self\.soundTags\]"),
        "replacement": "soundsList = [x.sound for x in self.soundTags]",
        "expect": 1,
    },
    # getopt.long_has_args -- LOAD_FAST o
    {
        "module": "getopt",
        "why": "long_has_args lost `o` from its comprehension",
        "pattern": re.compile(r"possibilities = \[_\[1\] for o in longopts "
                              r"if o\.startswith\(opt\)\]"),
        "replacement": "possibilities = [o for o in longopts "
                       "if o.startswith(opt)]",
        "expect": 1,
    },
    # os._get_exports_list -- LOAD_FAST n
    {
        "module": "os",
        "why": "_get_exports_list lost `n` from its comprehension",
        "pattern": re.compile(r"return \[_\[1\] for n in dir\(module\) "
                              r"if n\[0\] != '_'\]"),
        "replacement": "return [n for n in dir(module) if n[0] != '_']",
        "expect": 1,
    },
]


def patches_for(module):
    """Every patch registered against a module path like 'statusOf'."""
    return [p for p in PATCHES if p["module"] == module]


def apply(module, text):
    """Returns (text, applied, problems) for one recovered module."""
    applied, problems = [], []
    for patch in patches_for(module):
        found = len(patch["pattern"].findall(text))
        if found != patch["expect"]:
            problems.append("%s: matched %d times, expected %d -- %s"
                            % (module, found, patch["expect"], patch["why"]))
            continue
        text = patch["pattern"].sub(patch["replacement"].replace("\\", "\\\\"), text)
        applied.append("%s: %s" % (module, patch["why"]))
    return text, applied, problems
