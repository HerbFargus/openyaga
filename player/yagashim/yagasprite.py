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
import time

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
        # An empty rect rather than None: the room manager hit-tests every
        # object each tick, including sprites that have not drawn yet, and
        # utility.CursorOverSprite reads .x/.width straight off it.
        self.renderRect = yagascene.Rect(0, 0, 0, 0)
        self.currentFrame = 0
        self.frameCount = 0
        self.loopCount = 0
        self.hFlip = 0
        self.vFlip = 0
        self.visible = 1
        self._playing = False
        self._started = None
        self._anim_id = None
        self._drawn = []          # (layer, screen x, screen y) from the last frame
        # Not a list: the game sets attributes on it, e.g.
        # `sprite.talkies.continuous = true`.
        self.talkies = _stub.Stub("%s.talkies" % name)

    def Run(self, scene=None, *a, **kw):
        """Start playing.  Sprites do not animate until asked.

        Idempotent on purpose: the game calls Run every loop iteration, and
        restarting the clock each time pins every animation on frame 0.

        That is faithful rather than lazy: only characters call Run, so a
        clickpoint sits on its first frame until something activates it,
        which is what the game expects.
        """
        if not self._playing:
            self._playing = True
            self._started = time.time()
            _stub.LOG.record("call", "%s.Run" % self._yaga_name,
                             "(%s)" % _stub._brief(scene))

    def Stop(self, *a, **kw):
        self._playing = False
        _stub.LOG.record("call", "%s.Stop" % self._yaga_name, _stub._args(a, kw))

    def _advance(self, frame_count):
        """Step currentFrame according to elapsed time, not frames drawn.

        The loop runs at DEFAULT_FPS (10) but is not guaranteed to, and an
        animation carries its own rate, so timing off the clock keeps playback
        at the intended speed either way.
        """
        if not self._playing or frame_count < 2:
            return
        # A new animation on the same sprite starts from its first frame.
        if self._anim_id != id(self.anim):
            self._anim_id = id(self.anim)
            self._started = time.time()
        fps = getattr(self.anim, "framesPerSecond", 10) or 10
        elapsed = time.time() - (self._started or time.time())
        step = int(elapsed * fps)
        if self.loopCount:
            limit = int(self.loopCount) * frame_count
            if step >= limit:
                self._playing = False
                self.currentFrame = frame_count - 1
                return
        self.currentFrame = step % frame_count

    def SetLayerFlag(self, *a, **kw):
        _stub.LOG.record("call", "%s.SetLayerFlag" % self._yaga_name, _stub._args(a, kw))

    def SetVolume(self, *a, **kw):
        pass

    def Intersect(self, collider=None, *a, **kw):
        """Per-pixel hit test, which is what the game expects.

        utility.OverSprite checks renderRect first and only then calls this,
        "paying attention to transparency" -- so a click lands on a character
        only where it is actually opaque, not anywhere in its bounding box.
        """
        x, y = getattr(collider, "x", None), getattr(collider, "y", None)
        if x is None or y is None or not self._drawn:
            return 0
        for layer, ox, oy in self._drawn:
            lx, ly = int(x) - ox, int(y) - oy
            if 0 <= lx < layer.w and 0 <= ly < layer.h:
                alpha = layer.rgba[(ly * layer.w + lx) * 4 + 3]
                if alpha:
                    return 1
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

        self._advance(len(inner.frames))
        index = int(self.currentFrame or 0) % len(inner.frames)
        ox, oy = int(self.position.x or 0), int(self.position.y or 0)
        self._drawn = []
        drawn = 0
        for layer in inner.frames[index].layers:
            if layer.rgba is None or not layer.w or not layer.h:
                continue
            if layer.mask and not (layer.mask & PHONEME_REST):
                continue
            lx, ly = ox + layer.x, oy + layer.y
            surface.blit(_surface_for(layer), (lx, ly))
            self._drawn.append((layer, lx, ly))
            drawn += 1
        if self._drawn:
            import yagascene
            x1 = min(x for _l, x, _y in self._drawn)
            y1 = min(y for _l, _x, y in self._drawn)
            x2 = max(x + l.w for l, x, _y in self._drawn)
            y2 = max(y + l.h for l, _x, y in self._drawn)
            self.renderRect = yagascene.Rect(x1, y1, x2 - x1, y2 - y1)
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
