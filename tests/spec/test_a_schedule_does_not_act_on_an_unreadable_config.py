# -*- coding: utf-8 -*-
# @covers Z5
"""A container config that could not be read does not permit a scheduled action.

THE FINDING (review E6, section 26 - never reviewed by either pass).
`_get_disallowed_action_reason` answers None for "this may run", and its
handler does the same when it could not tell:

    except (ImportError, AttributeError, RuntimeError, OSError, ValueError) as e:
        logger.warning(f"Could not check allowed actions for '{container_name}': {e}")
        return None

So a config that cannot be read lets the scheduler start, stop or restart a
container WITHOUT confirming the container allows that action.

SPEC.md Z5: "Start, stop and restart happen only if the channel holds the
permission AND the container allows the action - on EVERY path: button,
schedule, automation rule, web panel." The documented exception B12 is a
different one (web-panel tasks have no channel to check); this gap is not
recorded anywhere.

And it is the opposite answer to the one this programme gave the same
question elsewhere: D36 - "a permission that cannot be read is not a
permission granted"; D32 - the same for the container assignment; E5 - a
check that could not be made is not a verdict. Here the unverifiable answer
was "go ahead and touch the container".

NOT CHANGED, because it is a different decision and a defensible one: a
container that is simply not in the config still runs, with the warning that
was already there. The task was made for it and the config merely does not
list it. What changes is only the case where reading FAILED.

What the operator sees now: the run is skipped and the task says why - since
E3 a skipped run is written on the task, so this does not disappear into the
log.
"""

import pytest

import services.scheduling.scheduler as scheduler_mod

CONFIGURED = [{"docker_name": "valheim", "allowed_actions": ["start", "restart"]}]


def _config_raises(monkeypatch, error):
    monkeypatch.setattr(
        "services.config.server_config_service.get_server_config_service",
        lambda: (_ for _ in ()).throw(error))


def _config_is(monkeypatch, servers):
    monkeypatch.setattr(
        "services.config.server_config_service.get_server_config_service",
        lambda: type("S", (), {"get_all_servers": staticmethod(lambda: servers)})())


@pytest.mark.parametrize("error", [OSError("config unreadable"),
                                   ValueError("config is not JSON"),
                                   RuntimeError("service unavailable")])
def test_a_config_that_could_not_be_read_refuses(monkeypatch, error):
    """The finding: an unverifiable permission is not a permission."""
    _config_raises(monkeypatch, error)

    reason = scheduler_mod._get_disallowed_action_reason("valheim", "stop")

    assert reason, (
        "the container config could not be read and the scheduler went ahead "
        "and touched the container anyway"
    )
    assert "could not" in reason.lower() or "unreadable" in reason.lower(), reason


def test_a_container_that_is_not_configured_still_runs(monkeypatch):
    """Unchanged on purpose - a different decision, and a defensible one."""
    _config_is(monkeypatch, CONFIGURED)

    assert scheduler_mod._get_disallowed_action_reason("nginx", "stop") is None


def test_an_allowed_action_is_allowed(monkeypatch):
    _config_is(monkeypatch, CONFIGURED)

    assert scheduler_mod._get_disallowed_action_reason("valheim", "restart") is None


def test_a_disallowed_action_is_refused_with_its_reason(monkeypatch):
    """The counter-case that was already working."""
    _config_is(monkeypatch, CONFIGURED)

    reason = scheduler_mod._get_disallowed_action_reason("valheim", "stop")

    assert reason and "stop" in reason, reason
