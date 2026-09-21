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


_mod.VideoMode = VideoMode
_mod.VideoDevice = VideoDevice
_mod.RenderTarget = RenderTarget
_mod.GraphicsSystem = GraphicsSystem
_mod.IRenderTarget = IRenderTarget

# Replacing ourselves in sys.modules drops the real module's last reference.
# Python 2 then tears it down and sets every global to None -- so the functions
# above would find _system, _System and _stub all None the next time they ran.
# Holding a reference keeps their globals intact.
_mod.__wrapped_module__ = sys.modules[__name__]
sys.modules[__name__] = _mod
