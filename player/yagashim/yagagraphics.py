# -*- coding: latin-1 -*-
"""Partly-real stand-in for the native yagagraphics module.

Everything here exists because the game asked for it. boot.py will not start
without a graphics device that reports a 640x480 mode in one of the 16-bit
formats it wants, so that much is implemented for real; every other name in
the module still auto-stubs and logs.

From BOOT_CreateRenderTarget, the contract is:

    vm = yagagraphics.VideoMode(width, height, format)   # .width .height .format
    device = BOOT_EnumFullscreenModes(vm)                # scans .primaryVideoDev
                                                         # then .videoDevices,
                                                         # matching dev.modes
    device.currentMode.format
    device.CreateRenderTarget(vm, buffers, targetType)   # must be truthy

The format constants are auto-created stubs rather than real pixel formats.
That is deliberate for now: they are cached, so the same name is the same
object every time, and the mode comparison in BOOT_EnumFullscreenModes is
identity-based. Real formats matter only once something actually renders.
"""

import sys

import pygame

import _stub

_mod = _stub.StubModule(__name__)

# 16-bit first: the game asks for 5-6-5, falls back to 5-5-5, and only then
# gives up.  32-bit is offered too, since the screen capture path wants A8R8G8B8.
_FORMAT_NAMES = ["PXL_R5G6B5", "PXL_X1R5G5B5", "PXL_A1R5G5B5", "PXL_A8R8G8B8"]

SCREEN_WIDTH = 640
SCREEN_HEIGHT = 480


class VideoMode(object):
    def __init__(self, width=0, height=0, format=None):
        self.width = width
        self.height = height
        self.format = format

    def __repr__(self):
        return "VideoMode(%s, %s, %s)" % (self.width, self.height, self.format)


_surface = None          # the pygame display, once opened


def target_surface():
    """Where sprites draw.  None until the game creates a render target."""
    return _surface


def shutdown():
    global _surface
    if _surface is not None:
        pygame.quit()
        _surface = None


class RenderTarget(_stub.Stub):
    """A real window.  Truthy, since boot.py checks `if not g_RenderTarget`.

    The game drives this once per frame from CRenderCallback:
        RenderBegin(0) -> sprites draw -> RenderEnd()
    which maps onto clear and flip.
    """

    def __init__(self, mode, buffers, targetType):
        global _surface
        _stub.Stub.__init__(self, "yagagraphics.RenderTarget")
        self.mode = mode
        self.width = getattr(mode, "width", SCREEN_WIDTH)
        self.height = getattr(mode, "height", SCREEN_HEIGHT)
        self.targetType = targetType
        # id -> (size, hotspot, data, mask), as the game loads them.
        object.__setattr__(self, "_cursors", {})
        object.__setattr__(self, "_cursor_id", None)

        pygame.init()
        _surface = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption("openyaga")
        _stub.LOG.record("new", "yagagraphics.RenderTarget",
                         "(%dx%d window opened)" % (self.width, self.height))

    # -- the per-frame cycle ----------------------------------------------
    def RenderBegin(self, clearFlags=0):
        if _surface is not None:
            _surface.fill((0, 0, 0))

    def RenderEnd(self):
        if _surface is not None:
            pygame.display.flip()

    def RenderImage(self, img, opacity=1.0, rcDst=None, rcSrc=None):
        pass

    def SetCursor(self, *a, **kw):
        pass

    # -- the cursor --------------------------------------------------------
    #
    # The game never takes its own software cursor path: CCursor.__init__
    # sets g_forceHWCursor true and CursorTest only ever clears useHWCursor,
    # so every ChangeCursor ends up here.  Left as no-ops the pointer stayed
    # a plain arrow over everything, when the game had been saying all along
    # which cursor it wanted -- the filled arrow over anything clickable, a
    # direction arrow over an exit, the hourglass while it is busy.

    def __setattr__(self, name, value):
        """`cursorVisible` is the game hiding and showing the pointer.

        CCursor.Render sets it false whenever the cursor is disabled, which
        is what happens for the length of a cutscene -- so honouring it is
        what makes the pointer disappear while Sam is busy, and come back
        when control returns.
        """
        _stub.Stub.__setattr__(self, name, value)
        if name == "cursorVisible":
            try:
                pygame.mouse.set_visible(bool(value))
            except Exception:
                pass

    def LoadCursorFile(self, path=None, idValue=None, *a, **kw):
        """Read a .cur and keep it under the id the game gave it."""
        if path is None or idValue is None:
            return 0
        if idValue in self._cursors:
            return idValue
        import resources
        import cur
        data = resources.read(str(path))
        if not data:
            _stub.LOG.record("call", "yagagraphics.RenderTarget.LoadCursorFile",
                             "(%s) not found" % path)
            return 0
        parsed = cur.parse(data)
        if parsed is None:
            _stub.LOG.record("call", "yagagraphics.RenderTarget.LoadCursorFile",
                             "(%s) could not be read as a cursor" % path)
            return 0
        self._cursors[idValue] = parsed
        _stub.LOG.record("call", "yagagraphics.RenderTarget.LoadCursorFile",
                         "(%s) -> id %s, %dx%d hotspot %s"
                         % (path, idValue, parsed[0][0], parsed[0][1], parsed[1]))
        return idValue

    def SetCursorByID(self, idValue=None, *a, **kw):
        entry = self._cursors.get(idValue)
        if entry is None or idValue == self._cursor_id:
            return
        size, hotspot, data, mask = entry
        try:
            pygame.mouse.set_cursor(size, hotspot, data, mask)
            # object.__setattr__, not plain assignment: Stub.__setattr__ files
            # attributes away in _yaga_attrs, which __getattribute__ never
            # looks at once __dict__ has the name -- so the "already showing
            # this one" guard above would have read None for ever and reset
            # the cursor on every rollover.
            object.__setattr__(self, "_cursor_id", idValue)
            _stub.LOG.record("call", "yagagraphics.RenderTarget.SetCursorByID",
                             "id %s" % idValue)
        except Exception, exc:
            _stub.LOG.record("call", "yagagraphics.RenderTarget.SetCursorByID",
                             "(%s) %s" % (idValue, exc))

    def screenshot(self, path):
        if _surface is not None:
            pygame.image.save(_surface, path)
            return True
        return False

    def __nonzero__(self):
        return True


class VideoDevice(object):
    def __init__(self, name="primary"):
        self.name = name
        fmts = [getattr(_mod.PixelFormat, f) for f in _FORMAT_NAMES]
        self.modes = [VideoMode(SCREEN_WIDTH, SCREEN_HEIGHT, f) for f in fmts]
        self.currentMode = self.modes[0]

    def CreateRenderTarget(self, mode, buffers, targetType):
        _stub.LOG.record("call", "yagagraphics.VideoDevice.CreateRenderTarget",
                         "(%r, %s, %s)" % (mode, _stub._brief(buffers),
                                           _stub._brief(targetType)))
        return RenderTarget(mode, buffers, targetType)

    def __repr__(self):
        return "<VideoDevice %s>" % self.name


class _System(_stub.Stub):
    def __init__(self):
        _stub.Stub.__init__(self, "yagagraphics.GraphicsSystem()")
        device = VideoDevice()
        self.primaryVideoDev = device
        self.videoDevices = [device]

    def __nonzero__(self):
        return True


_system = None


def GraphicsSystem():
    """Singleton, as the engine's is -- the game calls this constantly."""
    global _system
    if _system is None:
        _system = _System()
    _stub.LOG.record("call", "yagagraphics.GraphicsSystem", "()")
    return _system


class IRenderTarget(object):
    """Base class the game subclasses (see print_manager.CImageBufferTarget)."""

    def __init__(self):
        _stub.LOG.record("new", "yagagraphics.IRenderTarget", "(subclassed)")


class IImage(_stub.Stub):
    """A single bitmap.  font_loader builds these from a layer's surface;
    other callers pass a resource."""

    def __init__(self, source=None):
        _stub.Stub.__init__(self, "yagagraphics.IImage")
        surface = source
        if surface is not None and not hasattr(surface, "get_size"):
            anim = getattr(source, "anim", None)
            layers = anim.frames[0].layers if (anim and anim.frames) else []
            surface = layers[0].image if layers else None
        self.surface = surface
        self.width, self.height = surface.get_size() if surface is not None else (0, 0)

    def __nonzero__(self):
        return True


class IImageAnim(_stub.Stub):
    """A decoded animation, as the sprite manager wraps it:

        yagagraphics.IImageAnim(res).Compress(CompressionType.COMPRESS_YRLE, 1)

    Compression is the engine's own in-memory scheme; there is nothing to gain
    from imitating it here, so Compress returns self.
    """

    def __init__(self, res):
        _stub.Stub.__init__(self, "yagagraphics.IImageAnim")
        anim = getattr(res, "anim", None)
        self.resource = res
        self.anim = anim
        self.frames = anim.frames if anim is not None else []
        self.framesPerSecond = 15
        self.locator = getattr(res, "path", "")
        box = anim.bbox() if anim is not None else None
        self.width = (box[2] - box[0]) if box else 0
        self.height = (box[3] - box[1]) if box else 0
        _stub.LOG.record("new", "yagagraphics.IImageAnim",
                         "(%s) -> %d frames, %dx%d"
                         % (self.locator, len(self.frames), self.width, self.height))

    def Compress(self, kind=None, flag=None):
        return self

    def IsAnimDone(self):
        return True

    def __nonzero__(self):
        return True


_mod.VideoMode = VideoMode
_mod.VideoDevice = VideoDevice
_mod.RenderTarget = RenderTarget
_mod.GraphicsSystem = GraphicsSystem
_mod.IRenderTarget = IRenderTarget
_mod.IImage = IImage
_mod.IImageAnim = IImageAnim
import yagascene as _scene
_mod.Rect = _scene.Rect
_mod.target_surface = target_surface
_mod.shutdown = shutdown

# Replacing ourselves in sys.modules drops the real module's last reference.
# Python 2 then tears it down and sets every global to None -- so the functions
# above would find _system, _System and _stub all None the next time they ran.
# Holding a reference keeps their globals intact.
_mod.__wrapped_module__ = sys.modules[__name__]
sys.modules[__name__] = _mod
