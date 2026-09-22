# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
# -*- coding: utf-8 -*-
"""Audit 2026-09, package B: `_` (translation function) shadowing in cogs (B4, B5, B9, B12).

A function that assigns to `_` anywhere makes `_` local for the WHOLE function, so every
`_("...")` call in it either calls the assigned value (B4: an int) or raises
UnboundLocalError (B5). B9 imported a non-existent get_translation and always fell back to
untranslated text.
"""
import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from cogs.translation_manager import _ as translate

COGS_DIR = Path(__file__).resolve().parents[3] / "cogs"


def _collect_underscore_uses(node, stores, loads):
    """Collect `_` stores/loads in node's own scope (nested scopes have their own locals)."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            if getattr(child, "name", None) == "_":
                stores.append(child.lineno)
            continue
        if isinstance(child, ast.Name) and child.id == "_":
            (stores if isinstance(child.ctx, ast.Store) else loads).append(child.lineno)
        _collect_underscore_uses(child, stores, loads)


def _functions_shadowing_translation(path: Path):
    """Yield (lineno, name) for functions that assign `_` (Name store) and also load `_`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        stores, loads = [], []
        _collect_underscore_uses(fn, stores, loads)
        if stores and loads:
            yield fn.lineno, fn.name


def test_no_cog_function_shadows_translation_function():
    offenders = []
    for path in sorted(COGS_DIR.glob("*.py")):
        for lineno, name in _functions_shadowing_translation(path):
            offenders.append(f"{path.name}:{lineno} {name}")
    assert offenders == [], f"functions assigning `_` while calling _(): {offenders}"


def test_no_reference_to_nonexistent_get_translation():
    """B9: cogs.translation_manager has no get_translation(); nothing may import it."""
    import cogs.translation_manager as tm
    assert not hasattr(tm, "get_translation")
    offenders = []
    for path in sorted(COGS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders += [f"{path.name}:{n.lineno}" for n in ast.walk(tree)
                      if isinstance(n, ast.ImportFrom) and any(a.name == "get_translation" for a in n.names)]
    assert offenders == []


def test_admin_overview_embed_imports_translate_once():
    """B12: ruff F811 - `translate` was imported twice in _create_admin_overview_embed."""
    # The overview embeds moved to overview_embeds.py in the Phase 3 cog split.
    tree = ast.parse((COGS_DIR / "overview_embeds.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_create_admin_overview_embed")
    imports = [a for n in ast.walk(fn) if isinstance(n, ast.ImportFrom)
               for a in n.names if a.asname == "translate"]
    assert len(imports) == 1


# ---------------------------------------------------------------------------
# B4: get_status with hidden details must not call an int
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_status_hidden_details_running_container():
    from cogs.status_handlers import StatusHandlersMixin

    mixin = StatusHandlersMixin()
    mixin.bot = MagicMock()
    server_config = {
        "name": "Test Server",
        "docker_name": "test_container",
        "display_name": "Test Server",
        "allow_detailed_status": False,
    }
    info = {"State": {"Status": "running", "Running": True, "StartedAt": "2025-01-01T00:00:00Z"},
            "Name": "/test_container"}

    with patch("cogs.status_handlers.get_docker_info_dict_service_first",
               new_callable=AsyncMock, return_value=info), \
         patch("cogs.status_handlers.get_docker_stats_service_first",
               new_callable=AsyncMock, return_value=None):
        result = await mixin.get_status(server_config)

    assert result.success is True, getattr(result, "error_message", None)
    assert result.is_running is True
    assert result.cpu == translate("Hidden")
    assert result.ram == translate("Hidden")
    assert result.uptime not in ("", "Error", None)


# ---------------------------------------------------------------------------
# B5: /control error messages must not raise UnboundLocalError
# ---------------------------------------------------------------------------

def _control_ctx():
    ctx = MagicMock()
    ctx.defer = AsyncMock()
    ctx.respond = AsyncMock()
    ctx.followup.send = AsyncMock()
    ctx.channel.id = 1
    ctx.channel_id = 1
    ctx.response.is_done.return_value = True
    return ctx


def _control_cog():
    from cogs.docker_control import DockerControlCog
    cog = object.__new__(DockerControlCog)
    cog._check_spam_protection = AsyncMock(return_value=True)
    return cog


@pytest.mark.asyncio
async def test_control_config_load_failure_sends_message():
    from cogs.docker_control import DockerControlCog
    cog, ctx = _control_cog(), _control_ctx()
    with patch.object(DockerControlCog, "config", new_callable=PropertyMock, return_value={}), \
         patch("cogs.docker_control._channel_has_permission", return_value=True), \
         patch("cogs.docker_control.load_config", return_value={}), patch("cogs.overview_embeds.load_config", return_value={}):
        await DockerControlCog.control.callback(cog, ctx)

    ctx.followup.send.assert_awaited_once_with(translate("❌ Could not load configuration."))


@pytest.mark.asyncio
async def test_control_no_servers_sends_message():
    from cogs.docker_control import DockerControlCog
    cog, ctx = _control_cog(), _control_ctx()
    scs = MagicMock()
    scs.get_all_servers.return_value = []
    with patch.object(DockerControlCog, "config", new_callable=PropertyMock, return_value={}), \
         patch("cogs.docker_control._channel_has_permission", return_value=True), \
         patch("cogs.docker_control.load_config", return_value={"language": "en"}), patch("cogs.overview_embeds.load_config", return_value={"language": "en"}), \
         patch("cogs.docker_control.get_server_config_service", return_value=scs):
        await DockerControlCog.control.callback(cog, ctx)

    ctx.followup.send.assert_awaited_once_with(translate("❌ No servers configured."))
