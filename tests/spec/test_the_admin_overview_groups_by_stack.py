# -*- coding: utf-8 -*-
"""The Admin Overview shows each Compose stack as a group (Phase 4c, part 4).

Before the first container of a stack the Admin Overview writes the stack's
name as a bold heading line; containers outside a stack get none. The order
stays the server order - "Sort by stack" in the panel brings a stack's
containers together, and a stack whose containers are scattered shows its
heading again where it reappears rather than silently reordering the list.
A container whose status is not known yet has no known stack and no heading.
The public server overview is left as it is.

COUNTER-CHECK (2026-09-22): red before - no heading lines; the escaped name
case goes red when the stack name is written unescaped.
"""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cogs.docker_control import DockerControlCog
from services.docker_status.models import ContainerStatusResult


def _server(name):
    return {"docker_name": name, "name": name, "display_name": name, "allowed_actions": ["restart"]}


def _entry(name, project):
    result = ContainerStatusResult.success_result(
        docker_name=name, display_name=name, is_running=True,
        cpu="1%", ram="1024 MB", uptime="1h", details_allowed=True)
    result.compose_project = project
    return {"data": result, "timestamp": datetime.now(timezone.utc)}


def _description(names, entries):
    cog = object.__new__(DockerControlCog)
    cog.status_cache_service = SimpleNamespace(get=entries.get)
    cog._status_update_semaphore = asyncio.Semaphore(1)
    cog._last_status_cache_refresh = 0.0
    cog._status_fetch_failed = set()
    cog.pending_actions = {}
    info_service = MagicMock()
    info_service.get_container_info.return_value = SimpleNamespace(success=False, data=None)
    with patch("cogs.overview_embeds.load_config", return_value={}), \
         patch("services.infrastructure.container_info_service.get_container_info_service",
               return_value=info_service):
        embed, _file, _running = asyncio.run(cog._create_admin_overview_embed([_server(n) for n in names], {}))
    return embed.description


def _body(description):
    return [line for line in description.split("\n\n", 1)[1].split("\n") if line != "ㅤ"]


def test_a_stack_heading_stands_before_its_first_container():
    entries = {"db": _entry("db", "blog"), "web": _entry("web", "blog"), "plex": _entry("plex", None)}
    body = _body(_description(["db", "web", "plex"], entries))
    assert body[0] == "**blog**"
    assert [line.split(" ")[1] for line in body[1:]] == ["db", "web", "plex"]
    assert body.count("**blog**") == 1


def test_a_scattered_stack_shows_its_heading_again():
    entries = {"db": _entry("db", "blog"), "plex": _entry("plex", None), "web": _entry("web", "blog")}
    body = _body(_description(["db", "plex", "web"], entries))
    assert body.count("**blog**") == 2


def test_without_stacks_there_are_no_headings():
    entries = {"plex": _entry("plex", None)}
    body = _body(_description(["plex", "unknown"], entries))
    assert not any(line.startswith("**") for line in body)


def test_the_stack_name_cannot_format_the_message():
    entries = {"db": _entry("db", "my_*stack*")}
    assert _body(_description(["db"], entries))[0] == r"**my\_\*stack\***"
