# -*- coding: latin-1 -*-
"""Real stand-in for the native yagares module -- the engine's resource layer.

Yaga is built around a resource manager with one pluggable handler per asset
type.  During boot the game registers eight of them:

    PngHandler, MngHandler, RleHandler, TargaHandler   (yagagraphics)
    BinkHandler                                        (yagasprite)
    EvtHandler, EvbHandler                             (yagaevents)

Rather than model that indirection, this loads by signature -- the handler
registrations are recorded and otherwise ignored.

`Load` must return something FALSY when an asset is missing, because the sprite
manager relies on it:

    res = g_ResourceManager.Load(path.replace('.mng', '.rle'))
    if not res:
        res = g_ResourceManager.Load(path)

so every MNG request probes for an RLE of the same name first.
"""

import sys

import _stub
import decoders
import resources

_mod = _stub.StubModule(__name__)

_ANIM_EXTENSIONS = (".mng", ".rle")


class Resource(object):
    """One loaded asset.  Decoding is deferred until something wants pixels."""

    def __init__(self, path, data):
        self.path = path
        self.data = data
        self.size = len(data)
        self._anim = None
        self._failed = False

    @property
    def anim(self):
        if self._anim is None and not self._failed:
            try:
                self._anim = decoders.load(self.data, self.path)
            except Exception, exc:
                self._failed = True
                _stub.LOG.record("call", "yagares.Resource.decode",
                                 "(%r) -> %s" % (self.path, exc))
        return self._anim

    @property
    def isLoaded(self):
        # Loading is synchronous here, so anything that exists is ready.
        # pj_preload_manager polls this every tick while it warms a room.
        return True

    def __nonzero__(self):
        return True

    def __repr__(self):
        return "<Resource %s, %d bytes>" % (self.path, self.size)


class ResourceManager(object):
    def __init__(self):
        _stub.LOG.record("new", "yagares.ResourceManager", "()")
        self.handlers = []
        self.cacheBytes = 0
        self._cache = {}
        self._preloaded = []

    def RegisterFormatHandler(self, handler):
        self.handlers.append(handler)
        _stub.LOG.record("call", "yagares.ResourceManager.RegisterFormatHandler",
                         "(%s)" % _stub._brief(handler))

    def UnregisterFormatHandler(self, handler):
        if handler in self.handlers:
            self.handlers.remove(handler)

    def Load(self, path):
        key = str(path).lower()
        if key in self._cache:
            return self._cache[key]

        data = resources.read(path)
        if data is None:
            # Expected constantly: every .mng request probes for .rle first.
            # An event stream is different -- one that goes missing costs an
            # animation its sound effects, silently, so say so once.
            if key.endswith(".evt"):
                _stub.LOG.record("call", "yagares.ResourceManager.Load",
                                 "(%r) MISSING event stream" % str(path))
            self._cache[key] = 0
            return 0

        res = Resource(str(path), data)
        self._cache[key] = res
        self.cacheBytes += res.size
        _stub.LOG.record("call", "yagares.ResourceManager.Load",
                         "(%r) -> %d bytes" % (str(path), res.size))
        return res

    def LoadStream(self, path):
        return self.Load(path)

    def Preload(self, path):
        return self.Load(path)

    def FlushPreloadQueue(self):
        self._preloaded = []

    def Save(self, *a, **kw):
        _stub.LOG.record("call", "yagares.ResourceManager.Save", _stub._args(a, kw))


_mod.Resource = Resource
_mod.ResourceManager = ResourceManager

_mod.__wrapped_module__ = sys.modules[__name__]
sys.modules[__name__] = _mod
