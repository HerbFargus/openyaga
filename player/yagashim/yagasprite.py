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

import pygame

import _stub

# Only the rest pose is drawn; see Render() below.
PHONEME_REST = 0x1

_surfaces = {}


def _surface_for(layer):
    """Cache a pygame Surface per decoded layer.

    frombuffer does not copy, so the RGBA bytes must outlive the Surface --
    convert_alpha() takes its own copy and matches the display format, which
    also makes the blit fast.
    """
    key = id(layer)
    surface = _surfaces.get(key)
    if surface is None:
        raw = bytes(bytearray(layer.rgba))
        surface = pygame.image.frombuffer(raw, (layer.w, layer.h), "RGBA")
        try:
            surface = surface.convert_alpha()
        except pygame.error:
            surface = surface.copy()
        _surfaces[key] = surface
    return surface

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
        """Blit the current frame's layers onto the render target.

        Layer coordinates are absolute positions on the 640x480 screen (the
        MNG DEFI chunk carries them), and the sprite's own position offsets
        them.  Masked layers are lipsync alternatives: drawing all of them
        stacks every mouth shape at once, so only the rest pose (bit 0) is
        drawn -- and note those masked layers include the character's head,
        not just the mouth.  See ../../FORMATS.md.
        """
        import yagagraphics
        surface = yagagraphics.target_surface()
        anim = self.anim
        inner = getattr(anim, "anim", None)
        if surface is None or inner is None or not inner.frames:
            return

        index = int(self.currentFrame or 0) % len(inner.frames)
        ox, oy = int(self.position.x or 0), int(self.position.y or 0)
        drawn = 0
        for layer in inner.frames[index].layers:
            if layer.rgba is None or not layer.w or not layer.h:
                continue
            if layer.mask and not (layer.mask & PHONEME_REST):
                continue
            surface.blit(_surface_for(layer), (ox + layer.x, oy + layer.y))
            drawn += 1
        if drawn:
            _stub.LOG.record("call", "%s.Render" % self._yaga_name,
                             "(%s frame %d, %d layers)"
                             % (getattr(anim, "locator", "?"), index, drawn))

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
