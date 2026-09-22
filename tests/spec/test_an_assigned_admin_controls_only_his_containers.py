# -*- coding: utf-8 -*-
# @covers Z5
"""An assigned admin acts on their own containers, and on no others.

The enforcement half of the operator's request (review F2; F1 built the rule
and the format). In a status channel, where the channel permits nothing, the
global admin list is what lets an admin act (SPEC.md B2). With an assignment
in `admins.json` that right narrows to the containers named there.

WHAT MUST NOT CHANGE, and is checked here in every case: an admin WITHOUT an
assignment keeps every container. That is every admin until somebody makes
one, so getting it wrong would have locked the operator out of their own
installation on the first run.

And B1 is untouched. The channel branch is asked before the admin branch and
is not narrowed by anything - whoever may write in a control channel still
does everything there. The assignment bites only where the channel permits
nothing.

The sites covered: start/stop/restart (control_ui), deleting a task from the
control panel and from the info view (the two twins), and creating a task.
A task button knows its task and not its container, so the container is
looked up - but only for an admin who HAS an assignment, because for everyone
else the answer cannot depend on it and a missing task would otherwise refuse
somebody who is allowed today.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import cogs.control_ui as cui
from cogs.control_ui import ActionButton, TaskDeleteButton

ADMIN = 4711
MINE, THEIRS = "valheim", "nginx"


class _Passed(Exception):
    """Tripwire: raised once the permission check has been passed."""


def _tripwire(*_a, **_k):
    raise _Passed()


def _interaction():
    inter = MagicMock()
    inter.response.send_message = AsyncMock()
    inter.response.defer = AsyncMock()
    inter.followup.send = AsyncMock()
    inter.edit_original_response = AsyncMock()
    inter.user.id = ADMIN
    inter.user.name = "Luigi"
    inter.channel.id = 300
    inter.channel_id = 300
    inter.message = None
    return inter


@pytest.fixture
def status_channel(monkeypatch):
    """A status channel - 'info' yes, 'control' and 'schedule' no - plus the list."""
    spam = MagicMock()
    spam.is_enabled.return_value = False
    monkeypatch.setattr(
        "services.infrastructure.spam_protection_service.get_spam_protection_service",
        lambda: spam)
    config = {"servers": [], "channel_permissions": {
        "300": {"commands": {"info": True, "control": False, "schedule": False}}}}
    monkeypatch.setattr(cui, "load_config", lambda: config)
    monkeypatch.setattr("cogs.status_info_integration.load_config", lambda: config)
    monkeypatch.setattr("cogs.task_ui.load_config", lambda: config)  # moved there (Phase 3)
    monkeypatch.setattr("cogs.control_helpers.load_config", lambda: config)

    state = {"containers": [MINE]}

    service = MagicMock()
    service.is_user_admin.side_effect = lambda user_id, **kw: str(user_id) == str(ADMIN)
    service.get_admin_containers.side_effect = (
        lambda user_id, **kw: state["containers"] if str(user_id) == str(ADMIN) else [])
    service.may_control.side_effect = (
        lambda user_id, docker_name, **kw: str(user_id) == str(ADMIN) and (
            state["containers"] is None or str(docker_name) in state["containers"]))
    monkeypatch.setattr("services.admin.admin_service.get_admin_service", lambda: service)
    return state


def _action_button(docker_name):
    button = ActionButton.__new__(ActionButton)
    button.cog = SimpleNamespace(pending_actions={})
    button.action = "start"
    button.server_config = {"docker_name": docker_name, "display_name": docker_name,
                            "allowed_actions": ["start", "stop", "restart"]}
    button.docker_name = docker_name
    button.display_name = docker_name
    return button


async def test_he_starts_his_own_container(status_channel, monkeypatch):
    monkeypatch.setattr(cui, "_get_pending_embed", _tripwire)

    with pytest.raises(_Passed):
        await _action_button(MINE).callback(_interaction())


async def test_he_does_not_start_somebody_elses(status_channel, monkeypatch):
    monkeypatch.setattr(cui, "_get_pending_embed", _tripwire)
    button = _action_button(THEIRS)
    inter = _interaction()

    await button.callback(inter)

    assert button.cog.pending_actions == {}, (
        "the container was queued although it is not one of this admin's"
    )
    sent = " ".join(str(a) for c in inter.followup.send.await_args_list for a in c.args)
    assert "not allowed in this channel" in sent, sent


@pytest.mark.parametrize("container", [MINE, THEIRS])
async def test_an_admin_without_an_assignment_still_starts_everything(
        status_channel, monkeypatch, container):
    """The promise that must survive this feature - see the file docstring."""
    status_channel["containers"] = None          # no assignment at all
    monkeypatch.setattr(cui, "_get_pending_embed", _tripwire)

    with pytest.raises(_Passed):
        await _action_button(container).callback(_interaction())


def _task_button(cls, task_id="t1"):
    button = cls.__new__(cls)
    button.cog = SimpleNamespace()
    button.task_id = task_id
    button.task_description = "Daily restart"
    button.description = "Daily restart"
    return button


def _task_of(container):
    return SimpleNamespace(container_name=container, task_id="t1")


TASK_BUTTONS = ["control_panel", "info_view"]


def _delete_button(kind):
    if kind == "control_panel":
        return _task_button(TaskDeleteButton)
    from cogs.status_info_integration import ContainerTaskDeleteButton
    return _task_button(ContainerTaskDeleteButton)


@pytest.mark.parametrize("kind", TASK_BUTTONS)
async def test_he_deletes_a_task_of_his_own_container(status_channel, monkeypatch, kind):
    monkeypatch.setattr("services.scheduling.scheduler.find_task_by_id",
                        lambda _id: _task_of(MINE))
    monkeypatch.setattr("services.scheduling.scheduler.delete_task", _tripwire)

    with pytest.raises(_Passed):
        await _delete_button(kind).callback(_interaction())


@pytest.mark.parametrize("kind", TASK_BUTTONS)
async def test_he_does_not_delete_a_task_of_another_container(status_channel, monkeypatch, kind):
    monkeypatch.setattr("services.scheduling.scheduler.find_task_by_id",
                        lambda _id: _task_of(THEIRS))
    monkeypatch.setattr("services.scheduling.scheduler.delete_task", _tripwire)
    inter = _interaction()

    await _delete_button(kind).callback(inter)      # must NOT raise the tripwire

    sent = " ".join(str(a) for c in inter.followup.send.await_args_list for a in c.args)
    assert "permission" in sent.lower(), sent


@pytest.mark.parametrize("kind", TASK_BUTTONS)
async def test_a_task_nobody_can_place_is_refused(status_channel, monkeypatch, kind):
    """There is no way to tell whose it is, so it is not deleted."""
    monkeypatch.setattr("services.scheduling.scheduler.find_task_by_id", lambda _id: None)
    monkeypatch.setattr("services.scheduling.scheduler.delete_task", _tripwire)
    inter = _interaction()

    await _delete_button(kind).callback(inter)

    sent = " ".join(str(a) for c in inter.followup.send.await_args_list for a in c.args)
    assert "permission" in sent.lower(), sent


@pytest.mark.parametrize("kind", TASK_BUTTONS)
async def test_an_unassigned_admin_is_never_refused_for_lack_of_permission(
        status_channel, monkeypatch, kind):
    """The promise the lookup must not be allowed to break.

    For an admin with no assignment the answer cannot depend on which container
    a task belongs to, so a task that cannot be found must not turn into a
    permission refusal. The info-view button looks the task up on its own
    afterwards, for its log line, and answers "Task not found" - which is a
    different statement and the right one. The first version of this test
    forbade ANY lookup and was wrong about the code, not about the rule.
    """
    status_channel["containers"] = None
    monkeypatch.setattr("services.scheduling.scheduler.find_task_by_id", lambda _id: None)
    monkeypatch.setattr("services.scheduling.scheduler.delete_task", _tripwire)
    inter = _interaction()

    try:
        await _delete_button(kind).callback(inter)
    except _Passed:
        return          # the control-panel twin deletes without looking first

    sent = " ".join(str(a) for c in inter.followup.send.await_args_list for a in c.args)
    assert "permission" not in sent.lower(), (
        f"an admin with no assignment was refused on permission grounds: {sent}"
    )
    assert "not found" in sent.lower(), sent
