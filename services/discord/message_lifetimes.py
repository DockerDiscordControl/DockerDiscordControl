# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""How long a public message of DDC stays in its channel - kept over a restart.

THE OPERATOR (2026-09-30): every message but the status and control overviews
gets a lifetime. Their choice is LIFETIMES below.

WHY A FILE AND NOT discord's delete_after: that is a timer in the running
process. A restart of DDC lost it - and the channel cleanup at start, and
whenever an overview is posted anew, deleted every other bot message, the
reminder that was meant to stay included, while it spared the auto-action
notices for good. So each post is written down here with its expiry, sweep()
deletes what has expired (the status loop calls it every cycle), and the
cleanup spares alive_ids().

Posts that are meant to stay are not posted through here: the overviews, the
translated posts, the answers to a command (see
tests/spec/test_every_public_message_has_its_lifetime.py for the list).
"""

import json
import threading
import time
from typing import Any, Dict, Optional, Set

from utils.logging_utils import get_module_logger

logger = get_module_logger('message_lifetimes')

HOUR = 3600
# Seconds a kind of message stays; None: for good (spared by the cleanup too).
# player_warning has no fixed time - the caller gives it, from the action's moment.
LIFETIMES: Dict[str, Optional[int]] = {
    "auto_action": HOUR,               # "⚡ RESTART Icarus", watchdog notices
    "donation_thanks": 24 * HOUR,
    "update_notice": 7 * 24 * HOUR,
    "donation_reminder": None,
    "bulk_summary": 300,
    "player_warning": None,
    "player_join": 30 * 60,            # cogs/player_joins.py
}

_FILE = "message_lifetimes.json"
_lock = threading.Lock()


def _path():
    from utils.config_paths import get_config_dir
    return get_config_dir() / _FILE


def _read() -> Dict[str, Any]:
    """The records: "<channel_id>:<message_id>" -> expiry (None: for good)."""
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        # Unreadable: nothing is deleted on its say-so, and the cleanup spares
        # nothing it names - the messages fall back to the cleanup's own rules
        logger.error(f"{_FILE} could not be read ({e}) - message lifetimes are not applied")
        return {}


def _write(records: Dict[str, Any]) -> None:
    from utils.atomic_io import atomic_write_json
    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, records)
    except (OSError, TypeError, ValueError) as e:
        logger.error(f"{_FILE} could not be written ({e}) - a message may outlive its lifetime")


async def post(channel, kind: str, *args, lifetime: Optional[int] = None, **kwargs):
    """Send to ``channel`` and write down when the message goes.

    ``lifetime`` (seconds) overrides the kind's - the player warning knows its
    own. A kind with neither lives for good and is spared by the cleanup.
    """
    if kind not in LIFETIMES:
        raise ValueError(f"unknown message kind: {kind}")
    message = await channel.send(*args, **kwargs)
    channel_id, message_id = getattr(channel, 'id', None), getattr(message, 'id', None)
    if channel_id is None or message_id is None:
        logger.warning(f"A {kind} message was sent without an id to note - it has no lifetime")
        return message
    seconds = lifetime if lifetime is not None else LIFETIMES[kind]
    expires = time.time() + seconds if seconds is not None else None
    with _lock:
        records = _read()
        records[f"{channel_id}:{message_id}"] = expires
        _write(records)
    return message


def alive_ids(now: Optional[float] = None) -> Set[int]:
    """The message ids that may still stay - the cleanup spares them."""
    now = time.time() if now is None else now
    with _lock:
        records = _read()
    alive = set()
    for key, expires in records.items():
        try:
            message_id = int(key.split(":", 1)[1])
        except (IndexError, ValueError):
            continue
        if expires is None or expires > now:
            alive.add(message_id)
    return alive


async def sweep(bot) -> int:
    """Delete the messages whose time is up. Returns how many records it settled."""
    import discord

    now = time.time()
    with _lock:
        records = _read()
    due = [key for key, expires in records.items() if expires is not None and expires <= now]
    settled = []
    for key in due:
        try:
            channel_id, message_id = (int(part) for part in key.split(":", 1))
        except ValueError:
            settled.append(key)
            continue
        channel = bot.get_channel(channel_id) if bot else None
        if channel is None:
            # The channel is gone or not visible: nothing left to delete
            settled.append(key)
            continue
        try:
            await channel.get_partial_message(message_id).delete()
            settled.append(key)
        except discord.NotFound:
            settled.append(key)              # deleted by hand already
        except discord.Forbidden as e:
            logger.warning(f"Message {message_id} in channel {channel_id} could not be deleted "
                           f"at the end of its lifetime ({e}) - giving up on it")
            settled.append(key)
        except (discord.HTTPException, RuntimeError, OSError) as e:
            logger.info(f"Message {message_id} in channel {channel_id}: delete failed ({e}), "
                        f"tried again next cycle")
    if settled:
        with _lock:
            records = _read()
            for key in settled:
                records.pop(key, None)
            _write(records)
    return len(settled)
