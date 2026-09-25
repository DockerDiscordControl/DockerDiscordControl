# -*- coding: utf-8 -*-
"""A problem that will not go away is reported less and less, never forever.

THE OPERATOR (2026-09-25) asked what to do with bot_error.log, which is written
but shown nowhere. Reading it answered a different question. 33,216 lines, and:

    11042  ERROR  All token decryption methods failed
    11042  ERROR  FATAL: Bot token not found or could not be decrypted.
    11042  ERROR  Please configure the bot token in the Web UI ...
        2  ERROR  Error in event on_ready: Traceback ...
        1  ERROR  Error in event on_connect: Traceback ...

33,126 of 33,216 lines are one situation. Three are real incidents, and they
are the only reason to keep an error log at all.

11,042 retries at sixty seconds is 7.7 days - and the file's own dates are
2025-11-18 to 2025-11-25, so this happened once, for a week, when a container
ran without a configured token. The loop also printed a countdown at INFO
("Retrying in 50 seconds... 40... 30..."), about eleven lines a minute, into
discord.log.

WHY THIS IS THE WORST SHAPE OF THE DISEASE. Every other log finding today was
a line that was untrue, or pointless, or addressed to the wrong reader. THIS
ONE IS CORRECT. The token really was missing; ERROR really is the right level;
an operator really does need to be told. And repeated at a fixed rate it
destroys the very file it is written to: bot_error.log rotates at 5 MB with
three backups, so a week of this evicts every real incident before anybody
reads it. Being right is not enough. A log has a budget.

THE RULE: the FIRST report of a standing problem is full and loud, because
that is when somebody can act on it. After that the interval widens - attempt
1, 2, 3, 5, 10, 30, then hourly - and each repeat says how long it has been
going on, which is the only new information a repeat can carry. The check
itself keeps running at its own pace; only the reporting decays.

THE SAME FILE ALREADY KNEW THIS. `_wait_for_new_token_and_restart` warns once
and then re-checks in silence. Two loops, one habit each.

HOW THIS TEST CAN FAIL: a standing failure logged at a constant rate, a first
failure that is quiet, or a repeat that does not say how long it has lasted.

COUNTER-CHECK (2026-09-25): red before - 1,440 reports in a simulated day,
against 12 now.
"""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import bot as bot_module


@pytest.fixture
def no_sleep(monkeypatch):
    """Time passes instantly; the loop's own pace is not what is under test."""
    slept = []
    monkeypatch.setattr(bot_module.time, "sleep", lambda s: slept.append(s))
    return slept


def _runtime():
    return SimpleNamespace(logger=MagicMock(spec=logging.Logger), config={},
                           dependencies=SimpleNamespace(config_service_factory=None))


def _run_until_token_appears(monkeypatch, no_sleep, attempts_without_a_token):
    """Drive the wait exactly as main() does, with a token appearing at last."""
    answers = [None] * attempts_without_a_token + ["a-real-token"]
    supply = iter(answers)
    monkeypatch.setattr(bot_module, "get_decrypted_bot_token", lambda runtime: next(supply))
    monkeypatch.setattr(bot_module, "load_main_configuration", lambda: {})
    runtime = _runtime()
    monkeypatch.setattr(bot_module, "build_runtime", lambda config: runtime)

    token = bot_module._wait_for_a_usable_token(runtime, retry_interval=60, max_retries=0)
    return token, runtime.logger


def _reports(logger):
    return [str(call.args[0]) for call in logger.error.call_args_list]


def test_the_first_failure_is_reported_in_full(monkeypatch, no_sleep):
    """The moment somebody can act. Quietening this would be the opposite
    mistake, and it is the one a rate limit invites."""
    _token, logger = _run_until_token_appears(monkeypatch, no_sleep, 1)
    said = " ".join(_reports(logger))

    assert "token" in said.lower()
    assert "Web UI" in said, said


def test_a_day_of_the_same_failure_is_not_a_day_of_reports(monkeypatch, no_sleep):
    """THE FINDING: 1,440 attempts used to mean 1,440 reports - 4,320 ERROR
    lines - and bot_error.log holds 5 MB.

    The arithmetic of the schedule over a simulated day, written down because
    the first version of this case guessed at 30 and caught the real answer by
    one: six milestones (attempts 1, 2, 3, 5, 10, 30) plus every sixtieth
    attempt (60 ... 1440, so 24 of them) is 30 reporting attempts, and the
    first of those writes two lines - 31. About one report every 48 minutes.
    """
    _token, logger = _run_until_token_appears(monkeypatch, no_sleep, 1440)
    reports = _reports(logger)

    assert len(reports) <= 35, f"{len(reports)} reports for one standing problem"
    assert len(reports) >= 2, "a problem lasting a day must still be mentioned more than once"


def test_the_retries_themselves_keep_their_pace(monkeypatch, no_sleep):
    """Counter-check: reporting less must not mean TRYING less. An operator
    who saves a token waits at most one interval, as before."""
    _token, _logger = _run_until_token_appears(monkeypatch, no_sleep, 1440)

    assert len(no_sleep) >= 1440, f"the loop stopped checking: {len(no_sleep)} sleeps"
    assert set(no_sleep) == {60}, f"the check interval drifted: {sorted(set(no_sleep))[:5]}"


def test_a_repeat_says_how_long_it_has_been_going_on(monkeypatch, no_sleep):
    """The only new information a repeat can carry. Without it the tenth
    report is indistinguishable from the first and equally ignorable."""
    _token, logger = _run_until_token_appears(monkeypatch, no_sleep, 1440)
    later = _reports(logger)[-1]

    assert any(word in later.lower() for word in ("still", "for ", "since", "attempt")), later


def test_the_token_is_returned_once_it_appears(monkeypatch, no_sleep):
    """Counter-check on the extraction itself: the loop's job is unchanged."""
    token, _logger = _run_until_token_appears(monkeypatch, no_sleep, 3)

    assert token == "a-real-token"


def test_a_countdown_is_not_news(monkeypatch, no_sleep):
    """"Retrying in 50 seconds... 40... 30..." was about eleven INFO lines a
    minute, forever, in the file an operator reads to find out what happened."""
    _token, logger = _run_until_token_appears(monkeypatch, no_sleep, 60)
    announced = [str(call.args[0]) for call in logger.info.call_args_list]
    countdowns = [line for line in announced if "Retrying in" in line]

    assert countdowns == [], f"{len(countdowns)} countdown lines at INFO"


def test_a_limit_on_retries_is_still_honoured(monkeypatch, no_sleep):
    """DDC_TOKEN_MAX_RETRIES exists and must survive the extraction."""
    monkeypatch.setattr(bot_module, "get_decrypted_bot_token", lambda runtime: None)
    monkeypatch.setattr(bot_module, "load_main_configuration", lambda: {})
    runtime = _runtime()
    monkeypatch.setattr(bot_module, "build_runtime", lambda config: runtime)

    with pytest.raises(SystemExit):
        bot_module._wait_for_a_usable_token(runtime, retry_interval=60, max_retries=3)
