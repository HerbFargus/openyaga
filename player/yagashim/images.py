# -*- coding: latin-1 -*-
"""Images the game can read, write and draw into -- what saving needs.

The save screen is built on pictures.  Pressing Escape photographs the room
(screen_capture.GetScreenCaptureImg renders every sprite into an off-screen
image), Save shrinks the photo onto the cursor, and dropping it on a slot
composites it into the slot's frame.  Saving then writes the pixels out a
byte at a time:

    def SaveImage(img, filename):
        assert yagagraphics.PixelFormat.PXL_A8R8G8B8 == img.pixelFmt
        data = []
        for byte in img.imgData:
            data.append(byte)
        cPickle.dump([img.width, img.height, data], outFile, true)

and loading pokes them back in with `img.imgData[i] = data[i]`, while the
thumbnail is shrunk with `imageop.scale(str(srcImg.imgData), ...)`.  So an
image has to be three things at once: a pygame surface to draw with, a
buffer of raw bytes the game can index and assign, and the two kept in step.

**Byte order.**  PXL_A8R8G8B8 is a 32-bit ARGB word, which on a
little-endian machine sits in memory as B, G, R, A.  imgData uses that order,
so a thumbnail saved by the original game should load here and one saved
here should load there.  Neither direction has been tried against a real
original save yet.

**Keeping them in step** is done lazily, in whichever direction is stale:
drawing marks the bytes out of date, writing a byte marks the surface out of
date, and each is rebuilt only when it is next asked for.
"""

import pygame

# Set by yagagraphics once it has defined its constants.
PXL_A8R8G8B8 = None


def _rect(r, width, height):
    """A pygame Rect from the engine's Rect, clipped to width x height."""
    if r is None:
        return pygame.Rect(0, 0, width, height)
    try:
        x, y = int(r.x), int(r.y)
        w, h = int(r.width), int(r.height)
    except (AttributeError, TypeError, ValueError):
        return pygame.Rect(0, 0, width, height)
    return pygame.Rect(x, y, w, h)


def _surface_of(source):
    """The drawable surface behind anything the game might hand us."""
    if source is None:
        return None
    if isinstance(source, pygame.Surface):
        return source
    if isinstance(source, Image):
        return source.surface
    surface = getattr(source, "surface", None)
    if isinstance(surface, pygame.Surface):
        return surface
    anim = getattr(source, "anim", None)
    frames = getattr(anim, "frames", None)
    if frames:
        return _surface_of(frames[0].layers[0].image)
    return None


def draw(dest, source, opacity=1.0, rcDst=None, rcSrc=None, exact=False):
    """Composite (or with exact=True, copy) part of source onto dest.

    Scales when the two rectangles differ in size, which is how the room
    photo becomes a thumbnail if it ever goes through here.  An exact copy
    replaces the destination pixels, alpha included, rather than blending
    over them -- that is the difference between the engine's Copy and its
    Composite.
    """
    src = _surface_of(source)
    if dest is None or src is None:
        return
    sw, sh = src.get_size()
    area = _rect(rcSrc, sw, sh).clip(pygame.Rect(0, 0, sw, sh))
    if area.width <= 0 or area.height <= 0:
        return
    target = _rect(rcDst, area.width, area.height)
    if target.width <= 0 or target.height <= 0:
        # Nothing to draw into.  Not "draw it unscaled": Putt-Putt's
        # billboard flip shrinks its strips to zero height, and on that last
        # frame the whole old picture flashed back at full size.
        return
    piece = src.subsurface(area)
    if (target.width, target.height) != (area.width, area.height) \
            and target.width > 0 and target.height > 0:
        piece = pygame.transform.smoothscale(piece.copy(), (target.width, target.height))
    try:
        level = float(opacity)
    except (TypeError, ValueError):
        level = 1.0
    if level < 0.999:
        piece = piece.copy()
        piece.fill((255, 255, 255, max(0, int(level * 255))), None,
                   pygame.BLEND_RGBA_MULT)
    if exact:
        dest.fill((0, 0, 0, 0), pygame.Rect(target.x, target.y,
                                            piece.get_width(), piece.get_height()))
        dest.blit(piece, (target.x, target.y), None, pygame.BLEND_RGBA_ADD)
    else:
        dest.blit(piece, (target.x, target.y))


def _surface_to_bgra(surface):
    raw = bytearray(pygame.image.tostring(surface, "RGBA"))
    raw[0::4], raw[2::4] = raw[2::4], raw[0::4]
    return raw


def _bgra_to_surface(pixels, width, height):
    raw = bytearray(pixels)
    raw[0::4], raw[2::4] = raw[2::4], raw[0::4]
    return pygame.image.fromstring(bytes(raw), (width, height), "RGBA")


class _Pixels(bytearray):
    """imgData: a bytearray that tells its image when a byte changes."""

    def __setitem__(self, index, value):
        bytearray.__setitem__(self, index, value)
        owner = self.__dict__.get("_owner")
        if owner is not None:
            owner._surface_stale = True


class Image(object):
    """An engine image: IImage, and what GraphicsSystem().CreateImage makes.

    Built from a surface, a resource, another image, or a size.  Wrapping
    shares the surface rather than copying it -- a layer's picture handed to
    the font loader or to the save slot is read, not written.
    """

    def __init__(self, source=None, width=None, height=None):
        self._pixels = None
        self._bytes_stale = True
        self._surface_stale = False
        surface = _surface_of(source)
        if surface is None and width and height:
            surface = pygame.Surface((int(width), int(height)), pygame.SRCALPHA, 32)
            surface.fill((0, 0, 0, 0))
        self._surface = surface
        if surface is not None:
            self._size = surface.get_size()
        else:
            self._size = (0, 0)

    # -- shape -------------------------------------------------------------
    @property
    def width(self):
        return self._size[0]

    @property
    def height(self):
        return self._size[1]

    @property
    def pixelFmt(self):
        return PXL_A8R8G8B8

    # -- the two views -----------------------------------------------------
    @property
    def surface(self):
        if self._surface_stale and self._pixels is not None:
            self._surface = _bgra_to_surface(self._pixels, self.width, self.height)
            self._surface_stale = False
        return self._surface

    @property
    def imgData(self):
        if self._surface is None:
            return bytearray()
        if self._pixels is None or self._bytes_stale:
            fresh = _surface_to_bgra(self.surface)
            if self._pixels is None:
                self._pixels = _Pixels(fresh)
                self._pixels._owner = self
            else:
                bytearray.__setitem__(self._pixels, slice(None), fresh)
            self._bytes_stale = False
        return self._pixels

    def drawn(self):
        """Call after drawing on .surface directly: the bytes are stale."""
        self._bytes_stale = True

    # -- drawing -----------------------------------------------------------
    def Fill(self, color=None, rect=None, *a, **kw):
        surface = self.surface
        if surface is None:
            return
        rgba = (int(getattr(color, "r", 0)), int(getattr(color, "g", 0)),
                int(getattr(color, "b", 0)), int(getattr(color, "a", 255)))
        surface.fill(rgba, _rect(rect, self.width, self.height))
        self.drawn()

    def Composite(self, source=None, opacity=1.0, rcDst=None, rcSrc=None, *a, **kw):
        draw(self.surface, source, opacity, rcDst, rcSrc)
        self.drawn()

    def Copy(self, source=None, rcDst=None, rcSrc=None, *a, **kw):
        draw(self.surface, source, 1.0, rcDst, rcSrc, exact=True)
        self.drawn()

    def get_size(self):
        return self._size

    def __nonzero__(self):
        return True

    def __repr__(self):
        return "<Image %dx%d>" % self._size
