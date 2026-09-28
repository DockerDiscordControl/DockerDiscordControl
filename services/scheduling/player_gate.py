# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Restart or stop a game server only when nobody plays - and say so beforehand.

THE OPERATOR'S IDEA (2026-09-28, v3.1.0): DDC has known the player counts since
v2.3, but neither scheduled tasks nor auto-actions used them. "Restart daily at
4, but only once 0 players are online - at the latest at 6", and optionally a
warning in Discord: "Valheim restarts in 10 minutes".

DECIDED WITH THE OPERATOR:
* At the latest moment the action happens anyway, with the warning before it -
  a daily restart stays guaranteed.
* The warning goes to the status channels AND the control channels.
* A player count that cannot be read counts as EMPTY. Whether it CAN be read is
  checked when the task or rule is saved, and the operator is told there if not
  (query_problem) - so "treated as empty" is never a surprise.

THE OPTIONS (one dict, stored with the task or the auto-action rule):
    wait_for_empty    bool  - act only while no player is online
    max_wait_minutes  int   - how long to wait at most (0-720, default 120)
    warn_minutes      int   - post a warning this long before acting (0-60)

They apply to restart and stop only; start disturbs nobody.

The decisions (acting_at, should_act, warning_due) are pure functions of the
options, the scheduled moment, the clock and the player counts, so they are
tested exactly; everything that touches Docker, the config or Discord sits
below them.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger("ddc.player_gate")

GATED_ACTIONS = ("restart", "stop")
DEFAULT_MAX_WAIT_MINUTES = 120
MAX_WAIT_MINUTES_LIMIT = 720      # half a day: a "daily" task must not wait into the next one
MAX_WARN_MINUTES = 60


# ---------------------------------------------------------------- options

def normalize_options(raw: Any, action: str) -> Tuple[Dict[str, Any], Optional[str]]:
    """(clean options, None) or ({}, reason) - what the panel, Discord and the rules save.

    Only settings that differ from "off" are kept, so a task without them stays
    exactly what it was.
    """
    if not raw:
        return {}, None
    if not isinstance(raw, dict):
        return {}, "The player options must be an object."
    wait = bool(raw.get("wait_for_empty"))
    try:
        warn = int(raw.get("warn_minutes") or 0)
        max_wait = int(raw.get("max_wait_minutes") if raw.get("max_wait_minutes") not in (None, "")
                       else DEFAULT_MAX_WAIT_MINUTES)
    except (TypeError, ValueError):
        return {}, "Wait and warning times must be whole minutes."
    if not wait and warn == 0:
        return {}, None
    if (action or "").lower() not in GATED_ACTIONS:
        return {}, "Waiting for an empty server and warnings only apply to restart and stop."
    if not 0 <= warn <= MAX_WARN_MINUTES:
        return {}, f"The warning must be 0-{MAX_WARN_MINUTES} minutes before."
    options: Dict[str, Any] = {}
    if wait:
        if not 1 <= max_wait <= MAX_WAIT_MINUTES_LIMIT:
            return {}, f"Waiting for an empty server can last 1-{MAX_WAIT_MINUTES_LIMIT} minutes."
        options["wait_for_empty"] = True
        options["max_wait_minutes"] = max_wait
    if warn:
        options["warn_minutes"] = warn
    return options, None


def _wait_seconds(options: Dict[str, Any]) -> int:
    if not (options or {}).get("wait_for_empty"):
        return 0
    return int(options.get("max_wait_minutes", DEFAULT_MAX_WAIT_MINUTES)) * 60


def window_seconds(options: Dict[str, Any]) -> int:
    """How long after its scheduled moment an occurrence may still be carried out."""
    return _wait_seconds(options)


# ---------------------------------------------------------------- decisions

def occupied(counts: Dict[str, Optional[int]]) -> bool:
    """Someone plays on at least one of the containers. Unknown counts as empty."""
    return any((count or 0) > 0 for count in counts.values())


def acting_at(options: Dict[str, Any], due_ts: float) -> float:
    """The latest moment the action happens: the scheduled one, or the end of the wait."""
    return due_ts + _wait_seconds(options)


def should_act(options: Dict[str, Any], due_ts: float, now: float,
               counts: Dict[str, Optional[int]]) -> bool:
    """Carry out the occurrence now?"""
    if now < due_ts:
        return False
    if not (options or {}).get("wait_for_empty"):
        return True
    return now >= acting_at(options, due_ts) or not occupied(counts)


def warning_due(options: Dict[str, Any], due_ts: float, now: float,
                counts: Dict[str, Optional[int]]) -> bool:
    """Is it time to warn the players (once per occurrence - the caller remembers)?

    Without waiting: warn_minutes before the scheduled moment. With waiting: the
    action comes either at once on an empty server - nobody to warn - or at the
    end of the wait with players on it, so the warning belongs before THAT
    moment, and only while someone plays.
    """
    warn = int((options or {}).get("warn_minutes") or 0)
    if warn <= 0:
        return False
    moment = acting_at(options, due_ts)
    if not (moment - warn * 60 <= now < moment):
        return False
    return occupied(counts) if options.get("wait_for_empty") else True


# ---------------------------------------------------------------- the host

def players_online(docker_name: str) -> Optional[int]:
    """Players on this container per the status cache: 0 if it is not running, None if unknown."""
    try:
        from services.status.status_cache_service import get_status_cache_service
        entry = get_status_cache_service().get(docker_name)
    except (ImportError, RuntimeError, AttributeError) as e:
        logger.debug(f"No status for {docker_name}: {e}")
        return None
    data = (entry or {}).get("data")
    if data is None or not getattr(data, "success", False):
        return None
    if not getattr(data, "is_running", False):
        return 0
    return getattr(data, "players_online", None)


def target_containers(name: str, is_group: bool) -> List[str]:
    """The containers an action on ``name`` touches."""
    if not is_group:
        return [name]
    try:
        from services.config.group_service import get_group_service
        return list(get_group_service().members_of(name).containers)
    except (ImportError, RuntimeError, AttributeError, OSError) as e:
        logger.warning(f"Group {name} could not be resolved for the player check: {e}")
        return []


def counts_for(names: Iterable[str]) -> Dict[str, Optional[int]]:
    return {name: players_online(name) for name in names}


def query_problem(docker_name: str) -> Optional[str]:
    """Why this container's player count cannot be read - None if it can.

    Asked when a task or rule with wait_for_empty is saved; the answer is shown
    to the operator, because the count then counts as "empty".
    """
    try:
        from app.utils.web_helpers import _get_advanced_setting
        if not _get_advanced_setting("DDC_ENABLE_OPENGSQ", True, bool):
            return "player counts are switched off in the advanced settings"
    except (ImportError, RuntimeError, AttributeError):
        pass
    try:
        from services.config.server_config_service import get_server_config_service
        server = get_server_config_service().get_server_by_docker_name(docker_name) or {}
    except (ImportError, RuntimeError, AttributeError, OSError):
        server = {}
    if not server.get("query_enabled"):
        return "the player count is not switched on for this container (Players column)"
    try:
        from services.infrastructure.game_query_support_service import get_game_query_support_service
        if get_game_query_support_service().is_supported(docker_name) is False:
            return "the game server does not answer the player query"
    except (ImportError, RuntimeError, AttributeError):
        pass
    if players_online(docker_name) is None:
        return "no player count has been read for it yet"
    return None


def query_problems(name: str, is_group: bool) -> List[str]:
    """``["Valheim: reason", ...]`` for the containers whose count cannot be read."""
    problems = []
    for container in target_containers(name, is_group):
        reason = query_problem(container)
        if reason:
            problems.append(f"{container}: {reason}")
    return problems


# ---------------------------------------------------------------- Discord

def describe(options: Dict[str, Any]) -> str:
    """The options in one line for Discord: "only when nobody plays (at most 120 min) · warning 10 min before"."""
    from cogs.translation_manager import _
    o = options or {}
    parts = []
    if o.get("wait_for_empty"):
        parts.append(_("only when nobody plays (at most {minutes} min)").format(
            minutes=o.get("max_wait_minutes", DEFAULT_MAX_WAIT_MINUTES)))
    if o.get("warn_minutes"):
        parts.append(_("warning {minutes} min before").format(minutes=o["warn_minutes"]))
    return " · ".join(parts)


def warning_text(display_name: str, action: str, minutes: int,
                 counts: Dict[str, Optional[int]]) -> str:
    from cogs.translation_manager import _
    players = sum((count or 0) for count in counts.values())
    if (action or "").lower() == "stop":
        text = _("⚠️ **{name}** will be stopped in {minutes} minutes.")
    else:
        text = _("⚠️ **{name}** will restart in {minutes} minutes.")
    text = text.format(name=display_name, minutes=minutes)
    if players:
        text += " " + _("Players online: {count}").format(count=players)
    return text


def warning_channel_ids(config: Dict[str, Any]) -> List[int]:
    """Status channels and control channels, each once (operator, 2026-09-28)."""
    from services.config.channel_roles import control_channel_ids, status_channel_ids
    seen: List[int] = []
    for channel_id in status_channel_ids(config) + control_channel_ids(config):
        if channel_id not in seen:
            seen.append(channel_id)
    return seen


async def post_warning(bot, text: str) -> int:
    """Send the warning to every status and control channel; how many took it."""
    if bot is None:
        logger.warning(f"No bot to post the warning: {text}")
        return 0
    try:
        from services.config.config_service import load_config
        config = load_config() or {}
    except (ImportError, RuntimeError, OSError) as e:
        logger.error(f"Warning not posted - configuration unreadable: {e}")
        return 0
    sent = 0
    for channel_id in warning_channel_ids(config):
        channel = bot.get_channel(channel_id)
        if channel is None:
            logger.warning(f"Warning channel {channel_id} is not reachable")
            continue
        try:
            await channel.send(text)
            sent += 1
        except Exception as e:  # discord errors of any kind: the next channel still gets it
            logger.warning(f"Warning could not be posted in {channel_id}: {e}")
    logger.info(f"Player warning posted in {sent} channel(s): {text}")
    return sent


# ---------------------------------------------------------------- auto-actions

def gated_verb(action_type: str) -> Optional[str]:
    """The task verb of an auto-action type the options apply to, else None."""
    verb = {"RESTART": "restart", "RECREATE": "restart", "STOP": "stop"}.get((action_type or "").upper())
    return verb


async def hold_until_empty(options: Dict[str, Any], containers: List[str], action: str,
                           label: str, bot, clock=time.time, sleep=asyncio.sleep,
                           poll_seconds: int = 60) -> None:
    """Return when an auto-action may act: at once, after the warning, or once nobody plays.

    An auto-action is triggered NOW, so its "warning N minutes before" means: warn
    now, act N minutes later. With wait_for_empty it acts the moment the servers
    are empty, or at the end of the wait - warned before that moment if players
    are still on. Clock and sleep are parameters so the timing is tested exactly.
    """
    options = options or {}
    if not options:
        return
    warn = int(options.get("warn_minutes") or 0)
    due = clock() + (0 if options.get("wait_for_empty") else warn * 60)
    warned = False
    while True:
        now = clock()
        counts = counts_for(containers)
        if not warned and warning_due(options, due, now, counts):
            warned = True
            minutes = max(1, round((acting_at(options, due) - now) / 60))
            await post_warning(bot, warning_text(label, action, minutes, counts))
        if should_act(options, due, now, counts):
            return
        await sleep(max(1, min(poll_seconds, acting_at(options, due) - now)))
