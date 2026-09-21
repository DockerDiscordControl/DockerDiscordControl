# -*- coding: utf-8 -*-
"""The JavaScript the panel ships can be parsed at all.

THE FINDING (review E2, found by the operator on 2026-09-21 and traced to my
own commit `dfa3662` of 2026-09-20): removing the dead
`simulateDonationBroadcast()` from `config.html` took out the function's head -
the `function` line, three `const`s, the `if (confirm(...))`, the `fetch(`,
`method` and `headers` - and left the whole rest of the call standing:

        }

                    body: JSON.stringify({
                        donor_name: donorName,
                        ...
                    })
                })
                .then(response => response.json())
                ...

That is a **syntax error**, and a syntax error takes the ENTIRE inline script
block with it: not one function in it is ever defined. The mech display on the
configuration page stopped updating - it kept showing the server-rendered
placeholders ("ENERGIE 0", "REPARIERTER MECH", "$20 needed"), which look like
real values, while Discord showed the truth. The operator found it, not the
test suite.

**The full run was 4,828 green over a page whose JavaScript could not be
parsed.** Nothing in this project has ever looked at the delivered script. That
is what this test is for.

HOW IT CHECKS, and what that is worth: there is no JavaScript engine in the
runtime image (no node, and no esprima/dukpy/quickjs in site-packages), so this
cannot be a real parse. It counts brackets instead, with a scanner that knows
JS strings, template literals including nested `${...}`, and both kinds of
comment. It would not notice `let 3x = 1`, but it does notice a block that was
cut in half - which is the mistake that actually happened, and the one an
editing hand makes.

Regular-expression literals ARE handled, and they had to be: the first version
of this scanner read `.replace(/"/g, "&quot;")` in tasks.js as a division
followed by a string and reported three defects that were not there. Telling a
regex from a division without a parser means looking at what came before -
after a value (`)`, `]`, an identifier, a number) a `/` divides; after an
operator, a comma, an opening bracket or a keyword it starts a regex. That
heuristic is what the scanner uses, and the two tests at the end hold it to
both directions.
"""

import re
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
TEMPLATES = PROJECT / "app" / "templates"

SCRIPT = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.DOTALL | re.IGNORECASE)
JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.DOTALL)
OPEN, CLOSE = "([{", ")]}"
PAIR = {")": "(", "]": "[", "}": "{"}
# A "/" after one of these starts a REGEX, not a division: they cannot end a
# value. Anything else (an identifier, a number, ")", "]") means division.
BEFORE_REGEX = set("(,=:[!&|?{};+-*%~^<>") | {""}
REGEX_KEYWORDS = ("return", "typeof", "case", "in", "of", "new", "delete", "void",
                  "instanceof", "do", "else", "yield", "await")


def _regex_expected(source, at):
    """Whether a '/' at this position opens a regex literal rather than dividing."""
    j = at - 1
    while j >= 0 and source[j] in " \t\r\n":
        j -= 1
    if j < 0:
        return True
    if source[j] in BEFORE_REGEX:
        return True
    # a keyword directly before it also means a regex ("return /x/.test(s)")
    k = j
    while k >= 0 and (source[k].isalnum() or source[k] == "_"):
        k -= 1
    return source[k + 1:j + 1] in REGEX_KEYWORDS


def _scan(source):
    """Bracket balance outside strings, comments and regex literals.

    Template literals are a mode of their own and they NEST: a `${...}` may
    contain another backtick string, which may contain another `${...}`. The
    first version of this scanner skipped from one backtick to the next and
    reported an imbalance in config.html that was not there - the CSS builder
    in testSpeedControl() nests two levels deep.
    """
    stack = []                 # open brackets; "${" is one of them
    modes = ["code"]           # "code" or "template"
    i, n = 0, len(source)

    def line_of(pos):
        return source.count("\n", 0, pos) + 1

    while i < n:
        c = source[i]
        nxt = source[i + 1] if i + 1 < n else ""

        if modes[-1] == "template":
            if c == "\\":
                i += 2
                continue
            if c == "`":
                modes.pop()
                i += 1
                continue
            if c == "$" and nxt == "{":
                stack.append(("${", line_of(i)))
                modes.append("code")
                i += 2
                continue
            i += 1
            continue

        if c == "/" and nxt == "/":
            i = source.find("\n", i)
            if i == -1:
                break
            continue
        if c == "/" and nxt == "*":
            end_of = source.find("*/", i + 2)
            i = n if end_of == -1 else end_of + 2
            continue
        if c in "'\"":
            quote, i = c, i + 1
            while i < n:
                if source[i] == "\\":
                    i += 2
                    continue
                if source[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if c == "`":
            modes.append("template")
            i += 1
            continue
        if c == "/" and _regex_expected(source, i):
            i += 1
            in_class = False
            while i < n:
                if source[i] == "\\":
                    i += 2
                    continue
                if source[i] == "[":
                    in_class = True
                elif source[i] == "]":
                    in_class = False
                elif source[i] == "/" and not in_class:
                    i += 1
                    break
                elif source[i] == "\n":
                    break          # an unterminated regex is not a regex
                i += 1
            continue

        if c in OPEN:
            stack.append((c, line_of(i)))
        elif c in CLOSE:
            if not stack:
                return None, f"a stray '{c}' on line {line_of(i)}"
            opener, line = stack[-1]
            if opener == "${":
                if c != "}":
                    return None, (f"'{c}' on line {line_of(i)} closes the "
                                  f"${{...}} opened on line {line}")
                stack.pop()
                modes.pop()
                i += 1
                continue
            stack.pop()
            if opener != PAIR[c]:
                return None, (f"'{c}' on line {line_of(i)} closes a '{opener}' "
                              f"opened on line {line}")
        i += 1

    if stack:
        opener, line = stack[-1]
        return None, f"'{opener}' opened on line {line} is never closed"
    if len(modes) != 1:
        return None, "a template literal is never closed"
    return 0, None


def _blocks():
    for path in sorted(TEMPLATES.rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        for attributes, body in SCRIPT.findall(text):
            if "src=" in attributes.lower():
                continue
            if body.strip():
                yield path.relative_to(PROJECT), body


TEMPLATE_BLOCKS = list(_blocks())
JS_FILES = sorted((PROJECT / "app" / "static" / "js").glob("*.js"))


def test_there_is_something_to_check():
    """Safeguard against a blunt tool - a scanner reading nothing is green."""
    assert len(TEMPLATE_BLOCKS) > 3, f"only {len(TEMPLATE_BLOCKS)} script blocks found"
    assert JS_FILES, "no javascript files found"


@pytest.mark.parametrize("path,body", TEMPLATE_BLOCKS,
                         ids=[f"{p}#{i}" for i, (p, _) in enumerate(TEMPLATE_BLOCKS)])
def test_an_inline_script_block_is_not_cut_in_half(path, body):
    # Jinja is not JavaScript: its braces must not be counted.
    _, error = _scan(JINJA.sub("0", body))
    assert error is None, (
        f"{path}: {error}. A syntax error here takes the whole block with it - "
        f"every function in it stops existing, and the page keeps showing the "
        f"values the server rendered into it"
    )


@pytest.mark.parametrize("path", JS_FILES, ids=[p.name for p in JS_FILES])
def test_a_javascript_file_is_not_cut_in_half(path):
    _, error = _scan(path.read_text(encoding="utf-8"))
    assert error is None, f"{path.name}: {error}"


def test_the_scanner_notices_the_defect_it_was_written_for():
    """The counter-check: a test that cannot fail is not a test.

    This is the shape of what `dfa3662` left behind in config.html - the tail
    of a call whose head was deleted.
    """
    orphan = """
        function healthy() {
            return 1;
        }

                    body: JSON.stringify({
                        donor_name: donorName
                    })
                })
                .then(response => response.json());
            }
        }
    """
    _, error = _scan(orphan)
    assert error is not None, "the scanner walks straight past the real defect"


def test_the_scanner_tells_a_regex_from_a_division():
    """The false positive that the first version of this test produced.

    `.replace(/"/g, "&quot;")` is a regex, a flag and a string. Read as a
    division it swallows the rest of the file, and the scanner reported three
    defects in files that were perfectly fine.
    """
    real = """
        function escape(s) {
            return s.replace(/</g, "&lt;")
                    .replace(/"/g, "&quot;")
                    .replace(/[^}]/g, "")
                    .replace(/'/g, "&#039;");
        }
        const ratio = (a + b) / (c - d);
        const half = total / 2;
    """
    depth, error = _scan(real)
    assert error is None, error
    assert depth == 0


def test_the_scanner_follows_nested_template_literals():
    """The second false positive this test produced before it could ship.

    config.html builds CSS with a backtick string inside a `${...}` inside a
    backtick string. Skipping from backtick to backtick reads the file
    inside-out and reports an imbalance that is not there.
    """
    nested = """
        const css = `
            .a { color: red; }
            ${flag ? `
                .b { width: ${w}px; }
                @keyframes k { 0% { opacity: 0; } }
            ` : ''}
            .c { top: 0; }
        `;
    """
    depth, error = _scan(nested)
    assert error is None, error
    assert depth == 0


def test_the_scanner_does_not_trip_over_ordinary_javascript():
    """The other direction: template literals, nesting, comments, brackets in strings."""
    fine = """
        const css = `
            .a { color: red; }
            .b { width: ${100 - (x ? 1 : 2)}%; }
        `;
        // a comment with an unbalanced ) and }
        /* and a block one with { */
        const s = "a string with } and ) in it";
        const t = 'another with { and (';
        function f(a, b) { return [a, {b}]; }
    """
    depth, error = _scan(fine)
    assert error is None, error
    assert depth == 0
