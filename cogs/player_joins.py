# -*- coding: utf-8 -*-
"""Who joins a game server, announced where the operator asks for it (v3.1.0).

OFF UNLESS A CHANNEL ASKS: the channel tables in the panel carry a "Player
joins" box; with none ticked, nothing here runs a single query.

After each status cycle - in a task of its own, the cycle never waits - every
running game server with the player count switched on is compared with what
the last cycle saw:

* A game that NAMES its players completely (Valheim, Palworld) is compared by
  name: "👋 Anna joined Valheim (2/10)".
* A game that counts without naming (Icarus, Satisfactory), or names only a
  sample (Minecraft sends at most twelve, a different twelve each time), is
  compared by count: "👋 A player joined Icarus (3/8)". Comparing a sample by
  name would announce whoever happened to be drawn this time.
* The FIRST look after the bot starts only remembers: whoever was already on
  the server did not just join. A cycle whose query fails keeps what was seen
  before, so a hiccup does not re-announce everyone.

The notices go to channels that also hold DDC's status panels. Bot messages do
not count as activity there (docker_control.on_message), so they do not set
off the panels' recreation; they are deleted after JOIN_NOTICE_STAYS_FOR so
the panels do not drift up for good.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional

import discord

from utils.logging_utils import get_module_logger
from .translation_manager import _

logger = get_module_logger('player_joins')

JOIN_NOTICE_STAYS_FOR = 30 * 60


def join_channel_ids(config: Dict[str, Any]) -> List[int]:
    """The channels whose "Player joins" box is ticked."""
    ids = []
    for channel_id, channel in ((config or {}).get('channel_permissions') or {}).items():
        if isinstance(channel, dict) and channel.get('player_joins'):
            try:
                ids.append(int(channel_id))
            except (TypeError, ValueError):
                continue
    return ids


@dataclass(frozen=True)
class Seen:
    count: int
    # Only a COMPLETE list is kept; empty when the game names nobody or a sample
    names: FrozenSet[str] = field(default_factory=frozenset)
    complete: bool = False


def _seen(players, count: int) -> Seen:
    names = frozenset(name for name, _seconds in players.names) if players is not None else frozenset()
    # Nobody on the server is a complete list too - the first to join is then named
    complete = count == 0 or (players is not None and players.names_given and len(names) == count)
    return Seen(count=count, names=names if complete else frozenset(), complete=complete)


def joined(before: Seen, now: Seen) -> tuple:
    """(names that joined, how many joined without a name)."""
    if before.complete and now.complete:
        return sorted(now.names - before.names), 0
    return [], max(now.count - before.count, 0)


def notice(server: str, names: List[str], nameless: int,
           online: Optional[int], max_players: Optional[int]) -> Optional[str]:
    """The announcement, or None when nobody joined."""
    server = f"**{discord.utils.escape_markdown(server)}**"
    if names:
        text = _("👋 {names} joined {server}").format(
            names=", ".join(f"**{discord.utils.escape_markdown(n)}**" for n in names), server=server)
    elif nameless == 1:
        text = _("👋 A player joined {server}").format(server=server)
    elif nameless > 1:
        text = _("👋 {count} players joined {server}").format(count=nameless, server=server)
    else:
        return None
    if online is not None:
        text += f" ({online}/{max_players})" if max_players else f" ({online})"
    return text


class JoinWatcher:
    """What the last cycle saw per server, and the one check running at a time."""

    def __init__(self):
        self.known: Dict[str, Seen] = {}
        self.task: Optional[asyncio.Task] = None

    async def check(self, bot, channel_ids: List[int], counts: Dict[str, Optional[int]],
                    servers: Dict[str, Dict[str, Any]]) -> List[str]:
        """Compare, remember, announce. Returns the notices sent (for the log and the tests)."""
        from .info_extras import player_list
        for name in [n for n in self.known if n not in counts]:
            del self.known[name]  # stopped or gone: whoever comes back joins again
        notices = []
        for name, count in counts.items():
            server = servers.get(name) or {}
            # Switched off for this container in its info dialog (operator, 2026-10-04);
            # a container saved before the setting is announced
            if not server.get('query_enabled') or count is None or not server.get('announce_joins', True):
                continue
            before = self.known.get(name)
            players = None
            if count > 0 or (before is not None and before.count > 0):
                players = await player_list(server)
                if players is None or not players.success:
                    continue  # keep what was seen; ask again next cycle
                count = players.players_online if players.players_online is not None else count
            now = _seen(players, count)
            self.known[name] = now
            if before is None:
                continue  # first look: who is there did not just join
            text = notice(server.get('name') or name, *joined(before, now),
                          count, players.max_players if players is not None else None)
            if text:
                notices.append(text)
        for text in notices:
            await _post(bot, channel_ids, text)
        return notices


async def _post(bot, channel_ids: List[int], text: str) -> None:
    for channel_id in channel_ids:
        channel = bot.get_channel(channel_id) if bot is not None else None
        if channel is None:
            continue
        try:
            # Through the lifetime registry, not delete_after: a restart forgot that
            # timer, and a notice with a running lifetime does not move the overview
            # (operator, 2026-10-02)
            from services.discord.message_lifetimes import post
            await post(channel, "player_join", text, lifetime=JOIN_NOTICE_STAYS_FOR)
            logger.info(f"Join notice posted in {channel_id}: {text}")
        except (discord.errors.DiscordException, RuntimeError, OSError) as e:
            logger.warning(f"Join notice not posted in {channel_id}: {e}")


def schedule_join_check(cog, status_results: Dict[str, Any], servers: Dict[str, Dict[str, Any]]) -> None:
    """Start a join check after a status cycle - never two at once, never when no channel asks."""
    from services.docker_status.models import ContainerStatusResult
    watcher = cog.__dict__.setdefault('_join_watcher', JoinWatcher())
    channel_ids = join_channel_ids(getattr(cog, 'config', None) or {})
    if not channel_ids:
        watcher.known.clear()  # switched back on later, it starts with a first look again
        return
    if watcher.task is not None and not watcher.task.done():
        return
    counts = {name: result.players_online for name, result in status_results.items()
              if isinstance(result, ContainerStatusResult) and result.success and result.is_running}
    watcher.task = asyncio.ensure_future(
        watcher.check(getattr(cog, 'bot', None), channel_ids, counts, servers))
    watcher.task.add_done_callback(_log_failure)


def _log_failure(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.error(f"Join check failed: {task.exception()}")
