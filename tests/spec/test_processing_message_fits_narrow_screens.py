# -*- coding: utf-8 -*-
"""The "processing" message after a container action must read well on a phone.

No ``@covers`` marker: a display finding, not a guarantee.

THE FINDING (reported by the operator on 2026-09-19 with a phone screenshot
from a control channel): after start/stop/restart, the ephemeral message
showed a box drawn with ``┌── │ └──`` inside a code block. A code block does
not reflow - it has a fixed width of about 30 characters, the German lines are
longer ("Aktualisiere Container-Status..."), and on a phone the frame broke
into pieces. The footer "Container action in progress" was a hard-coded
English string, so every language saw English below the translated box.

HOW IT IS CHECKED: the button callback runs for real up to that message. The
background task is captured instead of scheduled, its waits are skipped, and
``_`` is replaced by a marker, so the test sees which visible text went
through the translation - without restating the texts the code builds.
"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import cogs.control_ui as cui
from cogs.control_ui import ActionButton

LOCALES = Path(__file__).resolve().parents[2] / "locales"
BOX = set("┌│└─")
URL = "https://ddc.bot"


class _AsyncioProxy:
    """``asyncio`` for control_ui only: tasks are captured, sleeps are skipped."""

    def __init__(self):
        self.tasks = []
        self.sleep = AsyncMock()

    def create_task(self, coro):
        self.tasks.append(coro)
        return MagicMock()

    def __getattr__(self, name):
        return getattr(asyncio, name)


def _mark(text):
    return f"«{text}»"


def _button():
    b = ActionButton.__new__(ActionButton)
    b.cog = SimpleNamespace(pending_actions={}, status_cache_service=MagicMock())
    b.action = "restart"
    b.server_config = {"docker_name": "nginx", "display_name": "nginx",
                       "allowed_actions": ["start", "stop", "restart"]}
    b.docker_name = "nginx"
    b.display_name = "nginx"
    return b


def _interaction():
    inter = MagicMock()
    inter.response.send_message = AsyncMock()
    inter.response.defer = AsyncMock()
    inter.followup.send = AsyncMock()
    inter.edit_original_response = AsyncMock()
    inter.user.id = 4711
    inter.user.name = "Somebody"
    inter.channel.id = 300
    inter.message = None
    return inter


@pytest.fixture
def processing_embed(monkeypatch):
    spam = MagicMock()
    spam.is_enabled.return_value = False
    monkeypatch.setattr(
        "services.infrastructure.spam_protection_service.get_spam_protection_service",
        lambda: spam)
    monkeypatch.setattr(cui, "load_config", lambda: {"servers": []})
    monkeypatch.setattr(cui, "_get_cached_channel_permission",
                        lambda channel_id, key, config=None: True)
    monkeypatch.setattr(cui, "log_user_action", MagicMock())
    servers = MagicMock()
    servers.get_all_servers.return_value = []
    monkeypatch.setattr(cui, "get_server_config_service", lambda: servers)
    monkeypatch.setattr(
        "services.docker_service.docker_action_service.docker_action_service_first",
        AsyncMock(return_value=True))
    monkeypatch.setattr(
        "services.infrastructure.container_status_service.get_container_status_service",
        lambda: MagicMock())
    monkeypatch.setattr(cui, "_", _mark)
    proxy = _AsyncioProxy()
    monkeypatch.setattr(cui, "asyncio", proxy)

    inter = _interaction()

    async def run():
        await _button().callback(inter)
        assert proxy.tasks, "the button scheduled no background action"
        await proxy.tasks.pop(0)          # run_docker_action
        for leftover in proxy.tasks:      # update_all_views - not part of this check
            leftover.close()

    asyncio.run(run())
    calls = inter.edit_original_response.await_args_list
    return calls


def test_the_driver_reaches_the_processing_message(processing_embed):
    """Guard: pending message first, then the processing message."""
    assert len(processing_embed) >= 2, f"only {len(processing_embed)} edits - never reached it"


def _embed(calls):
    return calls[1].kwargs["embed"]


def test_no_fixed_width_box(processing_embed):
    embed = _embed(processing_embed)
    visible = f"{embed.title or ''}\n{embed.description or ''}"
    assert "```" not in visible, "a code block does not reflow on a phone"
    assert not BOX & set(visible), "box-drawing characters break apart on a narrow screen"


def test_every_visible_text_is_translated(processing_embed):
    embed = _embed(processing_embed)
    texts = [embed.title or ""] + (embed.description or "").splitlines()
    footer = (embed.footer.text or "").replace(URL, "").replace("•", "").strip()
    texts.append(footer)
    untranslated = [t for t in texts if any(c.isalpha() for c in t) and "«" not in t]
    assert not untranslated, f"shown without translation: {untranslated}"


def test_the_catalogs_carry_the_texts():
    """All 40 languages have both lines; German pinned as the operator saw it."""
    keys = ["Updating container status...", "Please wait ~15 seconds"]
    missing = []
    for path in sorted(LOCALES.glob("*.json")):
        if path.name == "meta.json":
            continue
        catalog = json.loads(path.read_text(encoding="utf-8"))
        missing += [f"{path.name}: {k}" for k in keys if not catalog.get(k)]
    assert not missing, missing
    de = json.loads((LOCALES / "de.json").read_text(encoding="utf-8"))
    assert de["Updating container status..."] == "Aktualisiere Container-Status..."  # language data
    assert de["Please wait ~15 seconds"] == "Bitte warten Sie ~15 Sekunden"  # language data
