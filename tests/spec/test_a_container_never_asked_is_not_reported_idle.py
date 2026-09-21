# -*- coding: utf-8 -*-
"""A container whose status was never read is not reported as not running.

THE FINDING (review D14, pass 2, section 01 F3 and F4): both bulk buttons ask
`status_cache_service.get(docker_name)` and start from `is_running = False`.
When the cache has no entry for that container - right after it was added,
right after a restart before the cache is warm, or once the entry expired -
the lookup answers nothing, `is_running` keeps its default, and the container
lands in `skipped_count`.

The operator then reads "Skipped (not running): N containers". The container
was never asked and never touched, so what the report claims about it is a
measurement that was not taken. Both paths carry the same code and the same
sentence.
"""

from types import SimpleNamespace

import pytest

from cogs import admin_overview
from services.docker_status.models import ContainerStatusResult

RUNNING = "runner"
STOPPED = "sleeper"
UNKNOWN = "stranger"


class _Response:
    async def defer(self, **kwargs):
        return None


class _Followup:
    def __init__(self):
        self.embeds = []

    async def send(self, content=None, embed=None, **kwargs):
        if embed is not None:
            self.embeds.append(embed)


class _Interaction:
    def __init__(self):
        self.response = _Response()
        self.followup = _Followup()
        self.user = SimpleNamespace(id=1)
        self.channel = SimpleNamespace(id=2)


@pytest.fixture
def world(monkeypatch):
    """Three containers: one running, one stopped, one the cache never saw."""
    servers = [{"docker_name": name, "allowed_actions": ["restart", "stop"]}
               for name in (RUNNING, STOPPED, UNKNOWN)]
    monkeypatch.setattr(admin_overview, "get_server_config_service",
                        lambda: SimpleNamespace(get_all_servers=lambda: servers))

    def _status(is_running):
        return {"data": ContainerStatusResult(success=True, docker_name="x",
                                              display_name="x",
                                              is_running=is_running)}

    cache = {RUNNING: _status(True), STOPPED: _status(False)}
    monkeypatch.setattr(admin_overview, "get_status_cache_service",
                        lambda: SimpleNamespace(get=lambda name: cache.get(name)))

    async def _action(action, name, **kwargs):
        return True

    import services.docker_service.docker_action_service as action_module
    monkeypatch.setattr(action_module, "docker_action_service_first", _action)
    monkeypatch.setattr(admin_overview.asyncio, "sleep",
                        lambda seconds: _done())
    return _Interaction()


async def _done():
    return None


def _cog():
    return SimpleNamespace(_bulk_operation_in_progress=False)


async def _run(button_class, interaction):
    button = object.__new__(button_class)
    button.cog = _cog()
    button.channel_id = 2
    await button.callback(interaction)
    return interaction.followup.embeds[-1].description


@pytest.mark.asyncio
@pytest.mark.parametrize("button_class", [admin_overview.ConfirmRestartAllButton,
                                          admin_overview.ConfirmStopAllButton])
async def test_the_unread_one_is_not_called_not_running(world, button_class):
    description = await _run(button_class, world)

    assert "Skipped (not running): **1**" in description or \
           "Skipped (not running)" not in description, (
        f"two containers were skipped and only one of them is really idle: {description}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("button_class", [admin_overview.ConfirmRestartAllButton,
                                          admin_overview.ConfirmStopAllButton])
async def test_the_report_says_it_could_not_be_read(world, button_class):
    description = await _run(button_class, world)

    assert "not checked" in description.lower() or "could not be read" in description.lower(), (
        f"the container was never asked and the report does not say so: {description}"
    )


@pytest.mark.asyncio
async def test_the_running_one_is_still_acted_on(world):
    """Counter-check: the work itself must be unaffected."""
    description = await _run(admin_overview.ConfirmRestartAllButton, world)

    assert "Successfully restarted: **1**" in description
