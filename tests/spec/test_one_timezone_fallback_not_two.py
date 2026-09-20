# -*- coding: utf-8 -*-
"""
THE FINDING (review C35, section 36 F3 - and it is worse than reported): the
timezone an operator sets in the web panel has no effect on the times the bot
writes into Discord.

`_get_timezone_safe()` asks, in this order:

    1. os.environ['TZ']          "container-level override"
    2. the configured timezone
    3. ...
    4. 'UTC'

and the Dockerfile sets `TZ="Europe/Berlin"` for every image DDC ships. So step
1 always answers and steps 2-4 are dead. `format_datetime_with_timezone` - what
`docker_control`, `status_handlers`, `control_ui` and `control_helpers` use for
every timestamp they show - therefore always prints Berlin time.

`logging_utils.TimezoneFormatter` reads the CONFIG instead. Measured in the
real container with `timezone = America/New_York` configured:

    console log : 2026-09-09 20:26 EDT
    discord     : 10.09.2026 02:26:40

Six hours apart, and the panel setting is simply ignored on the Discord side.

WHAT THE REPORT SAID AND WHAT IS ACTUALLY TRUE: the reviewer described two
fallbacks disagreeing when the config is unreachable - `logging_utils` falling
back to 'Europe/Berlin' and `time_utils` to 'UTC'. Those fallbacks cannot
disagree in the shipped image, because the time_utils one is never reached: TZ
is always set. The disagreement is real but it is in the NORMAL path, not the
failure path, and it costs the operator their setting rather than a few log
lines during an outage.

The order is now: what the operator configured, then TZ as the container's
default, then one shared constant instead of two literals.

Found while reading, NOT fixed here: the same choice is hard-coded at about a
dozen further places with three different values - 'Europe/Berlin' in the web
and action-log services, 'UTC' in config validation, 'Europe/Zurich' in the
progress runtime. Some may be deliberate, so they are named rather than changed
by guesswork.

The counter-checks keep TZ meaningful where nothing was configured, and keep an
explicit argument winning over everything.
"""

import logging

import pytest

from utils import logging_utils, time_utils


@pytest.fixture
def clocks(monkeypatch):
    """Both modules read the config lazily from the same place."""
    import services.config.config_service as config_service

    def _configure(timezone_value):
        if timezone_value is None:
            monkeypatch.setattr(config_service, "load_config", lambda *a, **k: {})
        else:
            monkeypatch.setattr(config_service, "load_config",
                                lambda *a, **k: {"timezone": timezone_value})
        monkeypatch.setattr(config_service, "get_config_service",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no")))
        monkeypatch.setattr(logging_utils.TimezoneFormatter, "_tz_name", None)
        monkeypatch.setattr(logging_utils.TimezoneFormatter, "_tz_name_read_at", 0.0)
        time_utils.clear_timezone_cache()

    monkeypatch.setenv("TZ", "Europe/Berlin")   # what the Dockerfile sets
    yield _configure
    time_utils.clear_timezone_cache()


MOMENT = 1789000000.0


def _log_time() -> str:
    record = logging.LogRecord("ddc.spec", logging.INFO, "f.py", 1, "m", (), None)
    record.created = MOMENT
    return logging_utils.TimezoneFormatter("%(message)s").formatTime(
        record, "%Y-%m-%d %H:%M")


def _discord_time() -> str:
    from datetime import datetime, timezone as _tz
    return time_utils.format_datetime_with_timezone(
        datetime.fromtimestamp(MOMENT, _tz.utc))


def test_the_configured_timezone_reaches_discord(clocks):
    """THE FINDING: the panel setting must not be ignored."""
    clocks("America/New_York")

    assert time_utils.get_configured_timezone() == "America/New_York"


def test_both_clocks_show_the_same_hour(clocks):
    """One instant, one time - the log and Discord must not differ by six
    hours."""
    clocks("America/New_York")

    assert _log_time()[11:16] == _discord_time()[11:16], (
        f"log {_log_time()!r} vs discord {_discord_time()!r}")


def test_the_environment_still_decides_when_nothing_is_configured(clocks):
    """COUNTER-CHECK: TZ keeps its job as the container's default."""
    clocks(None)

    assert time_utils.get_configured_timezone() == "Europe/Berlin"


def test_an_explicit_argument_still_wins(clocks):
    """COUNTER-CHECK: a caller that names a timezone gets that one."""
    clocks("America/New_York")
    from datetime import datetime, timezone as _tz

    shown = time_utils.format_datetime_with_timezone(
        datetime.fromtimestamp(MOMENT, _tz.utc), timezone_name="Asia/Tokyo")

    assert shown.startswith("10.09.2026 09:26")


def test_the_fallback_has_one_name():
    """One constant instead of two literals, so the two modules cannot drift
    apart again."""
    assert time_utils.DEFAULT_TIMEZONE == logging_utils.DEFAULT_TIMEZONE
