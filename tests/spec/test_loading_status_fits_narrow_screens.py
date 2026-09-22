# -*- coding: utf-8 -*-
"""The "loading status" messages must read well on a phone, in every language.

No ``@covers`` marker: a display finding, not a guarantee.

THE FINDING (2026-09-19): the sibling of the "processing" message fixed in
test_processing_message_fits_narrow_screens.py. The operator's screenshot
showed that one; these are built the same way - a ┌── │ └── frame inside a
code block, which does not reflow and breaks apart on a narrow screen - and
have the same hard-coded English footer.

HOW IT IS CHECKED: the real code path runs up to the message, ``_`` is
replaced by a marker, and the test looks at what would be shown.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cogs.status_handlers as sh_mod
from cogs.status_handlers import StatusHandlersMixin

LOCALES = Path(__file__).resolve().parents[2] / "locales"
BOX = set("┌│└─")
URL = "https://ddc.bot"


def _mark(text):
    return f"«{text}»"


def _no_box(embed):
    visible = f"{embed.title or ''}\n{embed.description or ''}"
    assert "```" not in visible, "a code block does not reflow on a phone"
    assert not BOX & set(visible), "box-drawing characters break apart on a narrow screen"


def _untranslated(embed):
    texts = [embed.title or ""] + (embed.description or "").splitlines()
    texts.append((embed.footer.text or "").replace(URL, "").replace("•", "").strip())
    return [t for t in texts if any(c.isalpha() for c in t) and "«" not in t]


# --- the status embed while the background loop has no data yet -------------

@pytest.fixture
def status_loading_embed():
    mixin = StatusHandlersMixin()
    mixin.status_cache_service = MagicMock()
    mixin.status_cache_service.get.return_value = None     # no cache entry yet
    mixin.pending_actions = {}
    mixin.expanded_states = {}
    mixin.cache_ttl_seconds = 75
    servers = MagicMock()
    servers.get_all_servers.return_value = [{"docker_name": "nginx", "name": "nginx"}]
    import asyncio
    with patch.object(sh_mod, "get_server_config_service", return_value=servers), \
            patch.object(sh_mod, "_", _mark):
        embed, _view, _running = asyncio.run(mixin._generate_status_embed_and_view(
            1, "nginx", {"docker_name": "nginx"}, {"language": "en"}))
    return embed


def test_status_driver_reaches_the_loading_message(status_loading_embed):
    """Guard: the loading branch, not the error branch ("Could not retrieve")."""
    visible = f"{status_loading_embed.description}"
    assert "Could not retrieve" not in visible and status_loading_embed.color.value == 0x3498db


def test_status_loading_has_no_fixed_width_box(status_loading_embed):
    _no_box(status_loading_embed)


def test_status_loading_is_translated(status_loading_embed):
    assert not _untranslated(status_loading_embed), _untranslated(status_loading_embed)


def test_the_catalogs_carry_the_status_loading_texts():
    keys = ["Loading Status", "Fetching container data...",
            "Background process running", "Please wait for fresh data"]
    missing = []
    for path in sorted(LOCALES.glob("*.json")):
        if path.name == "meta.json":
            continue
        catalog = json.loads(path.read_text(encoding="utf-8"))
        missing += [f"{path.name}: {k}" for k in keys if not catalog.get(k)]
    assert not missing, missing
    de = json.loads((LOCALES / "de.json").read_text(encoding="utf-8"))
    assert de["Loading Status"] == "Status wird geladen"  # language data
    assert de["Fetching container data..."] == "Lade Container-Daten..."  # language data


# --- the toggle button when the cache has no entry for the container ---------

@pytest.fixture
def toggle_loading_embed():
    import asyncio
    import cogs.control_ui as cui
    from cogs.control_ui import ToggleButton

    cog = MagicMock()
    cog.expanded_states = {}
    cog.pending_actions = {}
    cog.status_cache_service.get.return_value = None        # no cache entry
    button = ToggleButton(cog, {"docker_name": "nginx", "name": "nginx"}, is_running=True, row=0)
    interaction = MagicMock()
    interaction.user.id = 4711
    interaction.channel.id = 99
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.message = MagicMock()
    interaction.message.edit = AsyncMock()
    spam = MagicMock()
    spam.is_enabled.return_value = False
    with patch("services.infrastructure.spam_protection_service.get_spam_protection_service",
               return_value=spam), \
            patch.object(cui, "load_config", return_value={"language": "en"}), \
            patch.object(cui, "_", _mark):
        asyncio.run(button.callback(interaction))
    interaction.message.edit.assert_awaited_once()
    return interaction.message.edit.await_args.kwargs["embed"]


def test_toggle_driver_reaches_the_loading_message(toggle_loading_embed):
    """Guard: the no-cache branch of the toggle button (blue loading embed)."""
    assert toggle_loading_embed.color.value == 0x3498db


def test_toggle_loading_has_no_fixed_width_box(toggle_loading_embed):
    _no_box(toggle_loading_embed)


def test_toggle_loading_is_translated(toggle_loading_embed):
    assert not _untranslated(toggle_loading_embed), _untranslated(toggle_loading_embed)
