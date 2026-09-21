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

import os
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


class KeyCodes(object):
    """The engine's names for the keys that are not characters.

    Numbered as linyaga numbers them (sys.h, KEYCODE_FIRST = 0x100 and on in
    order), which is the only surviving statement of the engine's table.
    The game compares against these by name everywhere but one place, and
    that one place is the rule that matters:

        elif msg.elementID < yagaevents.KeyCodes.KEY_CODES_BEGIN:
            ...self.__strData[...] += chr(msg.elementID)

    -- anything below KEY_CODES_BEGIN is a character, anything at or above
    it is a key.  So these all have to sit at 0x100 or higher.
    """
    KEY_CODES_BEGIN = 0x100
    KEY_ESCAPE = 0x100
    KEY_F1 = 0x101
    KEY_F2 = 0x102
    KEY_F3 = 0x103
    KEY_F4 = 0x104
    KEY_F5 = 0x105
    KEY_F6 = 0x106
    KEY_F7 = 0x107
    KEY_F8 = 0x108
    KEY_F9 = 0x109
    KEY_F10 = 0x10A
    KEY_F11 = 0x10B
    KEY_F12 = 0x10C
    KEY_BACKSPACE = 0x10D
    KEY_TAB = 0x10E
    KEY_ENTER = 0x10F
    KEY_SHIFT = 0x110
    KEY_CONTROL = 0x111
    KEY_ALT = 0x112
    KEY_UP = 0x113
    KEY_DOWN = 0x114
    KEY_LEFT = 0x115
    KEY_RIGHT = 0x116


_SPECIAL = {
    pygame.K_ESCAPE: KeyCodes.KEY_ESCAPE,
    pygame.K_BACKSPACE: KeyCodes.KEY_BACKSPACE,
    pygame.K_TAB: KeyCodes.KEY_TAB,
    pygame.K_RETURN: KeyCodes.KEY_ENTER,
    pygame.K_KP_ENTER: KeyCodes.KEY_ENTER,
    pygame.K_LSHIFT: KeyCodes.KEY_SHIFT,
    pygame.K_RSHIFT: KeyCodes.KEY_SHIFT,
    pygame.K_LCTRL: KeyCodes.KEY_CONTROL,
    pygame.K_RCTRL: KeyCodes.KEY_CONTROL,
    pygame.K_LALT: KeyCodes.KEY_ALT,
    pygame.K_RALT: KeyCodes.KEY_ALT,
    pygame.K_UP: KeyCodes.KEY_UP,
    pygame.K_DOWN: KeyCodes.KEY_DOWN,
    pygame.K_LEFT: KeyCodes.KEY_LEFT,
    pygame.K_RIGHT: KeyCodes.KEY_RIGHT,
}
for _n in range(1, 13):
    _SPECIAL[getattr(pygame, "K_F%d" % _n)] = getattr(KeyCodes, "KEY_F%d" % _n)

# Windows virtual-key codes for the punctuation keys, which is what a raw
# key event carries for them -- not their character.
_VK_PUNCTUATION = {
    ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF,
    "`": 0xC0, "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
}

# Keys the translated character event also reports, as the text entry
# screen expects: it reads KEY_ENTER and KEY_BACKSPACE from those events.
_TRANSLATED_SPECIALS = (KeyCodes.KEY_ENTER, KeyCodes.KEY_BACKSPACE,
                        KeyCodes.KEY_TAB, KeyCodes.KEY_ESCAPE)


def _raw_code(key):
    """What a raw key-down or key-up carries: a virtual-key code.

    Letters come through upper case -- the debug shortcut Ctrl+A tests a raw
    key-down against ord('A') -- so the room's lower-case bindings ('k' for
    keyboard hotspots, '.' to skip a line) match only the translated event,
    and fire once per press rather than once on the way down and again on
    the way up.  Space, digits and the special keys are the same either way.
    """
    if key in _SPECIAL:
        return _SPECIAL[key]
    if pygame.K_a <= key <= pygame.K_z:
        return key - 32
    if key == pygame.K_SPACE or pygame.K_0 <= key <= pygame.K_9:
        return key
    if 0 < key < 128:
        return _VK_PUNCTUATION.get(chr(key))
    return None


def _translated_code(ev):
    """What the translated event carries: the character typed, case and
    shift included, or the engine code for Enter, Backspace, Tab, Escape."""
    code = _SPECIAL.get(ev.key)
    if code in _TRANSLATED_SPECIALS:
        return code
    char = getattr(ev, "unicode", u"") or u""
    if len(char) == 1 and 32 <= ord(char) < 127:
        return ord(char)
    return None


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


def _display_key(ev):
    """Which display option a key toggles, or None: F11 or Alt+Enter for
    fullscreen, F10 for integer scaling, F12 for smooth scaling."""
    if ev.key == pygame.K_F11:
        return "fullscreen"
    if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and getattr(ev, "mod", 0) & pygame.KMOD_ALT:
        return "fullscreen"
    if ev.key == pygame.K_F10:
        return "integer"
    if ev.key == pygame.K_F12:
        return "smooth"
    return None



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

    def _pump_streams(self):
        """Raise the animation events that have come due.

        One event per stream event, in order and once only: CAnimReciever
        counts them itself (`self.idx += 1`) and looks up that index in the
        stream, so a skipped or repeated raise would read the wrong sounds
        for the rest of the animation.
        """
        import evb
        for playback in list(_playbacks):
            try:
                due = playback.Due()
            except Exception:
                continue
            for _ in range(due):
                self._dispatch(Event(EEventClass.CLASS_TIMER,
                                     ETimerEvent.TIMER_TICK,
                                     deviceID=playback.identity))

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
                pygame.MOUSEMOTION, pos=(x, y), rel=(0, 0), buttons=(0, 0, 0), test=True))

    def _inject_test_keys(self):
        """Press and release a key, for run_game.py --key."""
        for frame, key, char in _stub.KEYS:
            if frame != self.frames:
                continue
            _stub.LOG.record("call", "test.key", "frame %d key %d" % (frame, key))
            pygame.event.post(pygame.event.Event(
                pygame.KEYDOWN, key=key, unicode=char, mod=0))
            pygame.event.post(pygame.event.Event(pygame.KEYUP, key=key, mod=0))

    def _inject_test_click(self):
        """Post a synthetic move-and-click, so input can be exercised without
        a person at the keyboard.  Driven by run_game.py --click."""
        for frame, x, y in _stub.CLICKS:
            if frame != self.frames:
                continue
            _stub.LOG.record("call", "test.click", "frame %d at (%d, %d)"
                             % (frame, x, y))
            pygame.event.post(pygame.event.Event(
                pygame.MOUSEMOTION, pos=(x, y), rel=(0, 0), buttons=(0, 0, 0), test=True))
            pygame.event.post(pygame.event.Event(
                pygame.MOUSEBUTTONDOWN, pos=(x, y), button=1, test=True))
            pygame.event.post(pygame.event.Event(
                pygame.MOUSEBUTTONUP, pos=(x, y), button=1, test=True))

    def _pump_input(self):
        """Translate pygame input into the events the game expects.

        Mouse motion arrives as two separate axis events carrying the
        coordinate in `value`; that is how cursor.CCursor tracks the pointer.
        """
        import display
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                # Closing the window is how to quit.  Escape belongs to the
                # game, which opens its options menu with it.
                self.StopEventLoop()
                continue
            if ev.type == pygame.VIDEORESIZE:
                display.resized(ev.size)
                continue
            if ev.type in (pygame.KEYDOWN, pygame.KEYUP) and _display_key(ev):
                # The window's own keys, kept from the game.  (The game uses
                # F2 and F6-F9; nothing it listens for is taken.)
                if ev.type == pygame.KEYDOWN:
                    display.toggle(_display_key(ev))
                continue
            if ev.type == pygame.MOUSEMOTION:
                # The window may be any size; the game lives in 640x480.
                pos = ev.pos if getattr(ev, "test", False) else display.to_game(ev.pos)
                self._dispatch(Event(EEventClass.CLASS_MOUSE,
                                     EInputEvent.IEVENT_AXIS_POS_X, value=pos[0]))
                self._dispatch(Event(EEventClass.CLASS_MOUSE,
                                     EInputEvent.IEVENT_AXIS_POS_Y, value=pos[1]))
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
                # The keyboard source is set up with IFLAGS_RAW_BUTTONS +
                # IFLAGS_TRANSLATE_BUTTONS, so the game gets both: raw
                # down/up events carrying a key code, and on the way down a
                # translated press carrying the character -- which is what
                # the save-name entry screen reads.
                raw = _raw_code(ev.key)
                if raw is not None:
                    kind = (EInputEvent.IEVENT_BUTTON_DOWN if ev.type == pygame.KEYDOWN
                            else EInputEvent.IEVENT_BUTTON_UP)
                    self._dispatch(Event(EEventClass.CLASS_KEYBOARD, kind,
                                         elementID=raw, value=1))
                if ev.type == pygame.KEYDOWN:
                    typed = _translated_code(ev)
                    if typed is not None:
                        self._dispatch(Event(EEventClass.CLASS_KEYBOARD,
                                             EInputEvent.IEVENT_BUTTON_PRESS,
                                             elementID=typed, value=1))

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
            self._inject_test_keys()
            self._pump_input()
            self._pump_streams()

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
        """End the loop -- and if that is the game giving up, say so.

        main.py's tick handler ends like this:

            except:
                traceback.print_exc(None, sys.stderr)
                globals.eventManager.StopEventLoop()

        and sys.stderr is the game's log redirector by then, so a crash
        looks exactly like quitting.  The test for "called from inside a
        handler" is that the exception being handled was caught in the very
        frame calling us.  sys.exc_info() alone is not enough: Python 2 keeps
        an exception around until the frame that handled it returns, so an
        error swallowed earlier in the loop would turn every later quit into
        a false crash report.
        """
        info = sys.exc_info()
        caller = sys._getframe(1)
        if info[0] is not None and info[2] is not None                 and info[2].tb_frame is caller:
            where = "%s:%d (%s)" % (os.path.basename(caller.f_code.co_filename),
                                    caller.f_lineno, caller.f_code.co_name)
            _stub.report_crash(info, where)
        self._running = False

    def __nonzero__(self):
        return True


_mod.KeyCodes = KeyCodes
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
        self.duration = self.events[-1].time if self.events else 0.0
        if self.events:
            lipsync = len([e for e in self.events if e.type == evb.EVENT_LIPSYNC])
            sounds = [v for e in self.events for v in e.named("SoundName")]
            _stub.LOG.record("new", "yagaevents.IEventStream",
                             "(%s) %d events over %.2fs -- %d mouth shapes%s"
                             % (self.path, len(self.events), self.duration,
                                lipsync,
                                (", sounds %s" % (sounds,)) if sounds else ""))

    def MaskAt(self, elapsed):
        """The mouth shape in force `elapsed` seconds in.

        The last event at or before the moment wins: these are state changes,
        not pulses, so a shape holds until the next one replaces it.
        """
        import evb
        if not self.events:
            return None
        mask = None
        for event in self.events:
            if event.time > elapsed:
                break
            if event.type == evb.EVENT_LIPSYNC:
                # Silence is drawn as the closed mouth; drawn literally, a
                # mask of 0 takes the head with it (see evb.py).
                mask = evb.effective(event.param)
        return mask

    def EventData(self, index):
        """The groups on event `index`.

        character.CAnimReciever keeps its own running index and asks for each
        event in turn, then walks the result looking for 'SoundName' -- so
        this has to be indexed exactly as the file is ordered.
        """
        try:
            return self.events[index].elements
        except (TypeError, IndexError):
            return None

    def __len__(self):
        return len(self.events or ())

    def __nonzero__(self):
        return True


# Every playback ever made, so the loop can ask each one what has come due.
# Weak enough in practice: a room's streams are replaced as animations change
# and a finished one costs a single comparison per frame.
_playbacks = []


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

    _next_identity = [1]

    def __init__(self, name=""):
        _stub.Stub.__init__(self, "yagaevents.EventStreamPlayback")
        self.stream = None
        self.name = name
        # CAnimReciever.Raise only answers events whose deviceID matches this,
        # which is how one receiver ignores every other stream in the room.
        self.identity = EventStreamPlayback._next_identity[0]
        EventStreamPlayback._next_identity[0] += 1
        object.__setattr__(self, "_started", None)
        object.__setattr__(self, "_offset", 0.0)
        object.__setattr__(self, "_fired", 0)
        _playbacks.append(self)

    def Run(self, scene=None, *a, **kw):
        object.__setattr__(self, "_started", time.time())
        object.__setattr__(self, "_fired", 0)

    def Stop(self, scene=None, *a, **kw):
        object.__setattr__(self, "_started", None)

    def EventData(self, index):
        """The groups on one event.

        CAnimReciever asks the *playback* for this, not the stream:

            data = self.streamPlayback.EventData(self.idx)
            for element in data:
                if 'SoundName' == element.name: ...

        so without this the name resolved to an auto-created stub, which
        iterates as empty -- every animation lost its sound effects and
        nothing said so.
        """
        stream = self.stream
        if not isinstance(stream, IEventStream):
            return None
        return stream.EventData(index)

    def Due(self):
        """How many events have come due since the last time we asked.

        Timed off the wall clock rather than by accumulating the deltas the
        room passes to Seek: a slow frame then costs nothing, where summing
        deltas would let a long animation drift away from its own sound
        effects.
        """
        started = object.__getattribute__(self, "_started")
        stream = self.stream
        if started is None or not isinstance(stream, IEventStream):
            return 0
        if not stream.events:
            return 0
        elapsed = time.time() - started + object.__getattribute__(self, "_offset")
        fired = object.__getattribute__(self, "_fired")
        due = 0
        while fired + due < len(stream.events) and                 stream.events[fired + due].time <= elapsed:
            due += 1
        if due:
            object.__setattr__(self, "_fired", fired + due)
        return due

    def Seek(self, offset=0.0, *a, **kw):
        try:
            object.__setattr__(self, "_offset", float(offset))
        except (TypeError, ValueError):
            pass

    # How long past its last event a stream keeps speaking.  At least one
    # frame at the game's 10 fps, so the final shape -- usually ROOT, the
    # mouth closing -- is always applied before the stream goes quiet.
    TAIL = 0.25

    def CurrentMask(self):
        """The mouth shape this stream wants now, or None once it is done.

        Going quiet at the end matters.  The game does not always detach a
        finished stream: the cape sequence runs one line straight into the
        next without the StopTalkie that would remove it, so the talking
        sprite ends up carrying both.  A finished stream that kept answering
        with its last shape held Sam's mouth shut for the whole ten-second
        line that followed.
        """
        started = object.__getattribute__(self, "_started")
        stream = self.stream
        if started is None or not isinstance(stream, IEventStream):
            return None
        elapsed = time.time() - started + object.__getattribute__(self, "_offset")
        if elapsed > stream.duration + self.TAIL:
            return None
        return stream.MaskAt(elapsed)

    def __nonzero__(self):
        return True


_mod.IEventStream = IEventStream
_mod.EventStreamPlayback = EventStreamPlayback

_mod.__wrapped_module__ = sys.modules[__name__]
sys.modules[__name__] = _mod
