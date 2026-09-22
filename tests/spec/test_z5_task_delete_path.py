# -*- coding: utf-8 -*-
# @covers Z5
"""Z5, second path - deleting scheduled tasks.

Z5 says: no intervention without channel permission, **on every path**. The
existing coverage (``test_z5_channel_permission.py``) only checks ``ActionButton``,
i.e. start/stop/restart. The second intervention path - deleting a scheduled
task - was not covered, and that is exactly where the gap is.

THE CHAIN, read through in full (2026-09-17)::

    InfoButton.callback           control_ui.py:1032 / :1086
      has_control = is_admin_control or <channel permission>  <-- title heuristic
      -> ContainerInfoAdminView   control_ui.py:1058 / :1093
         -> TaskManagementButton  status_info_integration.py:55  (unconditional)
            -> TaskManagementView              :1337
               -> DeleteTasksButton.callback   :1422   no check
                  -> ContainerTaskDeleteButton.callback :2567  no check
                     -> delete_task()          :2585

So an old message title ``Admin Control`` is enough to get a view from which
scheduled tasks can be deleted - without a CURRENT channel permission being
checked anywhere along the way. This is the same case for which the operator
decided on 2026-09-16 that old panels must be ineffective immediately;
``control_ui.py:304`` has already been fixed for that.

A MISTAKE OF MY OWN that belongs here: SPEC.md listed ``:1019-1025`` and
``:1072-1079`` as *"only toggle info display and admin buttons"* and thus as
purely presentational. That was wrong - they decide on building the view that
carries the delete path. The comment at ``:1053`` even says so openly:
"Don't re-check channel permission as it would ignore admin control context".

SECOND FINDING, same place: the same intervention requires the permission
``schedule`` on one path (``control_ui.py:1276``), and none at all on the other.
``status_info_integration.py`` does not know the string ``'schedule'``.

DELIMITED, because checked: the two web paths (``tasks_bp.py:194``,
``task_management_service.py:817``) hang on ``@auth.login_required`` - the
panel has its own permission model, not the channel model. They are not part
of this finding.

COUNTER-CHECK (performed 2026-09-17): 2 red, 1 green - exactly as predicted,
and both failures for the right reason.

*First:* the stack trace showed literally that ``control_ui.py`` built the view
although ``control: False`` was in the configuration - solely because of the
message title. *Second:* ``ContainerTaskDeleteButton`` did not contain the
string ``'schedule'`` anywhere.

Three traps had been named beforehand and none occurred: ``pytest-asyncio`` runs,
the tripwire on ``cogs.status_info_integration.ContainerInfoAdminView``
takes effect despite the function-local import, and the guard
``is_user_admin.called`` proves that the flow did not turn off earlier. The
opposite-direction test was green from the start - without it one could delete
building the view without replacement and the first test would stay green.

After the fix: 3 green. ``test_z5_channel_permission.py`` unchanged
3 green, ``tests/unit/cogs`` unchanged 267, ``tests/spec`` 57.

WHAT THE FIX CHANGES: at both places only the CURRENT channel permission
decides now, and the second delete path checks ``'schedule'`` like its
twin. A panel that was posted while the channel still had the permission
is ineffective after revocation - the operator's decision of
2026-09-16, applied here to two places that had back then been wrongly
classified as "purely presentational".
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import cogs.control_ui as cui
from cogs.control_ui import InfoButton


class _ViewBuilt(Exception):
    """Tripwire: raised as soon as the admin view is built.

    Without it the test would have to take the finished view apart. This way
    the question suffices: was it built at all? That is the guarantee.
    """


def _interaction(*, embed_title):
    """Interaction whose message optionally carries an 'Admin Control' title."""
    inter = MagicMock()
    inter.response.send_message = AsyncMock()
    inter.response.defer = AsyncMock()
    inter.followup.send = AsyncMock()
    inter.edit_original_response = AsyncMock()
    inter.user.id = 4711
    inter.user.name = "Somebody"
    inter.channel.id = 300
    if embed_title is None:
        inter.message = None
    else:
        inter.message = SimpleNamespace(embeds=[SimpleNamespace(title=embed_title)])
    return inter


def _button():
    """InfoButton without the py-cord constructor - ``callback`` is what is checked."""
    b = InfoButton.__new__(InfoButton)
    b.cog = SimpleNamespace()
    b.server_config = {"docker_name": "nginx", "display_name": "nginx"}
    b.docker_name = "nginx"
    b.display_name = "nginx"
    return b


@pytest.fixture
def environment(monkeypatch):
    """Clear everything except the channel check out of the way.

    IMPORTANT: ``is_admin`` (control_ui.py:1002) switches off the info permission
    check. If the test user were accidentally an admin, he would get through for
    the WRONG reason and the test would be green without proving anything. The
    admin service therefore explicitly returns "not an admin", and the guard
    below proves that it was actually asked.
    """
    spam = MagicMock()
    spam.is_enabled.return_value = False
    monkeypatch.setattr(
        "services.infrastructure.spam_protection_service.get_spam_protection_service",
        lambda: spam,
    )

    admin = MagicMock()
    admin.is_user_admin.return_value = False
    monkeypatch.setattr("services.admin.admin_service.get_admin_service", lambda: admin)

    # Channel has 'info' (otherwise it already ends at :1005), but NOT 'control'.
    monkeypatch.setattr(cui, "load_config", lambda: {
        "servers": [],
        "channel_permissions": {"300": {"commands": {"info": True, "control": False}}},
    })

    info_service = MagicMock()
    info_service.get_container_info.return_value = SimpleNamespace(
        success=True,
        data=SimpleNamespace(to_dict=lambda: {"enabled": True, "info_text": "x"}),
    )
    monkeypatch.setattr(
        "services.infrastructure.container_info_service.get_container_info_service",
        lambda: info_service,
    )

    def _tripwire(*_a, **_k):
        raise _ViewBuilt()

    monkeypatch.setattr(
        "cogs.status_info_integration.ContainerInfoAdminView", _tripwire
    )
    return admin


@pytest.mark.asyncio
async def test_old_admin_title_creates_no_view_with_delete_path(environment, monkeypatch):
    """An old 'Admin Control' title does not replace the missing channel permission.

    The view carries ``TaskManagementButton`` unconditionally
    (status_info_integration.py:55) and with it the path to ``delete_task()``. If
    it is built without a current channel permission, Z5 is broken on this path.
    """
    button = _button()
    inter = _interaction(embed_title="🛠️ Admin Control: nginx")

    try:
        await button.callback(inter)
    except _ViewBuilt:
        pytest.fail(
            "The admin view was built solely because of the message title - "
            "without channel permission 'control'. It carries the task delete button and "
            "thus a path to delete_task(). Z5 requires the check on EVERY path."
        )

    assert environment.is_user_admin.called, (
        "The admin service was never asked - so the flow turned off earlier "
        "and this test does not check what it claims to check."
    )


@pytest.mark.asyncio
async def test_with_channel_permission_the_view_is_built(monkeypatch):
    """The opposite direction - otherwise 'never build a view' would also be green.

    Without this case one could delete building the view without replacement and
    the test above would stay green without the guarantee being worth anything.
    """
    spam = MagicMock()
    spam.is_enabled.return_value = False
    monkeypatch.setattr(
        "services.infrastructure.spam_protection_service.get_spam_protection_service",
        lambda: spam,
    )
    admin = MagicMock()
    admin.is_user_admin.return_value = False
    monkeypatch.setattr("services.admin.admin_service.get_admin_service", lambda: admin)
    monkeypatch.setattr(cui, "load_config", lambda: {
        "servers": [],
        "channel_permissions": {"300": {"commands": {"info": True, "control": True}}},
    })
    info_service = MagicMock()
    info_service.get_container_info.return_value = SimpleNamespace(
        success=True,
        data=SimpleNamespace(to_dict=lambda: {"enabled": True, "info_text": "x"}),
    )
    monkeypatch.setattr(
        "services.infrastructure.container_info_service.get_container_info_service",
        lambda: info_service,
    )

    def _tripwire(*_a, **_k):
        raise _ViewBuilt()

    monkeypatch.setattr(
        "cogs.status_info_integration.ContainerInfoAdminView", _tripwire
    )

    button = _button()
    inter = _interaction(embed_title=None)

    with pytest.raises(_ViewBuilt):
        await button.callback(inter)


def test_the_delete_path_checks_the_schedule_permission():
    """Both delete paths must require the same permission.

    ``control_ui.py:1276`` asks for 'schedule'. ``status_info_integration.py``
    did not even know the string - whoever has 'control' but deliberately NOT
    'schedule' could still delete via the second path.

    The source is checked, because otherwise the callback would only be reachable
    via half a Discord scaffold. The project uses the same means in
    test_z6_docker_actions.py for the call sites.
    """
    from pathlib import Path
    import re

    # ContainerTaskDeleteButton moved to task_ui.py in the Phase 3 split.
    source = (Path(__file__).resolve().parents[2]
              / "cogs" / "task_ui.py").read_text(encoding="utf-8")

    # The body of ContainerTaskDeleteButton.callback up to the next class.
    start = source.index("class ContainerTaskDeleteButton")
    rest = source[start:]
    end = rest.find("\nclass ", 1)
    body = rest[:end] if end > 0 else rest

    assert "delete_task(" in body, (
        "The delete call is no longer in this class - the test searches "
        "in the wrong place and would stay green without proving anything."
    )
    assert re.search(r"['\"]schedule['\"]", body), (
        "ContainerTaskDeleteButton deletes scheduled tasks without checking the "
        "'schedule' permission. The twin control_ui.py:1276 checks it - "
        "so the same intervention requires a different permission depending on the path."
    )
