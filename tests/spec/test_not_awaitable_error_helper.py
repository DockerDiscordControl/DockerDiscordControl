# -*- coding: utf-8 -*-
"""``tests.spec.is_not_awaitable_error`` must recognise BOTH wordings.

No ``@covers`` marker: this guards test infrastructure, not a guarantee.

WHY: four spec tests swallow exactly the TypeError of awaiting a MagicMock and
re-raise everything else. They matched only the Python 3.14 wording, so on CI
(Python 3.10) seven of them failed on the first develop push of 2026-09-19.
The Unraid runtime runs 3.14 and cannot see the 3.10 wording at all - dropping
it from the helper would stay green here and turn CI red again. So the 3.10
text is pinned below as a literal, measured with python3.10 on 2026-09-19.
"""

import asyncio
from unittest.mock import MagicMock

from tests.spec import is_not_awaitable_error

PY310 = "object MagicMock can't be used in 'await' expression"
PY314 = "'MagicMock' object can't be awaited"


def _real_error():
    async def run():
        await MagicMock()()
    try:
        asyncio.run(run())
    except TypeError as e:
        return e
    raise AssertionError("awaiting a MagicMock did not raise - the premise is gone")


def test_both_wordings_are_recognised():
    assert is_not_awaitable_error(TypeError(PY310))
    assert is_not_awaitable_error(TypeError(PY314))


def test_the_running_interpreter_is_recognised():
    """Whatever version runs the suite, its own real error must match."""
    error = _real_error()
    assert is_not_awaitable_error(error), f"unrecognised wording: {error}"


def test_other_type_errors_are_not_swallowed():
    assert not is_not_awaitable_error(TypeError("unsupported operand type(s) for +: 'int' and 'str'"))
    assert not is_not_awaitable_error(ValueError(PY314))
