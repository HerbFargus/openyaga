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

import random
import struct
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

_live = []          # every sprite made, so playback does not depend on drawing
_videos = []        # movies, so a click can cut one short


def tick_all():
    """Advance every playing sprite, once per frame.

    Animation cannot be driven from Render(): a sprite that is off screen, or
    simply not in the render list, still has to finish -- and a character's
    exit animation finishing is what triggers the room change.
    """
    for sprite in list(_live):
        try:
            sprite._apply_lipsync()
        except Exception:
            pass
        try:
            inner = getattr(sprite.anim, "anim", None)
            if inner is not None and inner.frames:
                sprite._advance(len(inner.frames))
        except Exception:
            continue


_mod = _stub.StubModule(__name__)


class IVideoElement(object):
    """A Bink movie -- the .da2 files, which are BIK video.

    The header gives the shape of the thing without decoding anything, and is
    what the movie is timed by:

        offset 0   "BIK" + version byte
               8   frame count
              20   width, height
              28   fps dividend, divider

    scene_helogo watches CBinkSprite.IsFinished(), which is
    `binkVideo.isPlaying == false`, to move from the Atari logo to the
    Humongous one and then into the game.  So the clock here is authoritative:
    the movie runs for exactly as long as its header says, whether or not the
    pictures keep up.  bink.Movie does the decoding and hands back whichever
    frame is due; without ffmpeg there are no frames and this is a black
    screen for the right duration, as it was before.
    """

    def __init__(self, res=None):
        self.resource = res
        self.path = str(getattr(res, "path", "") or "")
        self.volume = 1.0
        self.width = self.height = 0
        self.frames = 0
        self.fps = 15.0
        self._started = None
        self._playing = False

        data = getattr(res, "data", None)
        if data and len(data) >= 40 and bytes(data[:3]) == "BIK":
            (self.frames,) = struct.unpack_from("<I", bytes(data), 8)
            self.width, self.height = struct.unpack_from("<II", bytes(data), 20)
            dividend, divider = struct.unpack_from("<II", bytes(data), 28)
            if divider:
                self.fps = float(dividend) / divider
        self.duration = (self.frames / self.fps) if self.fps else 0.0
        if _stub.SKIP_VIDEO:
            self.duration = 0.0
        self.movie = None
        if not _stub.SKIP_VIDEO and self.width and self.height:
            import bink
            self.movie = bink.Movie(self.path, data,
                                    self.width, self.height, self.fps)
        _videos.append(self)
        _stub.LOG.record("new", "yagasprite.IVideoElement",
                         "(%s) %dx%d, %d frames at %.1f fps = %.1fs"
                         % (self.path, self.width, self.height,
                            self.frames, self.fps, self.duration))

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _stub.Stub("yagasprite.IVideoElement.%s" % name)

    def __setattr__(self, name, value):
        """CBinkSprite.SetVolume writes straight through to `volume`, and the
        options screen does it while a movie is already running."""
        object.__setattr__(self, name, value)
        if name == "volume":
            movie = self.__dict__.get("movie")
            if movie is not None:
                movie.SetVolume(value)

    @property
    def isPlaying(self):
        if not self._playing:
            return False
        if self._started is None:
            return True
        if time.time() - self._started >= self.duration:
            object.__setattr__(self, "_playing", False)
            return False
        return True

    def Run(self, scene=None, *a, **kw):
        self._playing = True
        if self.movie is not None:
            self.movie.Start()
            self.movie.SetVolume(self.volume)
        # Started after the decoder, so the first frame is not already late.
        self._started = time.time()
        _stub.LOG.record("call", "yagasprite.IVideoElement.Run",
                         "(%s for %.1fs)" % (self.path, self.duration))

    def Stop(self, scene=None, *a, **kw):
        self._playing = False
        if self.movie is not None:
            self.movie.Stop()

    def Render(self, camera=None, *a, **kw):
        """Draw whichever frame is due.

        The game calls this through CBinkSprite.Render, once a frame, for as
        long as the movie is playing.
        """
        if self.movie is None or not self._playing or self._started is None:
            return
        import yagagraphics
        surface = yagagraphics.target_surface()
        if surface is None:
            return
        frame = self.movie.surface_at(time.time() - self._started)
        if frame is not None:
            surface.blit(frame, (0, 0))

    def __nonzero__(self):
        return True

    def __repr__(self):
        return "<IVideoElement %s>" % self.path


def skip_videos():
    """End any playing movie immediately.

    We cannot draw Bink, so a movie is a black screen for its real duration --
    and pj_intro.da2 runs 172 seconds, during which the game is waiting and
    nothing responds.  A click or a key ends it, which is roughly what the
    original offered anyway: its cutscenes could be clicked through.
    """
    ended = 0
    for video in list(_videos):
        if video.isPlaying:
            video.Stop()
            ended += 1
    if ended:
        _stub.LOG.record("call", "yagasprite.skip_videos", "ended %d" % ended)
    return ended


class SoundList(object):
    """talkies.sounds -- character.PlayTalkie adds to it with an explicit
    `.sounds.__iadd__(sound)`, which a plain stub cannot answer because
    Stub.__getattr__ refuses dunder names."""

    def __init__(self):
        self.items = []

    def __iadd__(self, sound):
        self.items.append(sound)
        return self

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)

    def Clear(self, *a, **kw):
        self.items = []


class TalkieList(_stub.Stub):
    """What sprite.talkies is.  script.py drives it as

        speakerObj.talkies.Clear()
        speakerObj.talkies[0] = soundObj
        speakerObj.talkies.Run(soundScene)

    so it needs item assignment and a Run that starts what was assigned.
    """

    def __init__(self, name):
        _stub.Stub.__init__(self, name)
        self.continuous = 0
        object.__setattr__(self, "_items", {})
        object.__setattr__(self, "sounds", SoundList())

    def Clear(self, *a, **kw):
        object.__getattribute__(self, "_items").clear()
        object.__getattribute__(self, "sounds").Clear()

    def __setitem__(self, index, value):
        object.__getattribute__(self, "_items")[index] = value

    def __getitem__(self, index):
        return object.__getattribute__(self, "_items").get(index)

    def __len__(self):
        return len(object.__getattribute__(self, "_items"))

    def _all(self):
        return (list(object.__getattribute__(self, "_items").values())
                + list(object.__getattribute__(self, "sounds")))

    def Run(self, scene=None, *a, **kw):
        for sound in self._all():
            if hasattr(sound, "Run"):
                sound.Run(scene)
                _stub.LOG.record("call", "yagasprite.talkies.Run",
                                 "(%s)" % getattr(sound, "path", "?"))

    def Stop(self, scene=None, *a, **kw):
        for sound in self._all():
            if hasattr(sound, "Stop"):
                sound.Stop(scene)

    @property
    def isPlaying(self):
        """True while any line in the list is still being spoken.

        This is what a cutscene waits on.  character.PlayTalkie returns the
        sprite's talkie list rather than the sound itself, so the script ends
        up polling the list:

            self.soundObj = ...PlayTalkie(self.sound)     # -> sprite.talkies
            ...
            if self.soundObj.isPlaying:
                return True                               # still playing

        Without this the name resolved to an auto-created stub, which is
        truthy for ever: the script item never finished, its callback never
        ran, and whatever disabled the cursor for the cutscene never got to
        re-enable it.  The game accepted clicks and dropped every one.
        """
        for sound in self._all():
            if getattr(sound, "isPlaying", 0):
                return 1
        return 0

    @property
    def duration(self):
        """Longest line in the list; script.py reads it off the same object."""
        best = 0.0
        for sound in self._all():
            try:
                best = max(best, float(getattr(sound, "duration", 0) or 0))
            except (TypeError, ValueError):
                continue
        return best

    def __nonzero__(self):
        return True


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
        # How far into the animation we are, and how long it runs.  script.py
        # waits on `speakerObj.time < speakerObj.duration` to decide a line is
        # still playing; left as stubs those compare arbitrarily and a script
        # can wait for ever, which stops the game dead after one interaction.
        self.time = 0.0
        self.duration = 0.0
        self.hFlip = 0
        self.vFlip = 0
        self.visible = 1
        # The engine blends sprites by opacity; CActiveSprite reads it back
        # straight after construction, so it has to exist and be a number.
        self.opacity = 1.0
        self._playing = False
        self._started = None
        self._anim_id = None
        self._drawn = []          # (layer, screen x, screen y) from the last frame
        object.__setattr__(self, "_sinks", [])
        object.__setattr__(self, "_children", [])
        # Named layers the game has switched off, e.g. the nine eye
        # directions it does not want, and when this sprite next blinks.
        object.__setattr__(self, "_layer_flags", {})
        object.__setattr__(self, "_blink_at", time.time() + 1.0 + random.random() * 4.0)
        # ROOT: the rest pose, and what the game resets a mouth to.
        self.renderMask = PHONEME_REST
        _live.append(self)
        # Not a list: the game sets attributes on it, e.g.
        # `sprite.talkies.continuous = true`.
        self.talkies = TalkieList("%s.talkies" % name)

    def __setattr__(self, name, value):
        """Keep frameCount in step with the animation.

        The engine exposes an animation's length on the sprite, not on the
        anim, and the game reads it straight back:

            sprite = yagasprite.Sprite()
            sprite.anim = self.LoadAnim(path)
            ...
            if self.__sprite.currentFrame < self.__sprite.frameCount - 1:

        Left at zero that test is `0 < -1`, so every clickpoint animation
        ended on its first tick -- the instance hid itself, released the
        clickpoint and never drew a frame or played a sound.  Rooms looked
        alive (clicks registered, objects were found) and did nothing.
        """
        _stub.Stub.__setattr__(self, name, value)
        if name == "anim":
            frames = getattr(value, "frames", None)
            try:
                count = len(frames) if frames else 0
            except TypeError:
                count = 0
            _stub.Stub.__setattr__(self, "frameCount", count)
            _stub.Stub.__setattr__(self, "currentFrame", 0)

    def AddChild(self, child=None, *a, **kw):
        """Children are how the engine attaches a talkie's event stream.

        character.PlayTalkie builds the stream, hangs it off the sprite and
        runs it; the sprite is then what reads the mouth shapes out of it.
        """
        children = object.__getattribute__(self, "_children")
        if child is not None and child not in children:
            children.append(child)

    InsertChild = AddChild

    def RemoveChild(self, child=None, *a, **kw):
        children = object.__getattribute__(self, "_children")
        if child in children:
            children.remove(child)

    def RemoveChildren(self, *a, **kw):
        del object.__getattribute__(self, "_children")[:]

    def _apply_lipsync(self):
        """Put the current mouth shape into renderMask, once a frame.

        The game sets renderMask itself either side of a line -- ResetMouth
        puts it back to ROOT -- so this only speaks while a stream is
        actually running.
        """
        for child in list(object.__getattribute__(self, "_children")):
            mask = getattr(child, "CurrentMask", None)
            if mask is None:
                continue
            try:
                current = mask()
            except Exception:
                continue
            if current is not None:
                self.renderMask = current
                return

    def RegisterEventSink(self, sink, *a, **kw):
        sinks = object.__getattribute__(self, "_sinks")
        if sink is not None and sink not in sinks:
            sinks.append(sink)

    def UnregisterEventSink(self, sink=None, *a, **kw):
        sinks = object.__getattribute__(self, "_sinks")
        if sink in sinks:
            sinks.remove(sink)

    def _fire(self, eventType):
        """Tell anything watching that the animation started or ended.

        This is what drives room changes: a character's exit animation
        finishes, the sink fires SCENE_STOP, and the character queues the
        next scene.
        """
        import yagascene
        for sink in list(object.__getattribute__(self, "_sinks")):
            try:
                sink.Event(eventType, self)
            except Exception, exc:
                _stub.LOG.record("call", "yagasprite.sink",
                                 "-> %s: %s" % (type(exc).__name__, exc))

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
            import yagascene
            self._fire(yagascene.SceneEvents.SCENE_RUN)

    def Stop(self, *a, **kw):
        self._playing = False
        _stub.LOG.record("call", "%s.Stop" % self._yaga_name, _stub._args(a, kw))

    def _advance(self, frame_count):
        """Step currentFrame according to elapsed time, not frames drawn.

        The loop runs at DEFAULT_FPS (10) but is not guaranteed to, and an
        animation carries its own rate, so timing off the clock keeps playback
        at the intended speed either way.
        """
        # A single-frame animation still *finishes*: characters spend most of
        # their time on a one-frame root pose with loopCount 1, and the scene
        # change waits on that completion.
        if not self._playing or frame_count < 1:
            return
        # A new animation on the same sprite starts from its first frame.
        if self._anim_id != id(self.anim):
            self._anim_id = id(self.anim)
            self._started = time.time()
        fps = getattr(self.anim, "framesPerSecond", 10) or 10
        elapsed = time.time() - (self._started or time.time())
        step = int(elapsed * fps)
        loops = int(self.loopCount) if self.loopCount else 1
        self.duration = float(frame_count) / fps * loops
        self.time = min(elapsed, self.duration)
        if self.loopCount:
            limit = int(self.loopCount) * frame_count
            if step >= limit:
                self._playing = False
                self.time = self.duration
                self.currentFrame = frame_count - 1
                import yagascene
                _stub.LOG.record("call", "%s.finished" % self._yaga_name,
                                 "(%s)" % getattr(self.anim, "locator", "?"))
                self._fire(yagascene.SceneEvents.SCENE_STOP)
                return
        self.currentFrame = step % frame_count if frame_count else 0

    def SetLayerFlag(self, name=None, flag=None, on=1, *a, **kw):
        """Turn a named layer on or off.

        This is how the game picks between alternatives that all carry mask
        0 and would otherwise draw at once:

            def SetConditionalLayers(self):
                self.TurnOnLayerInSet(character.c_EyeDirections, 'FRONT')

        which turns on FRONT and turns off the other nine eye directions.
        There is only one flag in play, LF_LAYER_ON, so any call is about
        visibility.
        """
        if name is None:
            return
        flags = object.__getattribute__(self, "_layer_flags")
        flags[str(name).upper()] = bool(on)

    def _blink(self):
        """Which blink layer is showing, if any.

        Idle poses carry BLINK1 (half closed) and BLINK2 (shut) as mask 0
        layers, and no script in the game ever touches them -- the engine
        blinks characters itself.  Drawing them unconditionally, as a mask of
        0 otherwise means, leaves every character with their eyes shut.

        The shape of the blink is read off the art: open, half, shut, half,
        open.  Its timing is not in the data anywhere, so the rate here is a
        reconstruction rather than a recovered constant.
        """
        stages = (("BLINK1", 0.07), ("BLINK2", 0.09), ("BLINK1", 0.07))
        now = time.time()
        start = object.__getattribute__(self, "_blink_at")
        elapsed = now - start
        if elapsed < 0:
            return None
        for layer, length in stages:
            if elapsed < length:
                return layer
            elapsed -= length
        # Done: wait a few seconds, staggered so a roomful does not blink
        # in unison.
        object.__setattr__(self, "_blink_at", now + 2.5 + random.random() * 4.0)
        return None

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
            _stub.LOG.record("call", "yagasprite.Intersect",
                             "collider=%s x=%r y=%r drawn=%d -> reject"
                             % (type(collider).__name__, x, y, len(self._drawn)))
            return 0
        for layer, ox, oy in self._drawn:
            lx, ly = int(x) - ox, int(y) - oy
            if 0 <= lx < layer.w and 0 <= ly < layer.h:
                alpha = layer.rgba[(ly * layer.w + lx) * 4 + 3]
                if alpha:
                    return 1
        _stub.LOG.record("call", "yagasprite.Intersect",
                         "(%s) at (%s,%s) -> transparent" % (
                             getattr(self.anim, "locator", "?"), x, y))
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
        try:
            wanted = int(self.renderMask)
        except (TypeError, ValueError):
            wanted = PHONEME_REST
        index = int(self.currentFrame or 0) % len(inner.frames)
        flags = object.__getattribute__(self, "_layer_flags")
        blinking = self._blink()
        ox, oy = int(self.position.x or 0), int(self.position.y or 0)
        self._drawn = []
        drawn = 0
        for layer in inner.frames[index].layers:
            if layer.rgba is None or not layer.w or not layer.h:
                continue
            if layer.mask and not (layer.mask & wanted):
                continue
            name = (layer.name or "").upper()
            if name.startswith("BLINK"):
                if name != blinking:
                    continue
            elif flags.get(name) is False:
                continue
            lx, ly = ox + layer.x, oy + layer.y
            image = _surface_for(layer)
            try:
                opacity = float(self.opacity)
            except (TypeError, ValueError):
                opacity = 1.0
            if opacity < 0.999:
                # set_alpha is ignored on a per-pixel-alpha surface in SDL 1,
                # so scale the alpha channel itself.
                image = image.copy()
                level = max(0, min(255, int(opacity * 255)))
                image.fill((255, 255, 255, level), None, pygame.BLEND_RGBA_MULT)
            surface.blit(image, (lx, ly))
            self._drawn.append((layer, lx, ly))
            if opacity < 0.999:
                _stub.LOG.record("call", "yagasprite.blend",
                                 "(%s at %.2f opacity)"
                                 % (getattr(self.anim, "locator", "?"), opacity))
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
_mod.TalkieList = TalkieList
_mod.SoundList = SoundList
_mod.tick_all = tick_all
_mod.skip_videos = skip_videos
_mod.IVideoElement = IVideoElement
_mod.Sprite = Sprite
_mod.TalkieSprite = TalkieSprite

_mod.__wrapped_module__ = sys.modules[__name__]
sys.modules[__name__] = _mod
