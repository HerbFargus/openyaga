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
    """The fields the game reads: see pj_input_manager.InputHandler and
    cursor.CCursor.InputHandler."""

    def __init__(self, eventClass, eventType, value=0, elementID=0, deviceID=0):
        self.eventClass = eventClass
        self.eventType = eventType
        self.value = value
        self.elementID = elementID
        self.deviceID = deviceID

    def __repr__(self):
        return "<Event %s/%s value=%r>" % (self.eventClass, self.eventType, self.value)


class EventSource(_stub.Stub):
    """What GetEventSource returns -- a mouse, keyboard or gamepad.

    input_manager asserts on it, so it must be truthy, and sets .handled and
    .flags on it.
    """

    def __init__(self, eventClass, index):
        _stub.Stub.__init__(self, "yagaevents.EventSource(%s,%d)" % (eventClass, index))
        self.handled = 0
        self.flags = 0

    def __nonzero__(self):
        return True


def IEventSource(target=None):
    return EventSource("render_target", 0)


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
        self._sources = {}
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
    def RegisterEventReciever(self, classes, receiver=None, *a, **kw):
        _stub.LOG.record("call", "yagaevents.EventManager.RegisterEventReciever",
                         "(%s)" % _stub._brief(receiver))
        """Note the argument order: input_manager calls
        `em.RegisterEventReciever(seq, self)` -- the event classes first."""
        if receiver is not None and receiver not in self._receivers:
            self._receivers.append(receiver)

    def UnregisterEventReciever(self, receiver=None, *a, **kw):
        if receiver in self._receivers:
            self._receivers.remove(receiver)

    def GetEventSource(self, eventClass, index=0):
        # Only one mouse and one keyboard; no gamepads, so index 0 only.
        if index != 0:
            return None
        key = (eventClass, index)
        if key not in self._sources:
            self._sources[key] = EventSource(eventClass, index)
        return self._sources[key]

    def _dispatch(self, event):
        _stub.LOG.record('call', 'yagaevents.dispatch', '%r to %d receivers' % (event, len(self._receivers)))
        for receiver in list(self._receivers):
            try:
                receiver.Raise(event)
            except Exception, exc:
                _stub.LOG.record("call", "yagaevents.dispatch",
                                 "-> %s: %s" % (type(exc).__name__, exc))

    def CreateEventStreamPlayback(self, name="", *a, **kw):
        """A player for one .evb stream, which the caller then fills in."""
        return EventStreamPlayback(name)

    def _inject_test_hover(self):
        """Move the pointer with no button, so rollover can be exercised.

        Hovering is a separate thing to test from clicking: it is what changes
        the cursor over something clickable, and a click would hide that by
        running whatever is under it."""
        for frame, x, y in _stub.HOVERS:
            if frame != self.frames:
                continue
            _stub.LOG.record("call", "test.hover", "frame %d at (%d, %d)"
                             % (frame, x, y))
            pygame.event.post(pygame.event.Event(
                pygame.MOUSEMOTION, pos=(x, y), rel=(0, 0), buttons=(0, 0, 0)))

    def _inject_test_click(self):
        """Post a synthetic move-and-click, so input can be exercised without
        a person at the keyboard.  Driven by run_game.py --click."""
        for frame, x, y in _stub.CLICKS:
            if frame != self.frames:
                continue
            _stub.LOG.record("call", "test.click", "frame %d at (%d, %d)"
                             % (frame, x, y))
            pygame.event.post(pygame.event.Event(
                pygame.MOUSEMOTION, pos=(x, y), rel=(0, 0), buttons=(0, 0, 0)))
            pygame.event.post(pygame.event.Event(
                pygame.MOUSEBUTTONDOWN, pos=(x, y), button=1))
            pygame.event.post(pygame.event.Event(
                pygame.MOUSEBUTTONUP, pos=(x, y), button=1))

    def _pump_input(self):
        """Translate pygame input into the events the game expects.

        Mouse motion arrives as two separate axis events carrying the
        coordinate in `value`; that is how cursor.CCursor tracks the pointer.
        """
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                self.StopEventLoop()
            elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                self.StopEventLoop()
            elif ev.type == pygame.MOUSEMOTION:
                self._dispatch(Event(EEventClass.CLASS_MOUSE,
                                     EInputEvent.IEVENT_AXIS_POS_X, value=ev.pos[0]))
                self._dispatch(Event(EEventClass.CLASS_MOUSE,
                                     EInputEvent.IEVENT_AXIS_POS_Y, value=ev.pos[1]))
            elif ev.type in (pygame.MOUSEBUTTONDOWN, pygame.KEYDOWN):
                import yagasprite
                yagasprite.skip_videos()
            if ev.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
                kind = (EInputEvent.IEVENT_BUTTON_DOWN
                        if ev.type == pygame.MOUSEBUTTONDOWN
                        else EInputEvent.IEVENT_BUTTON_UP)
                self._dispatch(Event(EEventClass.CLASS_MOUSE, kind,
                                     elementID=ev.button - 1,
                                     value=int(ev.type == pygame.MOUSEBUTTONDOWN)))
            elif ev.type in (pygame.KEYDOWN, pygame.KEYUP):
                kind = (EInputEvent.IEVENT_BUTTON_DOWN if ev.type == pygame.KEYDOWN
                        else EInputEvent.IEVENT_BUTTON_UP)
                self._dispatch(Event(EEventClass.CLASS_KEYBOARD, kind,
                                     elementID=ev.key, value=1))

    # -- the loop ----------------------------------------------------------
    def StartEventLoop(self):
        import yagagraphics

        _stub.LOG.record("call", "yagaevents.EventManager.StartEventLoop",
                         "(%d timers)" % len(self._timers))
        for hook in _stub.FIRST_FRAME_HOOKS:
            try:
                hook()
            except Exception, exc:
                _stub.LOG.record("call", "hook", "%s: %s" % (type(exc).__name__, exc))
        del _stub.FIRST_FRAME_HOOKS[:]

        self._running = True
        clock = pygame.time.Clock()
        tick = Event(EEventClass.CLASS_TIMER, ETimerEvent.TIMER_TICK)

        while self._running:
            self._inject_test_hover()
            self._inject_test_click()
            self._pump_input()

            import yagasprite
            yagasprite.tick_all()

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

            if _stub.TRACE_STATE:
                try:
                    import globals as g
                    _stub.LOG.record('state', 'frame %d' % self.frames,
                                     'enabled=%s paused=%s hourglass=%s itemOnCursor=%s scene=%s'
                                     % (g.g_Cursor.enabled, g.g_AppPaused,
                                        getattr(g.g_Cursor, "hourglassCursor", "?"),
                                        getattr(g.g_Cursor, "itemOnCursor", "?"),
                                        g.g_SceneManager.CurrentScene()))
                except Exception, e:
                    pass
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

        # Shutdown happens in run_game, after the game's own Release() has
        # run: it still stops sounds once the loop returns.

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
_manager = None


def EventManagerFactory():
    """The engine's event manager is a singleton.

    input_manager builds its own with `em = yagaevents.EventManager()` and
    registers itself on that; if every call returned a fresh object those
    receivers would be stranded on a throwaway and no input would arrive.
    """
    global _manager
    if _manager is None:
        _manager = EventManager()
    return _manager


_mod.EventManager = EventManagerFactory
_mod.EventSource = EventSource
_mod.IEventSource = IEventSource


class IEventStream(object):
    """A parsed .evb.  The engine builds one from a loaded resource:

        stream = yagaevents.IEventStream(eventResource)

    For a talkie that is the lipsync track; see evb.py for the format.  A
    stream we cannot read is not an error -- the room event streams are a
    different shape -- it simply has no events and drives nothing.
    """

    def __init__(self, res=None):
        import evb
        self.resource = res
        self.path = str(getattr(res, "path", "") or "")
        data = getattr(res, "data", None)
        self.events = evb.parse(data) if data else None
        self.duration = self.events[-1][0] if self.events else 0.0
        if self.events:
            _stub.LOG.record("new", "yagaevents.IEventStream",
                             "(%s) %d mouth shapes over %.2fs"
                             % (self.path, len(self.events), self.duration))

    def MaskAt(self, elapsed):
        """The mouth shape in force `elapsed` seconds in.

        The last event at or before the moment wins: these are state changes,
        not pulses, so a shape holds until the next one replaces it.
        """
        if not self.events:
            return None
        mask = None
        for when, value in self.events:
            if when > elapsed:
                break
            mask = value
        return mask

    def __len__(self):
        return len(self.events or ())

    def __nonzero__(self):
        return True


class EventStreamPlayback(_stub.Stub):
    """What CreateEventStreamPlayback returns.

    character.PlayTalkie hangs one of these off the talking sprite:

        self.streamPlayback.stream = yagaevents.IEventStream(eventResource)
        self.__sprite.AddChild(self.streamPlayback)
        self.streamPlayback.Run(globals.g_SpriteManager.spriteScene)

    so the sprite is what reads it, once a frame.  Timed off the wall clock
    like the audio it belongs to, rather than off frames, so a slow moment
    cannot walk the mouth out of step with the voice.
    """

    def __init__(self, name=""):
        _stub.Stub.__init__(self, "yagaevents.EventStreamPlayback")
        self.stream = None
        self.name = name
        object.__setattr__(self, "_started", None)
        object.__setattr__(self, "_offset", 0.0)

    def Run(self, scene=None, *a, **kw):
        object.__setattr__(self, "_started", time.time())

    def Stop(self, scene=None, *a, **kw):
        object.__setattr__(self, "_started", None)

    def Seek(self, offset=0.0, *a, **kw):
        try:
            object.__setattr__(self, "_offset", float(offset))
        except (TypeError, ValueError):
            pass

    def CurrentMask(self):
        started = object.__getattribute__(self, "_started")
        stream = self.stream
        if started is None or not isinstance(stream, IEventStream):
            return None
        return stream.MaskAt(time.time() - started
                             + object.__getattribute__(self, "_offset"))

    def __nonzero__(self):
        return True


_mod.IEventStream = IEventStream
_mod.EventStreamPlayback = EventStreamPlayback

_mod.__wrapped_module__ = sys.modules[__name__]
sys.modules[__name__] = _mod
