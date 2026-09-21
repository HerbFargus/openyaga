# -*- coding: latin-1 -*-
"""Stand-in for the native yagascene module.

Only Point is real so far.  It is the engine's position type and the game
builds it constantly -- 116 call sites -- in several shapes:

    yagascene.Point()            yagascene.Point(0, 0)
    yagascene.Point(x, y, z)     yagascene.Point(rect_or_pair, ...)

z is the sort key the sprite manager renders by, so it has to be a real
number rather than a stub, or the sort throws.
"""

import sys

import _stub

_mod = _stub.StubModule(__name__)


class Point(object):
    __slots__ = ("x", "y", "z")

    def __init__(self, x=0, y=0, z=0):
        # Some call sites pass a rect or a sequence as the first argument.
        if hasattr(x, "__len__") and not isinstance(x, basestring):
            seq = list(x)
            x = seq[0] if len(seq) > 0 else 0
            if len(seq) > 1 and y == 0:
                y = seq[1]
        self.x = x
        self.y = y
        self.z = z

    def __iter__(self):
        return iter((self.x, self.y, self.z))

    def __repr__(self):
        return "Point(%s, %s, %s)" % (self.x, self.y, self.z)


_mod.Point = Point

_mod.__wrapped_module__ = sys.modules[__name__]
sys.modules[__name__] = _mod
