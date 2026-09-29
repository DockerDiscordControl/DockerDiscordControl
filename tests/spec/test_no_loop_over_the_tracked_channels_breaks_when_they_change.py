# -*- coding: utf-8 -*-
"""No loop over the tracked channels breaks when a channel is added meanwhile.

THE FINDING (stage 4 review before v3.1.0, section 04 pass 4 F5 and section
02 pass 4 F10, verified 2026-09-29). Two refresh loops walked
channel_server_message_ids.items() LIVE and awaited Discord edits inside:
trigger_status_refresh (the refresh after an auto-action) and
update_all_views (the redraw after a button press). A /ss in a new channel
or a clean-up in that moment changed the dict between two awaits:
"dictionary changed size during iteration" - the remaining channels missed
the refresh, and after a button press the catch-all then replaced the
freshly drawn panel with "could not be refreshed".

THE CONTRACT: every loop over the tracked channels that awaits inside walks
a snapshot (list(...)).

HOW THIS TEST CAN FAIL: a new loop walks the live dict across an await.

The scan covers every such loop in cogs/ and services/; the second case runs
trigger_status_refresh with a channel added during the first edit.

COUNTER-CHECK (2026-09-29): written before the fix and red then (both loops
listed; the refresh stopped after the first channel).
"""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

PROJECT = Path(__file__).resolve().parents[2]


def test_every_awaiting_loop_walks_a_snapshot():
    live = []
    for path in sorted((PROJECT / "cogs").rglob("*.py")) + sorted((PROJECT / "services").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.For, ast.AsyncFor)):
                walked = ast.unparse(node.iter)
                if ("channel_server_message_ids" in walked and not walked.startswith("list(")
                        and any(isinstance(inner, ast.Await) for inner in ast.walk(node))):
                    live.append(f"{path.relative_to(PROJECT)}:{node.lineno}")
    assert live == [], f"loops over the live dict across an await: {live}"


def test_the_auto_action_refresh_reaches_every_channel(monkeypatch):
    from cogs.docker_control import DockerControlCog

    cog = DockerControlCog.__new__(DockerControlCog)
    cog.channel_server_message_ids = {1: {"overview": 11}, 2: {"overview": 22}}
    edited = []

    async def _update(channel_id, message_id, kind):
        edited.append(channel_id)
        cog.channel_server_message_ids.setdefault(3, {})    # a /ss elsewhere, meanwhile

    cog._update_overview_message = _update
    cog.status_cache_service = MagicMock()
    cog.get_status = AsyncMock(return_value=SimpleNamespace(success=True))
    monkeypatch.setattr("services.infrastructure.container_status_service.get_container_status_service",
                        lambda: MagicMock())
    monkeypatch.setattr("cogs.docker_control.get_server_config_service",
                        lambda: SimpleNamespace(get_server_by_docker_name=lambda n: {"docker_name": n}),
                        raising=False)

    async def _run():
        await cog.trigger_status_refresh("c", delay_seconds=0)
        for _ in range(20):
            await asyncio.sleep(0)

    asyncio.run(_run())

    assert sorted(edited) == [1, 2], f"the refresh stopped after the first channel: {edited}"
