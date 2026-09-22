#!/usr/bin/env python
"""Write ENGINE_API.md: the engine interface the games' scripts use.

    .venv-sdl2\\Scripts\\python.exe engine_api.py [trace.log ...]

Three sources, cross-checked:

  * each game's recovered scripts (every gamecache*/scripts beside the
    player): every `yagaX.Name` they reference, and every attribute name
    they use anywhere -- counted per game;
  * the shim (yagashim/): what each name is here -- class, function or
    constant -- with the members it implements and their documentation;
  * trace logs, optional: how often a run touched each name.  Each trace
    is matched to its game by the '=== title ===' line it starts with.

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

def scan_scripts(scripts=SCRIPTS):
    """({module: {name: (refs, files)}}, {attribute: refs}) for one game."""
    refs = defaultdict(lambda: defaultdict(lambda: [0, set()]))
    attrs = defaultdict(int)
    for dirpath, _dirs, files in os.walk(scripts):
        if any(part in dirpath for part in _SKIP_SCRIPTS):
            continue
        for f in files:
            if not f.endswith(".py"):
                continue
            path = os.path.join(dirpath, f)
            rel = os.path.relpath(path, scripts)
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


SHORT = {"pajama4": "Pajama Sam 4", "puttpbs": "Putt-Putt PBS"}


def discover_games():
    """[(label, title, scripts dir)] for every game set up beside the player."""
    import json
    games = []
    for name in sorted(os.listdir(HERE)):
        manifest = os.path.join(HERE, name, "manifest.json")
        scripts = os.path.join(HERE, name, "scripts")
        if not (name.startswith("gamecache") and os.path.isfile(manifest)
                and os.path.isdir(scripts)):
            continue
        with open(manifest) as fh:
            m = json.load(fh)
        title = m.get("title") or name
        games.append((SHORT.get(m.get("game_id"), title), title, scripts))
    return games


def trace_game(path, games):
    """Which game a trace is from, by its '=== title ===' line."""
    with open(path) as fh:
        for n, line in enumerate(fh):
            if "=== " in line and " ===" in line:
                title = line.split("=== ", 1)[1].rsplit(" ===", 1)[0].strip()
                for label, gtitle, _s in games:
                    if gtitle == title:
                        return label
            if n > 200:
                break
    return None


def _refs_cell(entry):
    count, files = entry if entry else (0, set())
    return ("%d (%d files)" % (count, len(files))) if count else ""


def write(games, traces, shim, trace_paths):
    """games: [(label, refs, attrs)]; trace_paths: {path: game label}."""
    labels = [g[0] for g in games]
    lines = []
    add = lines.append
    add("# The Yaga engine API, as %s use it" % " and ".join(labels))
    add("")
    add("Generated by `player/engine_api.py`; do not edit by hand -- the rules in "
        "the next section come from `player/engine_rules.md`.")
    add("")
    add("Yaga is a C++ engine driving Python game scripts. The scripts import "
        "eleven native modules, and this is everything the games reference in "
        "them, with what the openyaga shim does for each. An engine that runs "
        "the games has to provide the same names with the same behaviour.")
    add("")
    add("- **%s** count references to `module.Name` in each game's recovered "
        "scripts (and the number of script files); a blank means that game "
        "never names it. For class members they count uses of the member's "
        "*name* anywhere in the scripts -- a name match, so common names "
        "over-count." % " / ".join(labels))
    if trace_paths:
        by_game = {}
        for label in trace_paths.values():
            by_game[label or "unidentified"] = by_game.get(label or "unidentified", 0) + 1
        add("- **Trace** counts engine events touching the name in trace logs "
            "from real play (%s): creations, calls and attribute writes the "
            "shim logs. Blank means the shim does not log it, not that it is "
            "unused." % ", ".join("%d from %s" % (n, l) for l, n in sorted(by_game.items())))
    add("- A member no script names is left out: it is the shim's own "
        "machinery, not engine API.")
    add("")
    if os.path.isfile(RULES):
        with io.open(RULES, encoding="utf-8") as fh:
            add(fh.read().rstrip())
        add("")

    head = "| Name | Kind | " + " | ".join(labels) + " | Trace | What it is |"
    mhead = "| Member | Kind | " + " | ".join(labels) + " | Trace | What it does |"
    rule = "|---|---|" + "---|" * len(labels) + "---|---|"
    add("## Modules")
    add("")
    totals = {"names": 0, "shared": 0, "gaps": 0}
    only = dict((l, 0) for l in labels)
    for modname in MODULES:
        real, types, doc = shim[modname]
        used = [g[1].get(modname, {}) for g in games]
        every = set(n for u in used for n in u) | set(n for n in types if not n.startswith("_"))
        names = sorted(every, key=lambda n: (-sum(u.get(n, [0])[0] for u in used), n))
        add("### `%s`" % modname)
        add("")
        summary = first_paragraph(doc, 500)
        if summary:
            add(summary)
            add("")
        rows, gaps = [], []
        for name in names:
            cells = [u.get(name) for u in used]
            present = [bool(c and c[0]) for c in cells]
            obj = types.get(name)
            if obj is None:
                if any(present):
                    gaps.append((name, [l for l, p in zip(labels, present) if p]))
                continue
            if not any(present):
                continue                      # the shim's own helper
            rows.append((name, classify(obj), cells, obj))
            if all(present):
                totals["shared"] += 1
            else:
                for l, p in zip(labels, present):
                    if p:
                        only[l] += 1
        if rows:
            add(head)
            add(rule)
            for name, kind, cells, obj in rows:
                tcount = sum(v for (m, n, _x), v in traces.items() if m == modname and n == name)
                desc = (first_paragraph(inspect.getdoc(obj) or "", 200)
                        if kind != "constant" else repr(obj)[:60])
                add("| `%s` | %s | %s | %s | %s |" % (
                    name, kind, " | ".join(_refs_cell(c) for c in cells),
                    tcount or "", md_escape(desc)))
            add("")
        totals["names"] += len(rows)
        documented = set(obj for _n, k, _c, obj in rows if k == "class")
        for name, kind, _cells, obj in rows:
            if kind != "class":
                continue
            found = members(obj, documented)
            # Plain attributes live on instances, where introspection cannot
            # see them; the traces record every write to them.  (Written or
            # read, not called: calls are to methods the class already lists.)
            for (m, n, member) in _ATTRIBUTES:
                if (m == modname and n == name and not member.startswith("_")
                        and member not in found
                        and not callable(getattr(obj, member, None))):
                    if (m, n, member) in _CALLED:
                        # Called, but the class defines nothing by that name:
                        # a stub answers.  The games get by without it.
                        found[member] = ("method (stub)", "")
                    else:
                        found[member] = ("attribute", "")
            # Constants the scripts spell out in full, which the shim may
            # only create on first use.
            for member in SPELLED.get((modname, name), {}):
                if member not in found:
                    value = getattr(obj, member, None)
                    if value == "%s.%s" % (name, member) or value is None:
                        note = "value unknown; the games only compare against it"
                    else:
                        note = repr(value)
                    found[member] = ("constant", note)
            used_members = []
            for member, (mkind, mdoc) in sorted(found.items()):
                counts = [g[2].get(member, 0) for g in games]
                if not any(counts):
                    continue
                used_members.append((member, mkind, counts,
                                     traces.get((modname, name, member), 0), mdoc))
            if not used_members:
                continue
            add("<details><summary><code>%s.%s</code> -- %d members the scripts use</summary>"
                % (modname, name, len(used_members)))
            add("")
            add(mhead)
            add(rule)
            for member, mkind, counts, t, mdoc in used_members:
                add("| `%s` | %s | %s | %s | %s |" % (
                    member, mkind, " | ".join(str(c) if c else "" for c in counts),
                    t or "", md_escape(first_paragraph(mdoc, 200))))
            add("")
            add("</details>")
            add("")
        if gaps:
            totals["gaps"] += len(gaps)
            add("**Left to stubs.** Referenced by the scripts but not defined in "
                "the shim, so they resolve to a tracing stub that accepts "
                "anything -- and the games play to the end regardless. Mostly "
                "flag enums and format-handler registrations: " +
                ", ".join("`%s`%s" % (n, "" if len(ls) == len(labels)
                                      else " (%s only)" % ", ".join(ls))
                          for n, ls in gaps))
            add("")
    add("---")
    add("")
    add("%d names across %d modules: %d used by %s, %s. %d more referenced "
        "names left to stubs." % (
            totals["names"], len(MODULES), totals["shared"],
            "both games" if len(labels) == 2 else "every game",
            ", ".join("%d by %s only" % (only[l], l) for l in labels),
            totals["gaps"]))
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(u"\n".join(l if isinstance(l, unicode) else l.decode("utf-8")
                            for l in lines) + u"\n")
    return totals


def main(argv):
    if sys.version_info[0] != 2:
        sys.exit("engine_api.py imports the shim, so it needs Python 2.7")
    found = discover_games()
    if not found:
        sys.exit("no recovered scripts beside the player -- run setup first")
    games = []
    for label, _title, scripts in found:
        refs, attrs = scan_scripts(scripts)
        games.append((label, refs, attrs))
    trace_paths = dict((p, trace_game(p, found)) for p in argv[1:])
    traces = scan_traces(list(trace_paths))
    shim = load_shim()
    totals = write(games, traces, shim, trace_paths)
    print("wrote %s: %s" % (OUT, totals))


if __name__ == "__main__":
    main(sys.argv)
