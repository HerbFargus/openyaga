# -*- coding: latin-1 -*-
"""Real stand-in for the native yagaxml module.

The game drives this in a SAX style, and the whole contract is four names:

    parser = yagaxml.XmlSystem().CreateParser()
    parser.contentHandler = handler      # a yagaxml.IContentHandler subclass
    if not parser.ParseFile(path):       # falsy on failure
        raise parser.errorString, path

with the handler providing StartElement(name, attrs) and EndElement(name).
`attrs` is a sequence of objects with .name and .value -- not a dict -- which
is how every loader in the game reads it:

    for attr in attrs:
        attrMap[attr.name] = attr.value

Twelve classes across the game subclass IContentHandler.  There is no character
data handler anywhere, which fits the data: these files carry their content in
attributes, as in `<name value = "exitArrowDoor"/>`.

Implemented on expat, which is what the original used too -- the retail install
ships expat.dll next to the game.
"""

import sys
import xml.parsers.expat

import _stub
import resources

_mod = _stub.StubModule(__name__)


class Attribute(object):
    """One attribute, as the game's loaders expect to read it."""

    __slots__ = ("name", "value")

    def __init__(self, name, value):
        self.name = name
        self.value = value

    def __repr__(self):
        return "%s=%r" % (self.name, self.value)


class IContentHandler(object):
    """Base class for the game's twelve XML loaders."""

    def __init__(self):
        pass

    def StartElement(self, name, attrs):
        pass

    def EndElement(self, name):
        pass


class Parser(object):
    def __init__(self):
        self.contentHandler = None
        self.errorString = ""

    def ParseFile(self, path):
        """Parse a game path.  Returns 1 on success, 0 on failure."""
        data = resources.read(path)
        if data is None:
            self.errorString = "could not find '%s'" % path
            _stub.LOG.record("call", "yagaxml.Parser.ParseFile",
                             "(%r) -> NOT FOUND" % str(path))
            return 0

        handler = self.contentHandler
        parser = xml.parsers.expat.ParserCreate()
        # Ordered attributes keep document order and give us a flat
        # [name, value, name, value, ...] list to wrap.
        parser.ordered_attributes = 1

        if handler is not None:
            def start(name, attrlist):
                attrs = [Attribute(attrlist[i], attrlist[i + 1])
                         for i in range(0, len(attrlist), 2)]
                handler.StartElement(name, attrs)

            parser.StartElementHandler = start
            parser.EndElementHandler = handler.EndElement

        try:
            parser.Parse(data, 1)
        except xml.parsers.expat.ExpatError, exc:
            self.errorString = "%s in '%s'" % (exc, path)
            _stub.LOG.record("call", "yagaxml.Parser.ParseFile",
                             "(%r) -> %s" % (str(path), exc))
            return 0

        _stub.LOG.record("call", "yagaxml.Parser.ParseFile",
                         "(%r) -> ok, %d bytes" % (str(path), len(data)))
        return 1


class _XmlSystem(object):
    def CreateParser(self):
        return Parser()


_system = None


def XmlSystem():
    global _system
    if _system is None:
        _system = _XmlSystem()
    return _system


_mod.Attribute = Attribute
_mod.IContentHandler = IContentHandler
_mod.Parser = Parser
_mod.XmlSystem = XmlSystem

# Keep the real module alive; see yagagraphics for why.
_mod.__wrapped_module__ = sys.modules[__name__]
sys.modules[__name__] = _mod
