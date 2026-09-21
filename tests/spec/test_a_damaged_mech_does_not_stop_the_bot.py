# -*- coding: utf-8 -*-
"""A mech state that cannot be healed does not stop the bot from starting.

THE FINDING (review E8), and it is a consequence of an earlier repair of mine.

D1 made `_heal_if_lagging` RAISE `MechStateError` when the snapshot lags
behind the event log and cannot be rebuilt. That was right: writing on top of
it would bury a donation for good. What nobody checked is where that new
exception goes on the paths that are not a donation.

`grant_power_gift_step` is **step 2 of 9** in STARTUP_STEPS, and the chain is:

    grant_power_gift_step -> adapter.power_gift -> progress_service.power_gift
                          -> _heal_if_lagging   -> raise MechStateError

The step catches
`(IOError, OSError, PermissionError, RuntimeError, docker.errors.APIError,
docker.errors.DockerException)`. `MechStateError` descends from
MechServiceError -> DDCBaseException -> Exception and is none of those. The
adapter passes it straight through. `run_startup_sequence` has no handler at
all - it is a bare `for step in steps: await step(context)` - and neither does
its caller.

So a damaged mech snapshot stops the startup sequence at step 2, and the seven
steps after it never run: **no extensions, no commands, no scheduler.** The bot
connects to Discord and does nothing. It looks online.

`initialize_member_count_step` has the same gap through `update_member_count`,
which also heals first. It is the LAST step, so the cost there is only its own
work - but the gap is the same one and is closed with it.

Not repaired here, and put to the operator instead: `run_startup_sequence`
aborting on ANY unlisted exception from ANY step. That is a decision about what
a failing step should mean, not a defect to be quietly patched. The last test
below pins today's answer so the decision is visible rather than assumed.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.exceptions import MechStateError


def _context():
    return SimpleNamespace(logger=MagicMock(), bot=MagicMock())


async def test_an_unhealable_mech_does_not_abort_the_power_gift_step(monkeypatch):
    """The finding: step 2 of 9, and the seven after it never ran."""
    from app.bot.startup_steps.power import grant_power_gift_step

    adapter = MagicMock()
    adapter.power_gift.side_effect = MechStateError(
        "Snapshot could not be healed", error_code="SNAPSHOT_HEALING_FAILED")
    monkeypatch.setattr("services.mech.mech_service_adapter.get_mech_service",
                        lambda: adapter)

    await grant_power_gift_step(_context())        # must not raise


async def test_the_reason_is_logged(monkeypatch):
    """It must not become silent either - the mech state needs attention."""
    from app.bot.startup_steps.power import grant_power_gift_step

    adapter = MagicMock()
    adapter.power_gift.side_effect = MechStateError(
        "Snapshot could not be healed", error_code="SNAPSHOT_HEALING_FAILED")
    monkeypatch.setattr("services.mech.mech_service_adapter.get_mech_service",
                        lambda: adapter)
    context = _context()

    await grant_power_gift_step(context)

    said = " ".join(str(call) for call in context.logger.mock_calls)
    assert "power" in said.lower() or "mech" in said.lower(), said


async def test_a_working_power_gift_is_still_granted(monkeypatch):
    """The counter-case: swallowing everything is not the point."""
    from app.bot.startup_steps.power import grant_power_gift_step

    adapter = MagicMock()
    adapter.power_gift.return_value = SimpleNamespace(power_level=3.0)
    monkeypatch.setattr("services.mech.mech_service_adapter.get_mech_service",
                        lambda: adapter)
    context = _context()

    await grant_power_gift_step(context)

    adapter.power_gift.assert_called_once_with("startup_gift_v1")
    said = " ".join(str(call) for call in context.logger.mock_calls)
    assert "granted" in said.lower(), said


async def test_the_member_count_step_has_the_same_gap_closed(monkeypatch):
    """The other path that heals first - last step, same rule."""
    from app.bot.startup_steps.member_count import initialize_member_count_step

    service = MagicMock()
    service.get_state.side_effect = MechStateError(
        "Snapshot could not be healed", error_code="SNAPSHOT_HEALING_FAILED")
    monkeypatch.setattr("services.mech.progress_service.get_progress_service",
                        lambda *a, **k: service)

    await initialize_member_count_step(_context())     # must not raise


async def test_a_step_that_fails_does_not_stop_the_ones_after_it():
    """The operator's decision, 2026-09-21, taken step by step (review E9).

    This test used to pin the OPPOSITE - that any exception stopped the rest -
    as an observation, so the choice would be visible rather than accidental.
    The operator then made it, and the reasoning that settled it is that the
    sequence runs in `handle_ready()`: the bot is already connected to Discord,
    so an abort protects nothing and only deepens a bad start. Not one of the
    nine steps is worth stopping the other eight for.
    """
    from app.bot.startup_steps.sequence import run_startup_sequence

    ran = []

    async def first(context):
        ran.append("first")
        raise ValueError("something nobody listed")

    async def second(context):
        ran.append("second")

    await run_startup_sequence(_context(), [first, second])

    assert ran == ["first", "second"], (
        "a failing step took the ones after it down - today the power gift "
        "could still stop the scheduler that way"
    )


async def test_the_end_says_which_steps_failed():
    """One line at the end, because a single failure drowns in a startup log."""
    from app.bot.startup_steps.sequence import run_startup_sequence

    async def good(context):
        return None

    async def bad(context):
        raise RuntimeError("no")

    bad.step_name = "start_scheduler_step"
    context = _context()

    await run_startup_sequence(context, [good, bad])

    said = " ".join(str(call) for call in context.logger.mock_calls)
    assert "STARTUP INCOMPLETE" in said, said
    assert "start_scheduler_step" in said, (
        "the summary does not name the step that failed, so it says nothing useful"
    )


async def test_a_clean_start_says_so_and_nothing_else():
    """The counter-case: the summary must not cry wolf."""
    from app.bot.startup_steps.sequence import run_startup_sequence

    async def good(context):
        return None

    context = _context()

    await run_startup_sequence(context, [good, good])

    said = " ".join(str(call) for call in context.logger.mock_calls)
    assert "STARTUP INCOMPLETE" not in said, said
    # The logger is a MagicMock, so it records the FORMAT STRING and the
    # arguments separately - asserting on the formatted sentence looks for
    # something nobody ever wrote down.
    assert "All %d startup steps completed" in said, said
    assert "2" in said, said


async def test_a_shutdown_is_not_a_step_failure():
    """CancelledError means DDC is going down; it must travel on."""
    import asyncio

    from app.bot.startup_steps.sequence import run_startup_sequence

    async def cancelled(context):
        raise asyncio.CancelledError()

    async def never(context):
        raise AssertionError("the sequence carried on through a shutdown")

    with pytest.raises(asyncio.CancelledError):
        await run_startup_sequence(_context(), [cancelled, never])
