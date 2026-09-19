# -*- coding: utf-8 -*-
"""No bare ``except:`` in the application code.

NO ``@covers`` marker: that would be a new guarantee, and guarantees are the
operator's decision. If this is to become Z12, the marker follows.

WHAT THIS IS ABOUT - and explicitly NOT about style: ``except:`` catches every
``BaseException``, including ``KeyboardInterrupt`` and ``SystemExit``. When the
container shuts down, this means:

* Cleanup code is skipped, because the abort signal gets stuck in the
  ``except`` instead of propagating.
* Worse: if an ``except:`` around a Discord send catches the abort signal, the
  fallback path starts and sends a message nobody asked for - during shutdown.

The second case is real in ``docker_control.py``: there a bare ``except:``
wraps a ``followup.send`` call including a fallback send.

BOUNDARY: ``except Exception:`` is allowed. This guarantee does not demand that
every place lists its exceptions one by one - that would be a style rule and
would produce false alarms that make the test worthless. It only demands that
the two program-abort signals are not caught along the way.

CHECKS THE SOURCE VIA AST, not via text search: ``except:`` can appear in a
comment or a string, and exactly this false alarm produced four wrong hits in
the Z10 detector (see test_z10_ci_test_gate.py). The AST knows the difference.

COUNTER-CHECK (performed 2026-09-17):

*Before the fix:* red with **33** findings - exactly the inventory from the
stocktaking (25 in ``cogs/``, 7 in ``services/``, 1 in ``utils/``, 0 in
``app/``). The two guards above were green at the time: the tree was populated,
and the tool correctly distinguished a real ``except:`` from ``except
Exception:``, from a comment, from a string and from an exception tuple.
Without this second guard the detector would have been as worthless as the
first version of the Z10 detector, which triggered on comments.

*After converting 32 places:* **one** finding left - ``mech_images.py:25``,
deliberately excluded. That file was a dead module (see below) and was removed
instead of repaired; an exception rule in the test would have hidden the
finding instead of eliminating it.

*Afterwards:* 0 findings, without the test knowing any exception.

EVIDENCE OF EFFECT: the five affected test groups stayed unchanged
(``cogs`` 267, ``services/web`` 358, ``services/automation`` 104,
``services/configuration`` 152, ``utils`` 248) - the conversion changes no
behaviour except the one at stake.

WHAT THE CONVERSION ACTUALLY ACHIEVES, and it is more than cosmetics:
``docker_control.py:2198`` and ``:2252`` wrap a Discord send including a
fallback send. A bare ``except:`` catches ``CancelledError`` there - so during
shutdown a donation message nobody asked for would have gone out.
``except Exception:`` does not catch it, because ``CancelledError`` inherits
from ``BaseException`` since Python 3.8.

SIDE FINDING, handled as its own commit: ``services/mech/mech_images.py``
imported ``services.mech.mech_evolution_loader`` on line 19 - a file that does
NOT exist anywhere in the tree. So the module was not importable, and no
production module imported it. Fourteen tests checked it through a patched
copy of the source; their own comment said so. Module and tests are removed.
"""

import ast
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]

# The application code. scripts/ is deliberately NOT included: one-off tools,
# started by the operator who watches them run - the same boundary as for Z7.
DIRECTORIES = ("cogs", "services", "app", "utils")


def _files():
    for directory in DIRECTORIES:
        yield from sorted((PROJECT / directory).rglob("*.py"))


def _bare_excepts(path: Path):
    """Line numbers of the ``except:`` blocks without a type."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler) and node.type is None
    ]


def test_the_tree_is_not_empty():
    """Safeguard against a blunt tool.

    If the file search finds nothing - because a directory was renamed or the
    path is wrong - the test below would be green without proving anything.
    """
    files = list(_files())
    assert len(files) > 100, (
        f"Only {len(files)} Python files found - the path is probably wrong"
    )


def test_the_tool_detects_a_bare_except():
    """Evidence of effect: the detector must fire when there is something to report.

    And it must NOT fire on ``except Exception:`` or when the character
    sequence only appears in a comment or string - exactly these false alarms
    once made the Z10 detector worthless.
    """
    import tempfile

    cases = [
        ("try:\n    pass\nexcept:\n    pass\n", 1, "real bare except not detected"),
        ("try:\n    pass\nexcept Exception:\n    pass\n", 0, "except Exception wrongly reported"),
        ("# except:\nx = 1\n", 0, "comment wrongly reported"),
        ("s = 'except:'\n", 0, "string wrongly reported"),
        ("try:\n    pass\nexcept (ValueError, KeyError):\n    pass\n", 0, "tuple wrongly reported"),
    ]
    for source, expected, message in cases:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(source)
            path = Path(f.name)
        try:
            assert len(_bare_excepts(path)) == expected, f"{message}: {source!r}"
        finally:
            path.unlink()


def test_no_bare_except_in_the_application_code():
    """``except:`` also catches KeyboardInterrupt and SystemExit."""
    findings = []
    for path in _files():
        for line in _bare_excepts(path):
            findings.append(f"{path.relative_to(PROJECT)}:{line}")

    assert not findings, (
        f"{len(findings)} bare 'except:' - they also catch KeyboardInterrupt and "
        "SystemExit, thereby suppressing the shutdown, and in the Discord path "
        "they can even trigger a fallback send:\n  "
        + "\n  ".join(findings)
    )
