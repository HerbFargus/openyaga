# -*- coding: latin-1 -*-
"""Real stand-in for the native yagaevents module -- the engine's main loop.

boot.py ends with `globals.eventManager.StartEventLoop()`, and everything the
game does after startup happens inside it.  main.MAIN_InitializeTiming sets up
the shape:

    codeTimer   = eventManager.CreateTimer()
    codeTimer.tickFrequency = DEFAULT_FPS
    eventManager.InstallTimer(codeTimer)
    codeTimer.eventReciever = CGameCodeCallback()   # game logic
    renderTimer.eventReciever = CRenderCallback()   # drawing
    eventManager.maxLoopFrequency = DEFAULT_FPS

so the loop is: tick each installed timer, hand its receiver a timer event, and
the game does the rest.  The render callback draws by calling

    g_RenderTarget.RenderBegin(0)
    g_SpriteManager.Render(g_Camera)
    g_Cursor.Render(g_Camera)
    g_RenderTarget.RenderEnd()

The constants must be real objects, not auto-stubs, because the receivers
compare against them:

    if yagaevents.EEventClass.CLASS_TIMER == event.eventClass and \\
       yagaevents.ETimerEvent.TIMER_TICK == event.eventType:

Timers are ticked in registration order, which puts game logic before drawing.
(The engine's own ordering may differ; this is the order the game installs
them, and it is the sane one.)
"""

import sys
import time

import pygame

import _stub

_mod = _stub.StubModule(__name__)


class _ConstMeta(type):
    """Named constants that are real where we know them and invented where we
    do not -- the engine has more event classes than the game reveals, e.g.
    CLASS_RENDER_TARGET.  Each invented one is cached, so `==` stays stable."""

    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        value = "%s.%s" % (cls.__name__, name)
        type.__setattr__(cls, name, value)
        _stub.LOG.record("const", "yagaevents.%s" % value)
        return value


class EEventClass(object):
    __metaclass__ = _ConstMeta
    CLASS_TIMER = "CLASS_TIMER"
    CLASS_INPUT = "CLASS_INPUT"
    CLASS_WINDOW = "CLASS_WINDOW"
    CLASS_SCENE = "CLASS_SCENE"


class ETimerEvent(object):
    __metaclass__ = _ConstMeta
    TIMER_TICK = "TIMER_TICK"


class ERecieverReturn(object):
    __metaclass__ = _ConstMeta
    EVENT_HANDLED = 1
    EVENT_NOT_HANDLED = 0


class EInputEvent(object):
    __metaclass__ = _ConstMeta
    INPUT_MOUSE_MOVE = "INPUT_MOUSE_MOVE"
    INPUT_MOUSE_DOWN = "INPUT_MOUSE_DOWN"
    INPUT_MOUSE_UP = "INPUT_MOUSE_UP"
    INPUT_KEY_DOWN = "INPUT_KEY_DOWN"
    INPUT_KEY_UP = "INPUT_KEY_UP"


class Event(object):
    def __init__(self, eventClass, eventType):
        self.eventClass = eventClass
        self.eventType = eventType

    def __repr__(self):
        return "<Event %s/%s>" % (self.eventClass, self.eventType)


class IEventReciever(_stub.Stub):
    """Base class for anything that wants events; the game subclasses it."""

    def __init__(self):
        _stub.Stub.__init__(self, "yagaevents.IEventReciever()")

    def Raise(self, event):
        return ERecieverReturn.EVENT_NOT_HANDLED

    def __nonzero__(self):
        return True


class Timer(_stub.Stub):
    def __init__(self, manager):
        _stub.Stub.__init__(self, "yagaevents.Timer")
        self.tickFrequency = 30
        self.eventReciever = None
        self._manager = manager
        self._suspended = 0

    def Tick(self):
        pass

    def __nonzero__(self):
        return True


class EventManager(_stub.Stub):
    def __init__(self):
        _stub.Stub.__init__(self, "yagaevents.EventManager()")
        self.maxLoopFrequency = 30
        self._timers = []
        self._running = False
        self._receivers = []
        self.frames = 0
        # Set by run_game.py: stop after N frames, for headless checking.
        self.frame_limit = _stub.FRAME_LIMIT

    # -- timers ------------------------------------------------------------
    def CreateTimer(self):
        return Timer(self)

    def InstallTimer(self, timer):
        if timer not in self._timers:
            self._timers.append(timer)

    def RemoveTimer(self, timer):
        if timer in self._timers:
            self._timers.remove(timer)

    def SuspendLocalTime(self, *a):
        pass

    def ResumeLocalTime(self, *a):
        pass

    # -- receivers ---------------------------------------------------------
    def RegisterEventReciever(self, receiver, *a, **kw):
        self._receivers.append(receiver)

    def UnregisterEventReciever(self, receiver, *a, **kw):
        if receiver in self._receivers:
            self._receivers.remove(receiver)

    # -- the loop ----------------------------------------------------------
    def StartEventLoop(self):
        import yagagraphics

        _stub.LOG.record("call", "yagaevents.EventManager.StartEventLoop",
                         "(%d timers)" % len(self._timers))
        self._running = True
        clock = pygame.time.Clock()
        tick = Event(EEventClass.CLASS_TIMER, ETimerEvent.TIMER_TICK)

        while self._running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.StopEventLoop()
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    self.StopEventLoop()

            for timer in list(self._timers):
                receiver = timer.eventReciever
                if receiver is None:
                    continue
                try:
                    receiver.Raise(tick)
                except Exception, exc:
                    _stub.LOG.record("call", "yagaevents.timer.Raise",
                                     "-> %s: %s" % (type(exc).__name__, exc))
                    raise

            self.frames += 1
            if self.frame_limit and self.frames >= self.frame_limit:
                if _stub.SCREENSHOT:
                    import yagagraphics as _g
                    surface = _g.target_surface()
                    if surface is not None:
                        pygame.image.save(surface, _stub.SCREENSHOT)
                _stub.LOG.record("call", "yagaevents.EventManager.StartEventLoop",
                                 "stopping after %d frames" % self.frames)
                self._running = False
            clock.tick(self.maxLoopFrequency or 30)

        yagagraphics.shutdown()

    def StopEventLoop(self):
        self._running = False

    def __nonzero__(self):
        return True


_mod.EEventClass = EEventClass
_mod.ETimerEvent = ETimerEvent
_mod.ERecieverReturn = ERecieverReturn
_mod.EInputEvent = EInputEvent
_mod.Event = Event
_mod.IEventReciever = IEventReciever
_mod.Timer = Timer
_mod.EventManager = EventManager

_mod.__wrapped_module__ = sys.modules[__name__]
sys.modules[__name__] = _mod
