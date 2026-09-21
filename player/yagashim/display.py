"""The window: the game's fixed 640x480 picture, scaled to whatever size the
window is.

The game draws into a 640x480 surface exactly as it always has -- sprites,
fonts, the save-slot photos all assume that surface -- and once a frame
present() scales it into the real window.  That keeps every coordinate the
game knows about in its own 640x480 space; the one thing that has to cross
back is the mouse, which to_game() maps from window pixels to game pixels.

Options, from run_game.py flags and remembered between runs:

    fullscreen   borderless, at the desktop's own resolution      F11, Alt+Enter
    integer      scale by whole multiples only (2x, 3x), crisp      F10
    smooth       filter when scaling instead of nearest-neighbour  F12
    scale        starting window size, as a multiple of 640x480

Whatever the mode, the picture keeps its 4:3 shape; the rest of the window is
black.

SDL2 draws at real pixels only if the process says it is DPI aware.  Left
unaware, Windows stretches the whole window itself on a high-DPI screen -- a
blurry 250% on a 4K laptop -- and every size here would be a lie.  So the
process declares itself aware, and the default window size is chosen from the
desktop's real resolution instead.
"""

import json
import os
import sys

import pygame

import _stub

GAME_W, GAME_H = 640, 480

_SETTINGS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "display.json")

settings = {"fullscreen": False, "integer": False, "smooth": False, "scale": 0}
_overrides = {}          # from the command line: win over the saved file

_window = None           # the real pygame display surface
_game = None             # the 640x480 surface the game draws into
_windowed_size = None    # to restore after fullscreen
_rect = pygame.Rect(0, 0, GAME_W, GAME_H)   # where the picture lands in the window
_cursor = None           # (size, hotspot, data, mask) as the game set it
_cursor_scale = None


# -- settings ----------------------------------------------------------------
def load_settings():
    try:
        with open(_SETTINGS_PATH) as fh:
            saved = json.load(fh)
        for key in settings:
            if key in saved:
                settings[key] = int(saved[key]) if key == "scale" else bool(saved[key])
    except (IOError, OSError, ValueError):
        pass
    settings.update(_overrides)


def save_settings():
    try:
        with open(_SETTINGS_PATH, "w") as fh:
            # Numbers, not booleans: the game's boot.py sets __builtin__.False
            # = 0, so json's `o is False` test fails and it writes False --
            # which is not JSON, and the next run could not read its settings.
            json.dump(dict((k, int(bool(settings[k])))
                           for k in ("fullscreen", "integer", "smooth")),
                      fh, indent=1, sort_keys=True)
    except (IOError, OSError):
        pass


def configure(**options):
    """Command-line choices, applied over the saved ones.  None = not given."""
    for key, value in options.items():
        if value is not None:
            _overrides[key] = value


# -- DPI ---------------------------------------------------------------------
def _declare_dpi_aware():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)     # per-monitor
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _desktop_size():
    try:
        sizes = pygame.display.get_desktop_sizes()
        if sizes:
            return sizes[0]
    except Exception:
        pass
    info = pygame.display.Info()
    return info.current_w or GAME_W, info.current_h or GAME_H


def _default_scale():
    """The largest whole multiple of 640x480 that fits in most of the desktop."""
    w, h = _desktop_size()
    return max(1, min(int(w * 0.85) // GAME_W, int(h * 0.85) // GAME_H))


# -- the window --------------------------------------------------------------
def open_window(caption="openyaga"):
    """Open the window and return the 640x480 surface the game draws into."""
    global _game, _windowed_size
    _declare_dpi_aware()
    pygame.init()
    load_settings()
    scale = int(settings.get("scale") or 0) or _default_scale()
    _windowed_size = (GAME_W * scale, GAME_H * scale)
    _game = pygame.Surface((GAME_W, GAME_H))
    pygame.display.set_caption(caption)
    _set_mode()
    _stub.LOG.record("new", "display", "(window %dx%d, %s)" % (
        _window.get_width(), _window.get_height(), describe()))
    return _game


def _set_mode():
    global _window
    if settings["fullscreen"]:
        _window = pygame.display.set_mode(_desktop_size(), pygame.NOFRAME)
        try:
            pygame.display.set_window_position(0, 0)
        except Exception:
            pass
    else:
        _window = pygame.display.set_mode(_windowed_size, pygame.RESIZABLE)
    _layout()


def _layout():
    """Where the 640x480 picture goes in the window, and how big."""
    global _rect
    ww, wh = _window.get_size()
    if settings["integer"]:
        k = max(1, min(ww // GAME_W, wh // GAME_H))
        w, h = GAME_W * k, GAME_H * k
    else:
        k = min(ww / float(GAME_W), wh / float(GAME_H))
        w, h = max(1, int(GAME_W * k + 0.5)), max(1, int(GAME_H * k + 0.5))
    _rect = pygame.Rect((ww - w) // 2, (wh - h) // 2, w, h)
    _apply_cursor()


def describe():
    return "%s, %s scaling, %s" % (
        "fullscreen" if settings["fullscreen"] else "windowed",
        "integer" if settings["integer"] else "fit",
        "smooth" if settings["smooth"] else "sharp")


def game_surface():
    return _game


def window_surface():
    return _window


def present():
    """Scale the finished frame into the window and show it."""
    if _window is None or _game is None:
        return
    if _rect.size == (GAME_W, GAME_H):
        frame = _game
    elif settings["smooth"] and not settings["integer"]:
        frame = pygame.transform.smoothscale(_game, _rect.size)
    else:
        frame = pygame.transform.scale(_game, _rect.size)
    if _rect.topleft != (0, 0) or _rect.size != _window.get_size():
        _window.fill((0, 0, 0))
    _window.blit(frame, _rect.topleft)
    pygame.display.flip()


def resized(size):
    """The user dragged the window to a new size."""
    global _windowed_size
    if settings["fullscreen"]:
        return
    _windowed_size = (max(GAME_W // 2, size[0]), max(GAME_H // 2, size[1]))
    global _window
    _window = pygame.display.get_surface()
    _layout()


def toggle(option):
    settings[option] = not settings[option]
    if option == "fullscreen":
        _set_mode()
    else:
        _layout()
    save_settings()
    _stub.LOG.record("call", "display.toggle", "(%s) -> %s" % (option, describe()))


# -- the mouse ---------------------------------------------------------------
def to_game(pos):
    """Window pixels -> the game's 640x480 pixels, clamped to the picture."""
    x = (pos[0] - _rect.x) * GAME_W // max(1, _rect.w)
    y = (pos[1] - _rect.y) * GAME_H // max(1, _rect.h)
    return (max(0, min(GAME_W - 1, x)), max(0, min(GAME_H - 1, y)))


def set_cursor(size, hotspot, data, mask):
    """The game's monochrome cursor, drawn at the picture's scale so it keeps
    its size relative to the room."""
    global _cursor, _cursor_scale
    _cursor = (size, hotspot, data, mask)
    _cursor_scale = None
    _apply_cursor()


def _apply_cursor():
    global _cursor_scale
    if _cursor is None:
        return
    k = max(1, int(round(_rect.h / float(GAME_H))))
    if k == _cursor_scale:
        return
    size, hotspot, data, mask = _cursor
    if k > 1:
        size, hotspot, data, mask = scale_mono_cursor(size, hotspot, data, mask, k)
    try:
        pygame.mouse.set_cursor(size, hotspot, data, mask)
    except pygame.error:
        return          # no cursor support (a headless test driver)
    _cursor_scale = k


def scale_mono_cursor(size, hotspot, data, mask, k):
    """Blow a monochrome cursor up by a whole factor, bit by bit."""
    w, h = size
    row = w // 8

    def grow(bits):
        out = []
        for y in range(h):
            line = bits[y * row:(y + 1) * row]
            pixels = []
            for byte in line:
                for b in range(7, -1, -1):
                    pixels.extend([(byte >> b) & 1] * k)
            packed = []
            for i in range(0, len(pixels), 8):
                v = 0
                for bit in pixels[i:i + 8]:
                    v = (v << 1) | bit
                packed.append(v)
            for _ in range(k):
                out.extend(packed)
        return tuple(out)

    return (w * k, h * k), (hotspot[0] * k, hotspot[1] * k), grow(data), grow(mask)


def screenshot(path):
    if _game is not None:
        pygame.image.save(_game, path)
        return True
    return False
