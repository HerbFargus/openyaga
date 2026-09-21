# -*- coding: utf-8 -*-
"""Tracing stubs standing in for the native yaga* engine modules.

The point of these is NOT to work.  It is to let the game's own scripts run far
enough to tell us, in their own order, which parts of the engine they need --
so the worklist comes from the game rather than from guesswork.

Every attribute access, instantiation, call and assignment is recorded.  Nothing
is hand-written per module: attributes spring into existence on first use, so a
name we never anticipated still gets logged rather than raising AttributeError.

Two constraints shaped the design:

* Python 2.7 has no module-level ``__getattr__`` (that is 3.7+), so each shim
  module replaces itself in ``sys.modules`` with a ``StubModule`` instance.
* The game *subclasses* six engine types -- IRenderTarget, IEventReciever,
  IContentHandler, ISceneEventSink, ISprite and Point -- so an auto-created
  attribute has to be a real class, not an instance.  Hence the metaclass.

Log output goes to a file, never stdout: boot.py replaces sys.stdout with its
own redirector early on, and would swallow it.
"""

import os
import sys
import time
import traceback


class TraceLog(object):
    """Ordered record of everything the game asked of the engine."""

    def __init__(self):
        self.events = []        # (seq, kind, target, detail)
        self.counts = {}        # target -> number of times touched
        self.seq = 0
        self.stream = None

    def open(self, path):
        d = os.path.dirname(path)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        self.stream = open(path, "w")

    def record(self, kind, target, detail=""):
        self.seq += 1
        self.counts[target] = self.counts.get(target, 0) + 1
        self.events.append((self.seq, kind, target, detail))
        if self.stream:
            self.stream.write("%05d  %-8s %-46s %s\n" % (self.seq, kind, target, detail))
            self.stream.flush()
        return self.seq

    def note(self, text):
        if self.stream:
            self.stream.write("\n%s\n\n" % text)
            self.stream.flush()

    def close(self):
        if self.stream:
            self.stream.close()
            self.stream = None


LOG = TraceLog()

_MAX_REPR = 40


def _brief(value):
    """A short, safe repr -- game objects can be huge or explode on repr()."""
    try:
        if isinstance(value, Stub) or isinstance(value, type):
            return getattr(value, "_yaga_name", None) or getattr(value, "__name__", "?")
        text = repr(value)
    except Exception:
        return "<unreprable>"
    if len(text) > _MAX_REPR:
        text = text[:_MAX_REPR - 3] + "..."
    return text


def _args(a, kw):
    parts = [_brief(x) for x in a]
    parts += ["%s=%s" % (k, _brief(v)) for k, v in sorted(kw.items())]
    return "(" + ", ".join(parts) + ")"


class Stub(object):
    """A permissive value: callable, attribute-bearing, quietly falsy.

    Falsy and empty on purpose -- `if x:` and `for x in y:` then take the short
    path, which gets the boot sequence further along instead of hanging.
    """

    def __init__(self, name):
        object.__setattr__(self, "_yaga_name", name)
        object.__setattr__(self, "_yaga_attrs", {})

    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        attrs = object.__getattribute__(self, "_yaga_attrs")
        if name not in attrs:
            full = "%s.%s" % (object.__getattribute__(self, "_yaga_name"), name)
            LOG.record("get", full)
            attrs[name] = Stub(full)
        return attrs[name]

    def __setattr__(self, name, value):
        full = "%s.%s" % (object.__getattribute__(self, "_yaga_name"), name)
        LOG.record("set", full, "= %s" % _brief(value))
        object.__getattribute__(self, "_yaga_attrs")[name] = value

    def __call__(self, *a, **kw):
        name = object.__getattribute__(self, "_yaga_name")
        LOG.record("call", name, _args(a, kw))
        return Stub(name + "()")

    # Keep the game moving rather than raising.  Truthy: the game asserts on
    # engine objects constantly (`assert __debug__ and self.idevMouse`), and a
    # falsy stand-in fails every one of those.
    def __nonzero__(self):
        return True

    def __len__(self):
        return 0

    def __iter__(self):
        return iter(())

    def __int__(self):
        return 0

    def __float__(self):
        return 0.0

    def __index__(self):
        return 0

    def __add__(self, other):
        return self

    __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = __add__

    def __div__(self, other):
        return self

    __truediv__ = __rdiv__ = __div__

    def __getitem__(self, key):
        return self.__getattr__("item")

    def __str__(self):
        return "<%s>" % object.__getattribute__(self, "_yaga_name")

    __repr__ = __str__


class _StubMeta(type):
    """Metaclass so auto-created engine types can be subclassed AND hold enums.

    `yagaevents.EEventClass.CLASS_TIMER` and
    `class CGameCodeCallback(yagaevents.IEventReciever)` must both work, which
    means every generated attribute has to be a class with attributes of its own.
    """

    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        full = "%s.%s" % (cls._yaga_name, name)
        LOG.record("const", full)
        value = Stub(full)
        type.__setattr__(cls, name, value)   # cache: enums must compare stably
        return value

    def __repr__(cls):
        return "<class %s>" % cls._yaga_name


def make_type(name):
    """Build a stub engine class that logs construction and every method call."""

    def __init__(self, *a, **kw):
        LOG.record("new", name, _args(a, kw))
        object.__setattr__(self, "_yaga_name", name + "()")
        object.__setattr__(self, "_yaga_attrs", {})

    return _StubMeta(str(name.split(".")[-1]), (Stub,), {
        "__init__": __init__,
        "_yaga_name": name,
        "__module__": name.split(".")[0],
    })


class StubModule(object):
    """Stands in for one native yaga* module in sys.modules."""

    def __init__(self, name):
        object.__setattr__(self, "__name__", name)
        object.__setattr__(self, "_types", {})

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        types = object.__getattribute__(self, "_types")
        if name not in types:
            full = "%s.%s" % (object.__getattribute__(self, "__name__"), name)
            LOG.record("lookup", full)
            types[name] = make_type(full)
        return types[name]

    def __setattr__(self, name, value):
        object.__getattribute__(self, "_types")[name] = value

    def __repr__(self):
        return "<stub module %s>" % object.__getattribute__(self, "__name__")


def install(module_name):
    """Replace the calling module with a tracing stub.

    The real module object is kept alive on the stub: dropping its last
    reference makes Python 2 tear it down and null out every global, which
    breaks any function still holding those globals.
    """
    stub = StubModule(module_name)
    object.__getattribute__(stub, "_types")["__wrapped_module__"] = sys.modules.get(module_name)
    sys.modules[module_name] = stub
