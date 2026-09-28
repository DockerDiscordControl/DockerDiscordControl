# -*- coding: utf-8 -*-
"""What the info display knows beyond the operator's text (v3.1.0).

Every container has an info display now, not only the ones with a text set
(operator, 2026-09-28). Beyond the text it shows:

* THE GAME SERVER, for one with the player count switched on (the "Players"
  column): the name it has in the server browser, game and version, whether
  it asks for a password, the port to connect to - and who is online. Not
  every game names its players: Icarus sends empty names (opengsq issue #44),
  Satisfactory's API only counts. The display then says so.
* DOCKER'S FACTS: running since / stopped since and why, and - only with
  "details" allowed for the container, the switch that already hides CPU and
  RAM - version, image date, restart policy and memory limit. A public status
  channel should not tell a stranger which software runs in which version on
  a server whose owner chose to show less.

Everything is asked for when someone opens the display, never by the status
cycle, and within a short budget: the dropdown path answers Discord without
deferring, and Discord waits three seconds. Game query and Docker run side by
side. Times are Discord timestamps, which every viewer sees in their own
time zone and language.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import discord

from utils.logging_utils import get_module_logger
from .translation_manager import _

logger = get_module_logger('info_extras')

# Seconds the whole lookup may take, port resolution and query together
BUDGET_SECONDS = 2.5
# Seconds one port may take. A server in the LAN answers in milliseconds; a
# port that does not answer at all must not eat the whole budget before the
# next one is tried - measured 2026-09-28: Valheim lists 2456 first and
# answers only on 2457, and until the status cycle has learned that, a
# 2.5 s wait on 2456 left nothing for 2457.
PORT_SECONDS = 1.2
# Names shown; the rest becomes "+k more"
MAX_NAMES = 20
# Exit codes that are an ordinary stop, not a reason worth showing (143 = SIGTERM, `docker stop`)
ORDINARY_EXIT = (0, 143)


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
                            timeout_seconds=min(DEFAULT_QUERY_TIMEOUT_SECONDS, PORT_SECONDS))


def _is_running(name: str) -> bool:
    from services.status.status_cache_service import get_status_cache_service
    data = (get_status_cache_service().get(name) or {}).get('data')
    return bool(data and getattr(data, 'success', False) and getattr(data, 'is_running', False))


# --- the game server ---------------------------------------------------------

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
        if players.error_type == 'not_answering':
            return "⚠️ " + _("The game server does not answer - the container runs, the game in it may not.")
        return "👥 " + _("The player list cannot be read right now.")
    online = players.players_online or 0
    if players.max_players:
        head = "👥 **" + _("Players online: {count}").format(count=f"{online}/{players.max_players}") + "**"
    else:
        head = "👥 **" + _("Players online: {count}").format(count=online) + "**"
    if not online:
        return head  # "0/10" says it; a line "nobody is playing" repeated it
    if not players.names_given:
        return head + "\n" + _("This game does not send player names.")
    lines = [head] + [f"• {discord.utils.escape_markdown(name)}{_time_on_server(seconds)}"
                      for name, seconds in players.names[:MAX_NAMES]]
    hidden = online - len(lines) + 1
    if hidden > 0:
        lines.append(_("+{count} more").format(count=hidden))
    return "\n".join(lines)


def game_line(players, facts=None) -> Optional[str]:
    """"🎯 BachelorLaming · Valheim 1.0.16 · 🔒 Password · Port 2456", or None."""
    from services.infrastructure.container_facts_service import connect_port
    if players is None or not players.success:
        return None
    parts = []
    if players.server_name:
        parts.append(f"**{discord.utils.escape_markdown(players.server_name)}**")
    game = " ".join(p for p in (players.game, players.game_version) if p)
    if game:
        parts.append(discord.utils.escape_markdown(game))
    if players.password:
        parts.append("🔒 " + _("Password"))
    port = connect_port(facts, players.game_port)
    if port:
        parts.append(_("Port {port}").format(port=port))
    return "🎯 " + " · ".join(parts) if parts else None


async def player_list(server_config: Dict[str, Any]):
    """The PlayerList of a game server, or None when the container has none.

    None for a container that is not a game server with the player count
    switched on, and for one that is not running. A server that does not
    answer within the budget is a failed PlayerList. Never raises.
    """
    from services.infrastructure.game_query_service import PlayerList, get_game_query_service

    async def _ask():
        request = await _request_for(server_config)
        if request is None or not _is_running(request.container_name):
            return None
        return await get_game_query_service().get_player_list(request)

    if not server_config.get('query_enabled'):
        return None
    # FOUND BY THIS DISPLAY, 2026-09-28: the operator's Enshrouded server had
    # stopped twelve days before - its log ends on 16 September, no process
    # listens - while the container ran on (a `tail -f` keeps it alive), so it
    # stood 🟢 online all along. The support check had long since marked it
    # unreachable, and the display stayed silent about it. It says so now,
    # at once: asking again would only cost the whole budget.
    try:
        from services.infrastructure.game_query_support_service import get_game_query_support_service
        name = server_config.get('docker_name')
        if get_game_query_support_service().is_supported(name) is False:
            return PlayerList(success=False, error_type='not_answering') if _is_running(name) else None
    except (ImportError, RuntimeError, AttributeError) as e:
        logger.debug(f"Support verdict for {server_config.get('docker_name')} not readable: {e}")
    try:
        return await asyncio.wait_for(_ask(), timeout=BUDGET_SECONDS)
    except asyncio.TimeoutError:
        return PlayerList(success=False, error_type='timeout')
    except Exception as e:  # noqa: BLE001 - the info display must open without it
        logger.debug(f"Player list for {server_config.get('docker_name')} skipped: {e}")
        return None


# --- Docker's facts ----------------------------------------------------------

def _when(moment, style: str = "f") -> str:
    stamp = int(moment.timestamp())
    return f"<t:{stamp}:{style}> (<t:{stamp}:R>)"


def _restart_policy(name: Optional[str]) -> str:
    if name in ('always', 'unless-stopped'):
        return _("Restarts on its own after a crash or a reboot")
    if name == 'on-failure':
        return _("Restarts on its own after a crash")
    # "no" is what Unraid's own containers carry: Unraid starts them at boot by
    # its autostart setting, which Docker - and so DDC - cannot see. What is
    # true is only that Docker will not bring it back after a crash.
    return _("Docker does not restart it after a crash")


def format_facts(facts, details: bool, update: Optional[bool] = None) -> List[str]:
    """Lines for a ContainerFacts (services/infrastructure/container_facts_service.py).

    ``update`` is True when the registry holds a newer image than the one that
    runs - said only then, never "up to date" on an unknown answer.
    """
    if facts is None:
        return []
    lines = []
    if facts.running and facts.started_at:
        lines.append("⏱️ " + _("Running since {moment}").format(moment=_when(facts.started_at)))
    elif not facts.running and facts.finished_at:
        line = "⏹️ " + _("Stopped since {moment}").format(moment=_when(facts.finished_at))
        if facts.oom_killed:
            line += " · " + _("out of memory")
        elif facts.exit_code is not None and facts.exit_code not in ORDINARY_EXIT:
            line += " · " + _("exit code {code}").format(code=facts.exit_code)
        lines.append(line)
    if details:
        image = [discord.utils.escape_markdown(facts.version)] if facts.version else []
        if facts.image_created:
            image.append(_("image from {date}").format(date=_when(facts.image_created, "D")))
        if image:
            lines.append("📦 " + " · ".join(image))
        if update:
            lines.append("⬆️ " + _("A newer image is in the registry"))
    # One line for restarts and what restarts it - two lines with 🔁 and 🔄
    # read as the same thing twice (operator, 2026-09-28)
    restarts = [_("🔄 Restarts: {count}").format(count=facts.restart_count)] \
        if facts.restart_count is not None else []
    if details:
        restarts.append(_restart_policy(facts.restart_policy) if restarts
                        else "🔄 " + _restart_policy(facts.restart_policy))
    if restarts:
        lines.append(" · ".join(restarts))
    if facts.health:
        lines.append(_("🩺 Health check: {status}").format(status=facts.health))
    if details and facts.memory_limit:
        size = facts.memory_limit / 1024 ** 3
        text = f"{size:.1f} GB" if size >= 1 else f"{facts.memory_limit // 1024 ** 2} MB"
        lines.append("🧠 " + _("Memory limit: {size}").format(size=text))
    return lines


async def address_line(info_config: Dict[str, Any], game_port: Optional[int] = None) -> Optional[str]:
    """The address a member connects to, or None. One function for every path.

    There were three: _get_ip_info in control_ui.py and in
    status_info_integration.py (the twins validate_custom_address was
    extracted from) and the dropdown's own copy, which validated nothing.

    The port is the one set in the info form; without one, the port the game
    server names (operator, 2026-09-28: "185.137.173.157" without a port
    under a Valheim server, the port three lines higher) - but never glued to
    an address that already carries its own.
    """
    from .control_helpers import validate_custom_address, validate_custom_port
    custom_ip = str(info_config.get('custom_ip') or '').strip()
    custom_port = str(info_config.get('custom_port') or '').strip()
    port = custom_port if validate_custom_port(custom_port) else ''
    if not port and game_port and ':' not in custom_ip:
        port = str(game_port)
    if custom_ip:
        if not validate_custom_address(custom_ip):
            logger.warning(f"Invalid custom address format: {custom_ip}")
            return f"🔗 **{_('Custom Address')}:** [Invalid Format]"
        return f"🔗 **{_('Custom Address')}:** `{custom_ip}{':' + port if port else ''}`"
    try:
        from utils.common_helpers import get_wan_ip_async
        wan_ip = await get_wan_ip_async()
    except (OSError, RuntimeError, ValueError) as e:
        logger.debug(f"Could not get WAN IP: {e}")
        wan_ip = None
    return f"🌐 **{_('Public IP')}:** `{wan_ip}{':' + port if port else ''}`" if wan_ip else None


async def image_update(facts, wait: float) -> Optional[bool]:
    """Whether the registry holds a newer image than the running one; None when not known.

    The check the watchdog already had (Phase 4d, image_updates.py) ran only
    for operators with an image_update rule. The display asks through a
    six-hour cache, within what is left of its budget.
    """
    from services.automation.image_updates import (cached_remote_digest, parse_image_reference,
                                                   update_available)
    ref = parse_image_reference(facts.image_reference) if facts is not None else None
    if ref is None or not facts.running_digests:
        return None
    try:
        return update_available(await cached_remote_digest(ref, wait), set(facts.running_digests))
    except Exception as e:  # noqa: BLE001 - the display opens without it
        logger.debug(f"Image update for {facts.image_reference} not known: {e}")
        return None


@dataclass
class Extras:
    """What info_extras found, in the groups the display separates with a blank line."""
    game: List[str] = field(default_factory=list)
    docker: List[str] = field(default_factory=list)
    # The port players connect to, for the address line; None when not known
    port: Optional[int] = None

    def blocks(self) -> List[str]:
        return ["\n".join(group) for group in (self.game, self.docker) if group]


async def info_extras(server_config: Dict[str, Any]) -> Extras:
    """Everything beyond the operator's text, for the info display. Never raises.

    Game query and Docker inspect run side by side within one budget.
    """
    from services.infrastructure.container_facts_service import connect_port, get_container_facts
    name = server_config.get('docker_name')
    if not name:
        return Extras()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + BUDGET_SECONDS
    details = bool(server_config.get('allow_detailed_status', True))
    facts_task = asyncio.ensure_future(get_container_facts(name))
    players = await player_list(server_config)
    try:
        facts = await asyncio.wait_for(asyncio.shield(facts_task), timeout=BUDGET_SECONDS)
    except asyncio.TimeoutError:
        facts = None
    update = await image_update(facts, deadline - loop.time()) if details else None
    game = [game_line(players, facts), format_players(players) if players is not None else None]
    return Extras(
        game=[line for line in game if line],
        docker=format_facts(facts, details=details, update=update),
        port=connect_port(facts, players.game_port) if players is not None and players.success else None)
