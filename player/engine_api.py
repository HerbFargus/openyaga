#!/usr/bin/env python
"""Write ENGINE_API.md: the engine interface the game's scripts use.

    .venv-sdl2\\Scripts\\python.exe engine_api.py [trace.log ...]

Three sources, cross-checked:

  * the recovered scripts (gamecache/scripts): every `yagaX.Name` they
    reference, and every attribute name they use anywhere;
  * the shim (yagashim/): what each name is here -- class, function or
    constant -- with the members it implements and their documentation;
  * trace logs, optional: how often a run touched each name.

A shim member counts as engine API when the scripts use its name somewhere.
That is a name match, not a type check, so it can over-count a common name
like `position`; it never under-counts.  Names the scripts reference that the
shim does not define are listed as left to stubs.

Python 2.7 (it imports the shim).  Writes only names and counts, never game
code.
"""

import inspect
import io
import os
import re
import sys
import tokenize
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
SHIM = os.path.join(HERE, "yagashim")
SCRIPTS = os.path.join(HERE, "gamecache", "scripts")
OUT = os.path.join(os.path.dirname(HERE), "ENGINE_API.md")
RULES = os.path.join(HERE, "engine_rules.md")

MODULES = ["yaga", "yagaevents", "yagagraphics", "yagasprite", "yagascene",
           "yagasound", "yagares", "yagaxml", "yagafont", "yagainput",
           "yagacollisionlib"]
_SKIP_SCRIPTS = ("_boot",)


# -- the scripts ---------------------------------------------------------------
SPELLED = defaultdict(lambda: defaultdict(int))   # (module, class) -> {member: refs}

def scan_scripts():
    """({module: {name: (refs, files)}}, {attribute: refs})"""
    refs = defaultdict(lambda: defaultdict(lambda: [0, set()]))
    attrs = defaultdict(int)
    for dirpath, _dirs, files in os.walk(SCRIPTS):
        if any(part in dirpath for part in _SKIP_SCRIPTS):
            continue
        for f in files:
            if not f.endswith(".py"):
                continue
            path = os.path.join(dirpath, f)
            rel = os.path.relpath(path, SCRIPTS)
            with io.open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            try:
                toks = [t for t in tokenize.generate_tokens(io.StringIO(text).readline)
                        if t[0] in (tokenize.NAME, tokenize.OP)]
            except (tokenize.TokenError, IndentationError):
                continue
            for i in range(len(toks) - 2):
                a, dot, b = toks[i][1], toks[i + 1][1], toks[i + 2][1]
                if dot != "." or toks[i + 2][0] != tokenize.NAME:
                    continue
                attrs[b] += 1
                if a in MODULES:
                    entry = refs[a][b]
                    entry[0] += 1
                    entry[1].add(rel)
                    # module.Class.MEMBER: the constants, spelled out
                    if (i + 4 < len(toks) and toks[i + 3][1] == "."
                            and toks[i + 4][0] == tokenize.NAME):
                        SPELLED[(a, b)][toks[i + 4][1]] += 1
    return refs, attrs


# -- traces -------------------------------------------------------------------
_TRACE = re.compile(r"^\s*\d+\s+(new|call|set|get|lookup)\s+(yaga[a-z]*)\.([A-Za-z_][\w]*)(?:\(\))?(?:\.([A-Za-z_]\w*))?")


_ATTRIBUTES = set()      # (module, class, member) seen written or read
_CALLED = set()          # ... and seen called


def scan_traces(paths):
    """{(module, name, member or None): count}"""
    counts = defaultdict(int)
    for path in paths:
        with open(path) as fh:
            for line in fh:
                m = _TRACE.match(line)
                if m:
                    key = (m.group(2), m.group(3), m.group(4))
                    counts[key] += 1
                    if m.group(1) in ("set", "get") and key[2]:
                        _ATTRIBUTES.add(key)
                    elif m.group(1) == "call" and key[2]:
                        _CALLED.add(key)
    return counts


# -- the shim -----------------------------------------------------------------
def load_shim():
    sys.path.insert(0, SHIM)
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import _stub
    shim = {}
    for name in MODULES:
        try:
            __import__(name)
        except Exception as exc:
            shim[name] = (None, {}, "could not import: %s" % exc)
            continue
        mod = sys.modules[name]
        types = dict(object.__getattribute__(mod, "_types")) if isinstance(mod, _stub.StubModule) else {}
        real = sys.modules.get("_real_" + name) or _real_module(name)
        doc = inspect.getdoc(real) if real is not None else ""
        shim[name] = (real, types, doc or "")
    return shim


def _real_module(name):
    """The module object behind the stub, for its docstring."""
    import imp
    try:
        found = imp.find_module(name, [SHIM])
        return type(sys)(name, _module_docstring(found[1]))
    except ImportError:
        return None


def _module_docstring(path):
    import ast
    with open(path) as fh:
        return ast.get_docstring(ast.parse(fh.read())) or ""


def first_paragraph(doc, limit=240):
    if not doc:
        return ""
    para = doc.strip().split("\n\n")[0]
    para = " ".join(line.strip() for line in para.splitlines())
    return para if len(para) <= limit else para[:limit - 3].rsplit(" ", 1)[0] + "..."


def classify(obj):
    if inspect.isclass(obj):
        return "class"
    if inspect.isfunction(obj) or inspect.isbuiltin(obj):
        return "function"
    return "constant"


def members(cls, documented=()):
    """Public members defined on the class or its shim bases (not Stub/object,
    and not bases that get a section of their own)."""
    import _stub
    seen = {}
    for klass in inspect.getmro(cls):
        if klass in (object, _stub.Stub) or klass.__module__ in ("__builtin__",):
            continue
        if klass is not cls and klass in documented:
            continue
        for key, value in vars(klass).items():
            if key.startswith("_") or key in seen:
                continue
            if isinstance(value, property):
                seen[key] = ("property", inspect.getdoc(value.fget) or "")
            elif inspect.isfunction(value) or isinstance(value, (staticmethod, classmethod)):
                func = value.__func__ if hasattr(value, "__func__") else value
                seen[key] = ("method", inspect.getdoc(func) or "")
            else:
                seen[key] = ("attribute", "")
    return seen


# -- writing ------------------------------------------------------------------
def md_escape(text):
    return text.replace("|", "\\|")


def write(refs, attrs, traces, shim, trace_paths):
    lines = []
    add = lines.append
    add("# The Yaga engine API, as Pajama Sam 4 uses it")
    add("")
    add("Generated by `player/engine_api.py`; do not edit by hand -- the rules in "
        "the next section come from `player/engine_rules.md`.")
    add("")
    add("Yaga is a C++ engine driving Python game scripts. The scripts import "
        "eleven native modules, and this is everything they reference in them, "
        "with what the openyaga shim does for each. An engine that runs the "
        "game has to provide the same names with the same behaviour.")
    add("")
    add("- **Refs** counts references to `module.Name` in the recovered scripts "
        "(and the number of script files). For class members it counts uses of "
        "the member's *name* anywhere in the scripts -- a name match, so common "
        "names over-count.")
    if trace_paths:
        add("- **Trace** counts engine events touching the name in %d trace log(s) "
            "from real play: creations, calls and attribute writes the shim logs. "
            "Blank means the shim does not log it, not that it is unused." % len(trace_paths))
    add("- A member the scripts never name is left out: it is the shim's own "
        "machinery, not engine API.")
    add("")
    if os.path.isfile(RULES):
        with io.open(RULES, encoding="utf-8") as fh:
            add(fh.read().rstrip())
        add("")
    add("## Modules")
    add("")
    total_names = total_gaps = 0
    for modname in MODULES:
        real, types, doc = shim[modname]
        used = refs.get(modname, {})
        names = sorted(set(used) | set(n for n in types if not n.startswith("_")),
                       key=lambda n: (-used.get(n, [0])[0], n))
        add("### `%s`" % modname)
        add("")
        summary = first_paragraph(doc, 500)
        if summary:
            add(summary)
            add("")
        rows, gaps = [], []
        for name in names:
            count, files = used.get(name, [0, set()])
            obj = types.get(name)
            if obj is None:
                if count:
                    gaps.append((name, count, len(files)))
                continue
            if not count:
                continue                      # the shim's own helper
            kind = classify(obj)
            rows.append((name, kind, count, len(files), obj))
        if rows:
            add("| Name | Kind | Refs | Trace | What it is |")
            add("|---|---|---|---|---|")
            for name, kind, count, nfiles, obj in rows:
                tcount = sum(v for (m, n, _x), v in traces.items() if m == modname and n == name)
                desc = first_paragraph(inspect.getdoc(obj) or "", 200) if kind != "constant" else repr(obj)[:60]
                add("| `%s` | %s | %s | %s | %s |" % (
                    name, kind, ("%d (%d files)" % (count, nfiles)) if count else "",
                    tcount or "", md_escape(desc)))
            add("")
        total_names += len(rows)
        documented = set(obj for _n, k, _c, _f, obj in rows if k == "class")
        for name, kind, _count, _nfiles, obj in rows:
            if kind != "class":
                continue
            found = members(obj, documented)
            # Plain attributes live on instances, where introspection cannot
            # see them; the traces record every write to them.
            # (Written or read, not called: calls are to methods, which the
            # class or a documented base already lists.)
            for (m, n, member) in _ATTRIBUTES:
                if m == modname and n == name and not member.startswith("_")                         and member not in found and not callable(getattr(obj, member, None)):
                    if (m, n, member) in _CALLED:
                        # Called, but the class defines nothing by that name:
                        # a stub answers.  The game gets by without it.
                        found[member] = ("method (stub)", "")
                    else:
                        found[member] = ("attribute", "")
            # Constants the scripts spell out in full, which the shim may
            # only create on first use.
            for member in SPELLED.get((modname, name), {}):
                if member not in found:
                    value = getattr(obj, member, None)
                    if value == "%s.%s" % (name, member) or value is None:
                        # The shim invents these on first use: the real value
                        # is unknown, and the game only compares against it.
                        note = "value unknown; the game only compares against it"
                    else:
                        note = repr(value)
                    found[member] = ("constant", note)
            used_members = []
            for member, (mkind, mdoc) in sorted(found.items()):
                n = attrs.get(member, 0)
                if not n:
                    continue
                t = traces.get((modname, name, member), 0)
                used_members.append((member, mkind, n, t, mdoc))
            if not used_members:
                continue
            add("<details><summary><code>%s.%s</code> -- %d members the scripts use</summary>"
                % (modname, name, len(used_members)))
            add("")
            add("| Member | Kind | Refs (by name) | Trace | What it does |")
            add("|---|---|---|---|---|")
            for member, mkind, n, t, mdoc in used_members:
                add("| `%s` | %s | %d | %s | %s |" % (member, mkind, n, t or "",
                                                    md_escape(first_paragraph(mdoc, 200))))
            add("")
            add("</details>")
            add("")
        if gaps:
            total_gaps += len(gaps)
            add("**Left to stubs.** Referenced by the scripts but not defined in "
                "the shim, so they resolve to a tracing stub that accepts "
                "anything -- and Pajama Sam 4 plays to the end regardless. "
                "Mostly flag enums and format-handler registrations: " +
                ", ".join("`%s` (%d)" % (n, c) for n, c, _f in gaps))
            add("")
    add("---")
    add("")
    add("%d names across %d modules; %d more referenced names left to stubs."
        % (total_names, len(MODULES), total_gaps))
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(u"\n".join(l if isinstance(l, unicode) else l.decode("utf-8") for l in lines) + u"\n")
    return total_names, total_gaps


def main(argv):
    if sys.version_info[0] != 2:
        sys.exit("engine_api.py imports the shim, so it needs Python 2.7")
    if not os.path.isdir(SCRIPTS):
        sys.exit("no recovered scripts at %s -- run setup first" % SCRIPTS)
    trace_paths = argv[1:]
    refs, attrs = scan_scripts()
    traces = scan_traces(trace_paths)
    shim = load_shim()
    names, gaps = write(refs, attrs, traces, shim, trace_paths)
    print("wrote %s: %d names, %d gaps" % (OUT, names, gaps))


if __name__ == "__main__":
    main(sys.argv)
