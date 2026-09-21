# -*- coding: utf-8 -*-
"""The admin dropdown offers only the containers this admin may control.

THE REQUEST (operator, 2026-09-21): can the display in Discord change with
the right - so that the selection lists only the containers this admin is
allowed to control in a status channel?

Yes - and only here. The Server Overview above it is ONE message for the whole
channel and must look the same to everybody. The admin panel with this
dropdown is ephemeral ("only you can see this"), so it can differ per user.
That is the line between what can be tailored and what cannot.

It narrows only where the CHANNEL grants nothing. In a control channel whoever
may write there may do everything (SPEC.md B1), so there is nothing to narrow -
and an admin with no assignment keeps every container, here as everywhere.

Why bother, when every button behind an entry checks again: a button that is
shown and can only refuse is a defect of its own (review D32). This is the
display half of the same rule the callbacks already enforce.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import cogs.control_ui as cui
from cogs.control_ui import AdminContainerSelectView

ADMIN = 4711
MINE, THEIRS = "valheim", "nginx"
CONTAINERS = [{"name": MINE, "display": "Valheim", "docker_name": MINE, "order": 1},
              {"name": THEIRS, "display": "nginx", "docker_name": THEIRS, "order": 2}]


@pytest.fixture
def world(monkeypatch):
    state = {"control_channel": False, "assigned": [MINE]}
    monkeypatch.setattr(cui, "load_config", lambda: {"servers": []})
    monkeypatch.setattr(cui, "_channel_has_permission",
                        lambda channel_id, key, config=None: state["control_channel"])

    service = MagicMock()
    service.is_user_admin.side_effect = lambda user_id, **kw: str(user_id) == str(ADMIN)
    service.may_control.side_effect = (
        lambda user_id, docker_name, **kw: str(user_id) == str(ADMIN) and (
            state["assigned"] is None or docker_name in state["assigned"]))
    monkeypatch.setattr("services.admin.admin_service.get_admin_service", lambda: service)
    return state


def _offered(view):
    dropdown = view.children[0]
    return [option.value for option in dropdown.options]


async def test_only_his_own_containers_are_offered(world):
    view = AdminContainerSelectView(SimpleNamespace(), list(CONTAINERS), 300, user_id=ADMIN)

    assert _offered(view) == [MINE], (
        "a container the admin cannot control was offered - pressing anything "
        "on its panel is refused"
    )


async def test_an_admin_without_an_assignment_is_offered_everything(world):
    """The default, here as everywhere."""
    world["assigned"] = None

    view = AdminContainerSelectView(SimpleNamespace(), list(CONTAINERS), 300, user_id=ADMIN)

    assert _offered(view) == [MINE, THEIRS]


async def test_a_control_channel_is_not_narrowed(world):
    """B1: whoever may write there may do everything, assignment or not."""
    world["control_channel"] = True

    view = AdminContainerSelectView(SimpleNamespace(), list(CONTAINERS), 300, user_id=ADMIN)

    assert _offered(view) == [MINE, THEIRS]


async def test_without_a_user_the_list_is_left_alone(world, caplog):
    """A caller that passes nobody must not lose the list silently."""
    import logging

    with caplog.at_level(logging.WARNING):
        view = AdminContainerSelectView(SimpleNamespace(), list(CONTAINERS), 300)

    assert _offered(view) == [MINE, THEIRS]
    assert any("user id" in record.getMessage().lower() for record in caplog.records), (
        "the gap passed without a word in the log"
    )
