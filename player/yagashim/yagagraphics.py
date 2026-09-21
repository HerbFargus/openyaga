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


class RenderTarget(_stub.Stub):
    """Truthy, unlike a plain stub -- boot.py checks `if not g_RenderTarget`."""

    def __init__(self, mode, buffers, targetType):
        _stub.Stub.__init__(self, "yagagraphics.RenderTarget")
        _stub.LOG.record("new", "yagagraphics.RenderTarget",
                         "(%r, buffers=%s)" % (mode, _stub._brief(buffers)))
        self.mode = mode
        self.width = getattr(mode, "width", SCREEN_WIDTH)
        self.height = getattr(mode, "height", SCREEN_HEIGHT)
        self.targetType = targetType

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
_mod.IImageAnim = IImageAnim

# Replacing ourselves in sys.modules drops the real module's last reference.
# Python 2 then tears it down and sets every global to None -- so the functions
# above would find _system, _System and _stub all None the next time they ran.
# Holding a reference keeps their globals intact.
_mod.__wrapped_module__ = sys.modules[__name__]
sys.modules[__name__] = _mod
