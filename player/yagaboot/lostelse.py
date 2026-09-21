# -*- coding: utf-8 -*-
"""Find `else:` blocks the decompiler lost, by asking the bytecode.

The fourth way uncompyle6 gets this game wrong.  An `else:` whose body opens
with an `if` is folded into `elif`, and whatever followed that inner `if`
inside the else is dedented out of it -- so it runs on every path:

    ORIGINAL                                AS DECOMPILED
    if putty on cursor:                     if putty on cursor:
        self.UsePutty()                         self.UsePutty()
    else:                                   elif self.currentAnimation != ...:
        if self.currentAnimation != ...:        self.SetInRoot()
            self.SetInRoot()                self.GenericUseDialog()   <- always
        self.GenericUseDialog()

In the source the two readings look alike: an if/elif chain followed by a
statement at the if's level.  That shape is common and usually right.  The
bytecode tells them apart.  Every branch of an if-chain ends by jumping
forward past the rest of the chain:

    <cond 1>   JUMP_IF_FALSE -> L1
               <branch 1>   JUMP_FORWARD -> T1
    L1:        POP_TOP
    <cond 2>   JUMP_IF_FALSE -> L2
               <branch 2>   JUMP_FORWARD -> T2
    L2:        POP_TOP
    S:         <the statement after the chain>

In a genuine chain T1 is S: every branch falls through to it.  In the lost-
else shape branch 1 jumps *over* S -- T1 lies beyond it -- because S belonged
to the else and branch 1 never runs it.

So for each candidate: find the chain's first condition in the original
bytecode by the names it loads; walk the chain branch by branch, reading
where each one jumps when done; take the statement that begins right after
the last branch -- by position, since a line like `return true` repeats --
and check it loads what the source's statement loads.  All branches landing
on it is a genuine chain; branch 1 landing beyond it is a lost else; anything
else is reported as undetermined rather than guessed at.

A lost else is harmless when what it lost is a bare `return` and branch 1
only skips it to reach the end of the function anyway, and those are
counted as fine.
"""

from __future__ import annotations

import io
import keyword
import re
import tokenize

from .constfix import _code_by_path, _paths_by_offset, _path_at

_LOADS = {"LOAD_FAST", "LOAD_GLOBAL", "LOAD_NAME", "LOAD_ATTR", "LOAD_CONST",
          "LOAD_DEREF"}
_STRUCTURAL = re.compile(r"(elif\b|else\b|except\b|finally\b|def\b|class\b|#|@)")
_IGNORE = set(keyword.kwlist) - {"None", "True", "False"}


def _tokens(text):
    """The names and constants an expression loads, in order."""
    out, prev, before = [], None, None
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.NAME and tok.string not in _IGNORE:
                out.append(tok.string)
            elif tok.type == tokenize.STRING:
                try:
                    out.append(eval(tok.string))           # a literal
                except Exception:
                    pass
            elif tok.type == tokenize.NUMBER:
                try:
                    value = eval(tok.string.rstrip("lL"))
                except Exception:
                    value = None
                if value is not None:
                    # The compiler folds a negated literal into one constant.
                    if prev and prev.string == "-" and (
                            before is None or before.type == tokenize.OP
                            and before.string not in (")", "]", "}")):
                        value = -value
                    out.append(value)
            if tok.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT):
                before, prev = prev, tok
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return out


def _statement_loads(stmt):
    """What a statement loads first: the iterable of a for, the condition of
    a while or if, the right-hand side of an assignment."""
    m = re.match(r"^for\b.*?\bin\b(.*):\s*$", stmt)
    if m:
        return _tokens(m.group(1))
    m = re.match(r"^(?:while|if)\b(.*):\s*$", stmt)
    if m:
        return _tokens(m.group(1))
    m = re.match(r"^[\w.\[\]'\", ]+?\s*(?<![=!<>])=(?!=)\s*(.*)$", stmt)
    if m:
        return _tokens(m.group(1))
    m = re.match(r"^(return|print)\b\s*(.*)$", stmt)
    if m:
        return _tokens(m.group(2))
    return _tokens(stmt)


def candidates(source):
    """Every if/elif chain followed by a statement at the chain's own level.

    Returns dicts with the line numbers (0-based) of the chain's `if`, each
    `elif`, the statement S, and the text needed to find them in bytecode.
    """
    lines = source.split("\n")
    indent = lambda s: len(s) - len(s.lstrip())
    found = []
    for i, line in enumerate(lines):
        m = re.match(r"^( *)elif\b(.*):\s*$", line)
        if not m:
            continue
        ind = len(m.group(1))
        j = i + 1
        while j < len(lines) and (not lines[j].strip() or indent(lines[j]) > ind):
            j += 1
        if j >= len(lines) or indent(lines[j]) != ind:
            continue
        stmt = lines[j].strip()
        if not stmt or _STRUCTURAL.match(stmt):
            continue
        # Walk back to the `if` that heads this chain, collecting elifs.
        elifs, k = [i], i - 1
        head = None
        while k >= 0:
            s = lines[k]
            if not s.strip() or indent(s) > ind:
                k -= 1
                continue
            if indent(s) < ind:
                break
            if re.match(r"^ *elif\b", s):
                elifs.insert(0, k)
            elif re.match(r"^ *if\b", s):
                head = k
                break
            else:
                break
            k -= 1
        if head is None:
            continue
        cond = re.match(r"^ *if\b(.*):\s*$", lines[head])
        if not cond:
            continue
        found.append({"if": head, "elifs": elifs, "stmt": j, "indent": ind,
                      "cond": cond.group(1).strip(), "stmt_text": stmt})
    return found


def _instructions(code):
    from xdis.bytecode import Bytecode
    from xdis.op_imports import get_opcode_module
    return list(Bytecode(code, get_opcode_module(2.2)))


def _same(source_tok, byte_tok):
    """A source token and a bytecode value name the same thing.  Private
    names are mangled in the bytecode: self.__x is stored as _Class__x."""
    if source_tok == byte_tok:
        return True
    if (isinstance(source_tok, str) and isinstance(byte_tok, str)
            and source_tok.startswith("__") and not source_tok.endswith("__")):
        return byte_tok.startswith("_") and byte_tok.endswith(source_tok)
    return False


def _find(insts, tokens, start=0):
    """Index of the first instruction of a contiguous run of loads matching
    `tokens`, searching from instruction index `start`; or None."""
    if not tokens:
        return None
    stream = [(n, ins.argval) for n, ins in enumerate(insts)
              if ins.opname in _LOADS and n >= start]
    width = len(tokens)
    for a in range(len(stream) - width + 1):
        if all(_same(tokens[b], stream[a + b][1]) for b in range(width)):
            return stream[a][0]
    return None


def _branch(insts, by_offset, n):
    """From instruction n, the next branch test: (jif index, false-target
    index, where the branch body jumps when done).  Short-circuit jumps
    inside and/or land somewhere not preceded by a closing jump, so they
    are passed over."""
    for m in range(n, len(insts)):
        ins = insts[m]
        if ins.opname not in ("JUMP_IF_FALSE", "JUMP_IF_TRUE"):
            continue
        if ins.argval <= ins.offset:
            continue
        t = by_offset.get(ins.argval)
        # A chained comparison (a <= b <= c) bails out to a ROT_TWO cleanup
        # that also sits behind a JUMP_FORWARD; it is not a branch.
        if t and insts[t].opname == "ROT_TWO":
            continue
        if t and insts[t - 1].opname == "JUMP_FORWARD":
            return m, t, insts[t - 1].argval
    return None


def _statement_after(insts, t):
    """The SET_LINENO that starts the first statement at or after index t.

    An empty line -- an `else:` or `pass` with nothing to compile -- leaves a
    SET_LINENO with no code before the next one; that is not a statement."""
    for m in range(t, len(insts)):
        if insts[m].opname != "SET_LINENO":
            continue
        if m + 1 < len(insts) and insts[m + 1].opname == "SET_LINENO":
            continue
        return m
    return None


def _exits(insts, by_offset, jump_offset):
    """True if the branch ending in the JUMP_FORWARD at jump_offset returns
    or raises first -- so it never reaches what follows the chain at all."""
    n = by_offset.get(jump_offset)
    if not n or insts[n - 1].opname not in ("RETURN_VALUE", "RAISE_VARARGS"):
        return False
    # ...and only by falling through.  A nested `if x: A else: return` ends
    # in a return too, but A jumps straight to the closing jump and so does
    # reach what follows.
    for ins in insts:
        if ins.opcode >= 90 and ins.argval == jump_offset and "JUMP" in ins.opname:
            return False
    return True


def verdict(code, cand):
    """('lost-else' | 'ok' | 'undetermined', evidence, per-branch targets)."""
    return _judge(code, cand)[:3]


def _judge(code, cand):
    """verdict(), plus the offset where the statement after the chain starts.

    Walks the chain in the bytecode branch by branch -- the source says how
    many there are -- and takes the statement that begins right after the
    last one.  That locates the following statement by position rather than
    by searching for its text, which a repeated line like `return true`
    would defeat.
    """
    try:
        insts = _instructions(code)
    except Exception as exc:
        return "undetermined", "no bytecode: %s" % exc, [], None
    by_offset = {ins.offset: n for n, ins in enumerate(insts)}
    branches = 1 + len(cand["elifs"])
    cond_tokens = _tokens(cand["cond"])
    if not cond_tokens:
        return "undetermined", "condition loads nothing to match on", [], None

    search, reasons = 0, []
    while True:
        at = _find(insts, cond_tokens, search)
        if at is None:
            return "undetermined", (reasons[-1] if reasons else
                                    "condition not found in bytecode"), [], None
        search = at + 1
        targets, closers, pos, ok = [], [], at, True
        for _b in range(branches):
            found = _branch(insts, by_offset, pos)
            if found is None:
                ok = False
                break
            _jif, false_at, jump = found
            targets.append(jump)
            closers.append(insts[false_at - 1].offset)
            pos = false_at            # the next branch starts here
        if not ok:
            reasons.append("could not walk %d branches" % branches)
            continue
        after = _statement_after(insts, pos)
        bare_return = cand["stmt_text"] in ("return", "return None")
        if after is None:
            if bare_return and _epilogue(insts, pos):
                # The chain ends the function, and the `return` after it is
                # one the decompiler added: the original has no statement
                # there.  Every path ends the function either way.
                return "ok", "chain ends the function", targets, None
            reasons.append("no statement after the chain")
            continue
        s_start = insts[after].offset

        # Sanity: the statement found there should be the one the source
        # shows.  A bare `return` loads nothing, so accept None/RETURN.
        stmt_tokens = _statement_loads(cand["stmt_text"])
        if stmt_tokens:
            if _find(insts, stmt_tokens, after) != _next_load(insts, after):
                reasons.append("statement after the chain is not %r"
                               % cand["stmt_text"][:30])
                continue
        t1 = targets[0]
        if all(t == s_start for t in targets):
            return "ok", "every branch falls through to %d" % s_start, targets, s_start
        skipping = [c for t, c in zip(targets, closers) if t > s_start]
        if skipping and all(_exits(insts, by_offset, c) for c in skipping):
            # Every branch that would skip the statement returns or raises
            # before it gets there, so where the statement sits changes
            # nothing.
            return ("ok", "the branches that skip it return first", targets,
                    s_start)
        if t1 > s_start:
            if bare_return and _epilogue(insts, by_offset.get(t1, 0)):
                # Branch 1 skips a `return` only to reach the end of the
                # function anyway -- the same outcome.
                return ("ok", "branch 1 skips a bare return to reach the "
                        "function's end at %d" % t1, targets, s_start)
            return ("lost-else", "branch 1 jumps to %d, past the statement at %d"
                    % (t1, s_start), targets, s_start)
        return ("undetermined", "branch targets %s, statement at %d"
                % (targets, s_start), targets, s_start)


def _epilogue(insts, n):
    """True if instruction n begins the function's closing `return None`,
    allowing for the POP_TOP a false branch leaves behind."""
    m = n
    while m < len(insts) and insts[m].opname in ("POP_TOP", "SET_LINENO"):
        m += 1
    return (m + 1 < len(insts) and insts[m].opname == "LOAD_CONST"
            and insts[m].argval is None and insts[m + 1].opname == "RETURN_VALUE")


def _next_load(insts, n):
    for m in range(n, len(insts)):
        if insts[m].opname in _LOADS:
            return m
    return None


def scan(source, code):
    """Every candidate in a module with its verdict and enclosing function."""
    by_path = _code_by_path(code)
    marks = _paths_by_offset(source)
    lines = source.split("\n")
    starts, total = [], 0
    for line in lines:
        starts.append(total)
        total += len(line) + 1
    out = []
    for cand in candidates(source):
        path = _path_at(marks, starts[cand["if"]])
        target = by_path.get(path) or by_path.get("")
        if target is None:
            v, why, targets = "undetermined", "no code object", []
        else:
            v, why, targets = verdict(target, cand)
        out.append(dict(cand, path=path or "<module>", verdict=v, why=why,
                        targets=targets))
    return out


# -- repair ------------------------------------------------------------------
#
# The bytecode also says how to put the else back.  Branch 1's closing jump
# lands where the lost else *ends*, and the branches split into two runs:
# the leading ones jump there, past the statement (they sit before the
# else), and the rest fall through to it (they are the else's own inner
# `if`).  With k leading branches:
#
#   k < branches:  the (k+1)th branch's `elif C:` becomes `else:` + `if C:`
#                  and everything after it, to the else's end, moves in.
#   k = branches:  the else lost its `if` too; a bare `else:` goes in front
#                  of the statement and the statements up to its end move in.
#
# Anything that does not split that cleanly is left alone and reported.

_CLOSERS = ("JUMP_ABSOLUTE", "JUMP_FORWARD", "POP_BLOCK", "RETURN_VALUE",
            "BREAK_LOOP", "END_FINALLY")


def _else_end(lines, cand, insts, by_offset, t1):
    """Line index where the lost else's body ends (exclusive), or None.

    Either a later statement at the chain's level starts at t1 -- matched by
    what it loads -- or t1 closes the enclosing block and the else runs to
    that block's end."""
    n = by_offset.get(t1)
    if n is None:
        return None
    while n < len(insts) and insts[n].opname in ("SET_LINENO", "POP_TOP"):
        n += 1
    at = _next_load(insts, n)
    ind = cand["indent"]
    indent = lambda s: len(s) - len(s.lstrip())
    j = cand["stmt"] + 1
    while j < len(lines):
        line = lines[j]
        text = line.strip()
        if not text or indent(line) > ind:
            j += 1
            continue
        if indent(line) < ind:
            break
        if not _STRUCTURAL.match(text):
            tokens = _statement_loads(text)
            if tokens and at is not None and _find(insts, tokens, n) == at:
                return j
        j += 1
    if n < len(insts) and (insts[n].opname in _CLOSERS or _epilogue(insts, n)):
        # t1 closes the block; stop before any trailing blank lines.
        while j > cand["stmt"] + 1 and not lines[j - 1].strip():
            j -= 1
        return j
    return None


def _restructure(lines, cand, k, end):
    ind = " " * cand["indent"]
    moved = lambda block: [("    " + l) if l.strip() else l for l in block]
    if k < 1 + len(cand["elifs"]):
        at = cand["elifs"][k - 1]
        cond = re.match(r"^ *elif\b(.*)$", lines[at]).group(1)
        head = [ind + "else:", ind + "    if" + cond]
        return lines[:at] + head + moved(lines[at + 1:end]) + lines[end:]
    at = cand["stmt"]
    return lines[:at] + [ind + "else:"] + moved(lines[at:end]) + lines[end:]


def repair(source, code):
    """Returns (source, fixes, problems).  Restores every lost else the
    bytecode confirms and can place; the rest go into problems."""
    by_path = _code_by_path(code)
    fixes, problems, refused = [], [], set()
    while True:
        lines = source.split("\n")
        marks = _paths_by_offset(source)
        starts, total = [], 0
        for line in lines:
            starts.append(total)
            total += len(line) + 1
        for cand in candidates(source):
            path = _path_at(marks, starts[cand["if"]])
            target = by_path.get(path) or by_path.get("")
            key = (path, lines[cand["if"]], lines[cand["stmt"]])
            if target is None or key in refused:
                continue
            v, why, targets, s_start = _judge(target, cand)
            if v != "lost-else":
                continue
            where = "%s: line %d" % (path or "<module>", cand["stmt"] + 1)
            t1 = targets[0]
            k = 0
            while k < len(targets) and targets[k] == t1:
                k += 1
            insts = _instructions(target)
            by_offset = {ins.offset: n for n, ins in enumerate(insts)}
            end = None
            if all(t == s_start for t in targets[k:]):
                end = _else_end(lines, cand, insts, by_offset, t1)
            if end is None:
                refused.add(key)
                problems.append("%s: lost else, but cannot place it (%s)"
                                % (where, targets))
                continue
            source = "\n".join(_restructure(lines, cand, k, end))
            fixes.append("%s: restored a lost `else:` (%d lines moved in)"
                         % (where, end - cand["stmt"]))
            break
        else:
            return source, fixes, problems
