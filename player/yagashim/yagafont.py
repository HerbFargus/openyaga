# -*- coding: latin-1 -*-
"""Bitmap fonts, and the subtitles they draw.

The game's text needs no reversing: `data/script/pajamasam4_script.xml` holds
the line, its speaker and its audio file for all 1,212 talkies, and
`CPlayListItem` already builds an image string for every one of them --

    self.iStr = yagafont.FontManager().CreateImageString()
    self.iStr.font = yagafont.FontManager().GetFont('arial_13_black_outline')
    self.iStr.position = yagascene.Point(10, 10, 100000)
    self.iStr.constrainedWidth = 620

-- then `ShowText` appends it to the sprite manager, which asks it to render
like any other sprite.  Left as a stub that was 1,212 image strings a game,
each quietly doing nothing.

**The fonts.**  `data/fonts.xml` binds six of them to a .mng and an ASCII
range:

    <font value="arial_13_black_outline">
        <resource value="menus/fonts/arial_13_black_outline.mng"/>
        <ascii_data minChar="!" maxChar="~" spaceChar="34" baselineChar="a"/>
    </font>

Each .mng is one image -- `font_loader.LoadFontImage` takes
`anim.frames[0].layers[0]` and nothing else -- holding every glyph in a
single strip.  arial_13 is 1224x17.

**Slicing them.**  The engine is handed the strip and the ASCII range and
nothing more, so the glyph boundaries have to be in the picture: they are the
runs of columns that are not entirely transparent.  For arial_13 that gives
exactly 94 runs against exactly 94 codes from '!' (33) to '~' (126), which is
the confirmation that this is the rule and not a coincidence.  Glyphs are
proportional -- 'i' is 6 columns wide, 'm' 14, 'W' 17.

**Advance.**  This one is a judgement call, and worth stating plainly.  The
strip leaves 1-4 transparent columns between glyphs, and there are two
readings: they are the intended letter spacing, or they are separators that
exist so the engine can find the boundaries at all.  Taking them as spacing
sets the letters visibly apart, so they are separators -- and then the ink
width is not the advance either, because an outlined glyph carries a pixel of
outline down each side that is meant to sit against its neighbour's.

So the advance is the ink width less OVERLAP, which is 2.  That was settled by
rendering the same line at 0, 1, 2 and 3 and looking: 0 and 1 are loose, 3
runs the glyphs into each other, 2 reads as Arial.  `kerning_adjust` from a
menu's `text_style` is added on top; every one in the shipped data is 0.

A space advances by the width of the glyph named in `spaceChar`, which is 34
-- the double quote -- in all six fonts.
"""

import sys

import pygame

import _stub

_mod = _stub.StubModule(__name__)


class HorizontalJustification(object):
    HJUSTIFY_LEFT = 0
    HJUSTIFY_CENTER = 1
    HJUSTIFY_RIGHT = 2


class VerticalJustification(object):
    VJUSTIFY_TOP = 0
    VJUSTIFY_CENTER = 1
    VJUSTIFY_BOTTOM = 2


def _slice(surface):
    """The glyph strip, cut at its transparent columns.

    Returns [(x, width), ...] in order.  A column counts as a separator only
    when every pixel in it is fully transparent, so the gap inside a 'C' or
    under a 'T' cannot split a glyph.
    """
    width, height = surface.get_size()
    try:
        surface.lock()
    except Exception:
        pass
    try:
        blank = []
        for x in range(width):
            empty = True
            for y in range(height):
                if surface.get_at((x, y))[3]:
                    empty = False
                    break
            blank.append(empty)
    finally:
        try:
            surface.unlock()
        except Exception:
            pass

    runs = []
    start = None
    for x in range(width):
        if not blank[x] and start is None:
            start = x
        elif blank[x] and start is not None:
            runs.append((start, x - start))
            start = None
    if start is not None:
        runs.append((start, width - start))
    return runs


class Font(object):
    """One bitmap font: a glyph surface and an advance for each character."""

    def __init__(self, name, image, ascii_data):
        self.name = name
        self.glyphs = {}
        self.height = 0
        self.space = 6

        surface = getattr(image, "surface", image)
        if surface is None or not hasattr(surface, "get_size"):
            _stub.LOG.record("call", "yagafont.Font", "(%s) no image" % name)
            return
        self.height = surface.get_height()

        first = int(getattr(ascii_data, "minChar", ord("!")) or ord("!"))
        last = int(getattr(ascii_data, "maxChar", ord("~")) or ord("~"))
        runs = _slice(surface)
        expected = last - first + 1
        if len(runs) != expected:
            # Say so rather than drawing gibberish: every glyph after the
            # mismatch would be the wrong letter.
            _stub.LOG.record("call", "yagafont.Font",
                             "(%s) %d glyphs for %d codes -- not sliced"
                             % (name, len(runs), expected))
            if len(runs) < expected:
                return

        for index, (x, width) in enumerate(runs[:expected]):
            code = first + index
            self.glyphs[code] = (surface.subsurface((x, 0, width, self.height)),
                                 width)

        space_code = int(getattr(ascii_data, "spaceChar", 34) or 34)
        self.space = self.glyphs.get(space_code, (None, 6))[1]
        _stub.LOG.record("new", "yagafont.Font",
                         "(%s) %d glyphs, %dpx tall, space %dpx"
                         % (name, len(self.glyphs), self.height, self.space))

    OVERLAP = 2

    def advance(self, char, kerning=0):
        if char == " ":
            return self.space - self.OVERLAP + kerning
        entry = self.glyphs.get(ord(char))
        return (entry[1] - self.OVERLAP + kerning) if entry else 0

    def measure(self, text, kerning=0):
        return sum(self.advance(c, kerning) for c in text)

    def __nonzero__(self):
        return bool(self.glyphs)


class IImageString(object):
    """A laid-out run of text, drawn by the sprite manager.

    It is appended to g_SpriteManager like a sprite, so it needs the three
    things the manager asks of one: a `position` to sort by, a `Seek` each
    tick, and a `Render`.
    """

    def __init__(self):
        import yagascene
        self.font = None
        self.position = yagascene.Point(0, 0, 0)
        self.opacity = 1.0
        self.hJustify = HorizontalJustification.HJUSTIFY_LEFT
        self.vJustify = VerticalJustification.VJUSTIFY_TOP
        self.constrainedWidth = 640
        self.constrainedHeight = 480
        self.kerningAdjust = 0
        self.text = ""
        self._lines = None

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _stub.Stub("yagafont.IImageString.%s" % name)

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)
        # Any of these changes the layout, so throw it away and do it again
        # on the next draw rather than trying to patch it.
        if name in ("font", "constrainedWidth", "kerningAdjust", "text"):
            object.__setattr__(self, "_lines", None)

    def SetText(self, text=""):
        self.text = "" if text is None else str(text)

    def GetText(self):
        return self.text

    def Seek(self, *a, **kw):
        pass

    def _wrap(self):
        """Break the text to constrainedWidth, on spaces, keeping newlines.

        The script's text runs to a couple of sentences and the game gives it
        620 pixels of a 640 pixel screen, so wrapping is the whole of the
        layout problem.
        """
        font = self.font
        if not isinstance(font, Font) or not font.glyphs:
            return []
        limit = int(self.constrainedWidth or 640)
        kerning = int(self.kerningAdjust or 0)
        lines = []
        for paragraph in self.text.replace("\r\n", "\n").split("\n"):
            words = paragraph.split(" ")
            current = ""
            for word in words:
                candidate = word if not current else current + " " + word
                if current and font.measure(candidate, kerning) > limit:
                    lines.append(current)
                    current = word
                else:
                    current = candidate
            lines.append(current)
        return lines

    def Render(self, camera=None, *a, **kw):
        import yagagraphics
        surface = yagagraphics.target_surface()
        font = self.font
        if surface is None or not isinstance(font, Font) or not font.glyphs:
            return
        if self._lines is None:
            object.__setattr__(self, "_lines", self._wrap())
        lines = self._lines
        if not lines:
            return

        kerning = int(self.kerningAdjust or 0)
        line_height = font.height
        try:
            left = int(self.position.x or 0)
            top = int(self.position.y or 0)
        except (TypeError, ValueError):
            left, top = 0, 0

        block = line_height * len(lines)
        if self.vJustify == VerticalJustification.VJUSTIFY_CENTER:
            top += (int(self.constrainedHeight or 0) - block) // 2
        elif self.vJustify == VerticalJustification.VJUSTIFY_BOTTOM:
            top += int(self.constrainedHeight or 0) - block

        try:
            opacity = max(0.0, min(1.0, float(self.opacity)))
        except (TypeError, ValueError):
            opacity = 1.0

        for row, line in enumerate(lines):
            width = font.measure(line, kerning)
            x = left
            if self.hJustify == HorizontalJustification.HJUSTIFY_CENTER:
                x += (int(self.constrainedWidth or 0) - width) // 2
            elif self.hJustify == HorizontalJustification.HJUSTIFY_RIGHT:
                x += int(self.constrainedWidth or 0) - width
            y = top + row * line_height
            for char in line:
                if char == " ":
                    x += font.advance(" ", kerning)
                    continue
                entry = font.glyphs.get(ord(char))
                if entry is None:
                    x += font.advance(" ", kerning)
                    continue
                glyph, width_px = entry
                if opacity < 0.999:
                    glyph = glyph.copy()
                    glyph.fill((255, 255, 255, int(opacity * 255)), None,
                               pygame.BLEND_RGBA_MULT)
                surface.blit(glyph, (x, y))
                x += width_px - font.OVERLAP + kerning

    def __nonzero__(self):
        return True


class CFontManager(object):
    """Holds the loaded fonts.  A singleton: font_loader builds the fonts
    through `FontManager()` and script.py looks them up through another call
    to the same name, so a fresh object each time would find nothing."""

    def __init__(self):
        self.fonts = {}

    def CreateFontFromImage(self, image=None, name="", ascii_data=None, *a, **kw):
        font = Font(str(name), image, ascii_data)
        if font.glyphs:
            self.fonts[str(name)] = font
        return font

    def GetFont(self, name="", *a, **kw):
        font = self.fonts.get(str(name))
        if font is None:
            _stub.LOG.record("call", "yagafont.FontManager.GetFont",
                             "(%s) not loaded" % name)
        return font

    def CreateImageString(self, *a, **kw):
        return IImageString()

    def __nonzero__(self):
        return True


_manager = None


def FontManagerFactory():
    global _manager
    if _manager is None:
        _manager = CFontManager()
    return _manager


_mod.FontManager = FontManagerFactory
_mod.HorizontalJustification = HorizontalJustification
_mod.VerticalJustification = VerticalJustification
_mod.IImageString = IImageString
_mod.Font = Font

_mod.__wrapped_module__ = sys.modules[__name__]
sys.modules[__name__] = _mod
