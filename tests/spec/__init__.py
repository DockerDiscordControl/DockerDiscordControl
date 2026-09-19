# -*- coding: utf-8 -*-
"""Tests mapped to the guarantees in SPEC.md.

Each file carries a marker ``# @covers Zn`` at its top and checks exactly what
the guarantee promises - not the implementation that fulfils it today.
"""


def is_not_awaitable_error(error):
    """True if ``error`` is the TypeError of awaiting a non-awaitable (a MagicMock).

    Several tests let a callback run into cog methods on a MagicMock AFTER the
    part they check, and swallow exactly this error. Its wording depends on the
    Python version: 3.14 says "'MagicMock' object can't be awaited", 3.10 says
    "object MagicMock can't be used in 'await' expression". The tests used to
    match only the first, so on CI (Python 3.10) they re-raised it and failed
    - seven red tests on the first develop push of 2026-09-19, while the Unraid
    runtime (3.14) was green. One place for the rule, so the copies cannot
    drift apart again.
    """
    text = str(error)
    return isinstance(error, TypeError) and (
        "can't be awaited" in text or "can't be used in 'await' expression" in text
    )
