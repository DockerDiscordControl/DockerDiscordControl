# -*- coding: utf-8 -*-
"""Who is playing, for the info display (v3.0.2).

Every container has an info display now, not only the ones with a text set
(operator, 2026-09-28). For a game server with the player count switched on
(the "Players" column) it names who is online. The names are asked for when
someone opens the display - the status cycle keeps asking for the count
alone - and within a short budget: the dropdown path answers Discord without
deferring, and Discord waits three seconds.

Not every game names its players: Icarus sends empty names (opengsq issue
#44), Satisfactory's API only counts. The display then says so instead of
showing an empty list.
"""

import asyncio
from typing import Any, Dict, Optional

import discord

from utils.logging_utils import get_module_logger
from .translation_manager import _

logger = get_module_logger('player_list_info')

# Seconds the whole lookup may take, port resolution and query together
BUDGET_SECONDS = 2.5
# Names shown; the rest becomes "+k more"
MAX_NAMES = 20


async def _request_for(server_config: Dict[str, Any]):
    """The query for this container, chosen as the status cycle chooses it, or None."""
    from app.utils.web_helpers import _get_advanced_setting
    from services.infrastructure.game_query_service import (
        DEFAULT_QUERY_TIMEOUT_SECONDS, TOKEN_PROTOCOLS, GameQueryRequest, get_game_query_service)
    from services.infrastructure.game_query_support_service import get_game_query_support_service
    name = server_config.get('docker_name')
    if not name or not server_config.get('query_enabled') \
            or not _get_advanced_setting('DDC_ENABLE_OPENGSQ', True, bool):
        return None
    support = get_game_query_support_service()
    if support.is_supported(name) is False:
        return None  # found unreachable; the status cycle skips it too, so there is no count either
    proto = server_config.get('query_protocol', 'source')
    if proto not in TOKEN_PROTOCOLS:
        proto = support.get_protocol(name) or proto
    host, ports = await get_game_query_service().resolve_query_candidates(
        name, server_config.get('query_host', ''), server_config.get('query_port', 0), proto)
    if not host or not ports:
        return None
    return GameQueryRequest(container_name=name, protocol=proto, host=host, port=ports[0],
                            candidate_ports=tuple(ports[1:4]), token=server_config.get('query_token', ''),
                            timeout_seconds=min(DEFAULT_QUERY_TIMEOUT_SECONDS, BUDGET_SECONDS))


def _is_running(name: str) -> bool:
    from services.status.status_cache_service import get_status_cache_service
    data = (get_status_cache_service().get(name) or {}).get('data')
    return bool(data and getattr(data, 'success', False) and getattr(data, 'is_running', False))


def _time_on_server(seconds: Optional[float]) -> str:
    if seconds is None or seconds < 0:
        return ""
    minutes = int(seconds // 60)
    if minutes < 1:
        return " · " + _("under a minute")
    if minutes < 60:
        return " · " + _("{minutes} min").format(minutes=minutes)
    return " · " + _("{hours} h {minutes} min").format(hours=minutes // 60, minutes=minutes % 60)


def format_players(players) -> str:
    """The block for a PlayerList (services/infrastructure/game_query_service.py)."""
    if not players.success:
        return "👥 " + _("The player list cannot be read right now.")
    online = players.players_online or 0
    if players.max_players:
        head = "👥 **" + _("Players online: {count}").format(count=f"{online}/{players.max_players}") + "**"
    else:
        head = "👥 **" + _("Players online: {count}").format(count=online) + "**"
    if not online:
        return head + "\n" + _("Nobody is playing right now.")
    if not players.names_given:
        return head + "\n" + _("This game does not send player names.")
    lines = [head] + [f"• {discord.utils.escape_markdown(name)}{_time_on_server(seconds)}"
                      for name, seconds in players.names[:MAX_NAMES]]
    hidden = online - len(lines) + 1
    if hidden > 0:
        lines.append(_("+{count} more").format(count=hidden))
    return "\n".join(lines)


async def players_block(server_config: Dict[str, Any]) -> Optional[str]:
    """The player block for a container's info display, or None when it has none.

    None for a container that is not a game server with the player count
    switched on, and for one that is not running. Never raises.
    """
    async def _ask():
        request = await _request_for(server_config)
        if request is None or not _is_running(request.container_name):
            return None
        from services.infrastructure.game_query_service import get_game_query_service
        return await get_game_query_service().get_player_list(request)

    if not server_config.get('query_enabled'):
        return None
    try:
        players = await asyncio.wait_for(_ask(), timeout=BUDGET_SECONDS)
    except asyncio.TimeoutError:
        from services.infrastructure.game_query_service import PlayerList
        players = PlayerList(success=False, error_type='timeout')
    except Exception as e:  # noqa: BLE001 - the info display must open without it
        logger.debug(f"Player list for {server_config.get('docker_name')} skipped: {e}")
        return None
    return format_players(players) if players is not None else None
