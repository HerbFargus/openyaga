# -*- coding: latin-1 -*-
"""Stand-in for the native yagasprite module.

A sprite is an animation plus a position and some playback state.  The game
reads and writes these, in rough order of how often:

    position (x, y, z)   anim        renderRect    talkies
    currentFrame         frameCount  loopCount     hFlip / vFlip
    Run() / Stop()       SetLayerFlag()            Intersect()

`position.z` is the render sort key, so it must be a real number.

Sprites must be truthy -- cursor.py does `assert __debug__ and self.sprite`
straight after creating one, which a plain falsy stub fails.

Nothing draws yet: Render() records the call so the render order shows up in
the trace.
"""

import sys

import _stub

_mod = _stub.StubModule(__name__)


class ISprite(_stub.Stub):
    """Base class; the game subclasses this for its own sprite types."""

    def __init__(self, name="yagasprite.ISprite"):
        _stub.Stub.__init__(self, name)
        import yagascene
        self.position = yagascene.Point(0, 0, 0)
        self.anim = None
        self.renderRect = None
        self.currentFrame = 0
        self.frameCount = 0
        self.loopCount = 0
        self.hFlip = 0
        self.vFlip = 0
        self.visible = 1
        # Not a list: the game sets attributes on it, e.g.
        # `sprite.talkies.continuous = true`.
        self.talkies = _stub.Stub("%s.talkies" % name)

    def Run(self, *a, **kw):
        _stub.LOG.record("call", "%s.Run" % self._yaga_name, _stub._args(a, kw))

    def Stop(self, *a, **kw):
        _stub.LOG.record("call", "%s.Stop" % self._yaga_name, _stub._args(a, kw))

    def SetLayerFlag(self, *a, **kw):
        _stub.LOG.record("call", "%s.SetLayerFlag" % self._yaga_name, _stub._args(a, kw))

    def SetVolume(self, *a, **kw):
        pass

    def Intersect(self, *a, **kw):
        return 0

    def Render(self, camera=None):
        anim = self.anim
        locator = getattr(anim, "locator", "?") if anim is not None else "none"
        _stub.LOG.record("call", "%s.Render" % self._yaga_name,
                         "(%s at %s)" % (locator, self.position))

    def __nonzero__(self):
        return True


class Sprite(ISprite):
    def __init__(self):
        ISprite.__init__(self, "yagasprite.Sprite")
        _stub.LOG.record("new", "yagasprite.Sprite", "()")


class TalkieSprite(ISprite):
    def __init__(self):
        ISprite.__init__(self, "yagasprite.TalkieSprite")
        _stub.LOG.record("new", "yagasprite.TalkieSprite", "()")


_mod.ISprite = ISprite
_mod.Sprite = Sprite
_mod.TalkieSprite = TalkieSprite

_mod.__wrapped_module__ = sys.modules[__name__]
sys.modules[__name__] = _mod
