# -*- coding: utf-8 -*-
"""Repairs for places where the decompiler produced wrong data.

uncompyle6 gets the *structure* of this game right almost everywhere, but it
can substitute constants -- emitting a list of integers where the bytecode
holds a list of strings.  The result is valid Python that runs and misbehaves,
so nothing but a comparison against the original bytecode will find it.
`verify_decompile.py` is that comparison; this is where its findings get fixed.

Each patch is checked when applied: if the pattern does not match exactly the
expected number of times, setup says so rather than silently doing nothing.
That matters because these are keyed to one build of one game, and a different
release will not match.

Replacement values are taken from `co_consts` in the original .pyc, in order.
"""

from __future__ import annotations

import re

# statusOf.SetTradingCards, from the bytecode: the 24 card asset names, in the
# order the list literal declares them.  `val + 'CU'` then yields e.g.
# 'pajamaManCU', which is the close-up art (pajamamancu.mng).
CARD_NAMES = [
    "fizzyPoppins", "evilUnderwear", "royalJelly", "admiralPeanutButter",
    "cardboardWoman", "seriousBowler", "Pajamaputer", "remoteRemover",
    "pajamamobile", "portableBadGuyContainer", "illuminatorMarkV", "darkness",
    "drGrime", "malevolentMilkMolecules", "drScottBruvvers", "dustDevil",
    "earthquake", "thunder", "lightning", "captainGelatin", "heroSandwich",
    "clementine", "milkman", "pajamaMan",
]

# statusOf.InitializeTradingCards: the dictionary keys, likewise from consts.
CARD_KEYS = ["trading_card%d" % i for i in range(1, 25)]


def _as_list(values):
    return "[" + ", ".join("'%s'" % v for v in values) + "]"


PATCHES = [
    {
        "module": "statusOf",
        "why": "card dictionary keys decompiled as integers instead of "
               "'trading_card1'...'trading_card24'",
        "pattern": re.compile(r"\btradingCards = \[1, 2, 3,.*?24\]", re.S),
        "replacement": "tradingCards = " + _as_list(CARD_KEYS),
        "expect": 1,
    },
    {
        "module": "statusOf",
        "why": "card asset names decompiled as integers, which made "
               "`val + 'CU'` raise TypeError instead of building 'pajamaManCU'",
        "pattern": re.compile(r"\bself\.randomCardList = \[1, 2, 3,.*?24\]", re.S),
        "replacement": "self.randomCardList = " + _as_list(CARD_NAMES),
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
