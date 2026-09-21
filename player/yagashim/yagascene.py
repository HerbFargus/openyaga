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


class _ConstMeta(type):
    """Named constants, invented on demand and cached so `==` stays stable."""

    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        value = "%s.%s" % (cls.__name__, name)
        type.__setattr__(cls, name, value)
        _stub.LOG.record("const", "yagascene.%s" % value)
        return value


class SceneEvents(object):
    """What a sprite reports as it plays.  SCENE_STOP is load-bearing: a
    character's exit animation ends, the sink fires, and samCharacter then
    calls QueueNextScene -- which is how the game changes rooms."""

    __metaclass__ = _ConstMeta
    SCENE_RUN = "SceneEvents.SCENE_RUN"
    SCENE_STOP = "SceneEvents.SCENE_STOP"


class ISceneEventSink(_stub.Stub):
    """Base class for the game's sprite callbacks; see character.CSpriteCallback,
    whose Event(eventType, sprite) forwards to the character."""

    def __init__(self):
        _stub.Stub.__init__(self, "yagascene.ISceneEventSink()")

    def Event(self, eventType, sprite):
        pass

    def __nonzero__(self):
        return True


class Rect(object):
    """What sprite.renderRect is: utility.OverSprite reads .x/.y/.width/.height."""

    def __init__(self, x=0, y=0, width=0, height=0):
        self.x, self.y = x, y
        self.width, self.height = width, height

    def __repr__(self):
        return "Rect(%s, %s, %sx%s)" % (self.x, self.y, self.width, self.height)


def copy_point(value):
    """A Point is a value in the engine: assigning one copies it.

    enter_text relies on that.  It hands the name's Point to the typing
    cursor and then moves the cursor by editing the Point it reads back:

        self.__textCursor.position = pos          # pos is the text's Point
        ...
        pos = self.__textCursor.position
        pos.x = textStringPos.x + (textStringWidth + 1) / 2

    With one shared object the name slid right by half its width on every
    keystroke.  Anything without x and y is passed through untouched.
    """
    if isinstance(value, Point):
        return Point(value.x, value.y, value.z)
    return value


class PointCollider(object):
    """Created by the scene for hit tests: spriteScene.CreatePointCollider."""

    def __init__(self, x=0, y=0, z=0):
        self.x, self.y, self.z = x, y, z


class Scene(_stub.Stub):
    def __init__(self):
        _stub.Stub.__init__(self, "yagascene.Scene")

    def CreatePointCollider(self, x=0, y=0, z=0):
        return PointCollider(x, y, z)

    def __nonzero__(self):
        return True


class SceneManager(_stub.Stub):
    """Only CreateScene is real; everything else still auto-stubs."""

    def __init__(self):
        _stub.Stub.__init__(self, "yagascene.SceneManager()")

    def CreateScene(self, *a, **kw):
        return Scene()

    def __nonzero__(self):
        return True


_manager = None


def SceneManagerFactory():
    global _manager
    if _manager is None:
        _manager = SceneManager()
    return _manager


_mod.SceneEvents = SceneEvents
_mod.ISceneEventSink = ISceneEventSink
_mod.Point = Point
_mod.copy_point = copy_point
_mod.Rect = Rect
_mod.PointCollider = PointCollider
_mod.Scene = Scene
_mod.SceneManager = SceneManagerFactory

_mod.__wrapped_module__ = sys.modules[__name__]
sys.modules[__name__] = _mod
