# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Open private panels, written down so a restart can still take them away.

A private (ephemeral) message can only be deleted through the token of the
interaction behind it, and only for fifteen minutes. A view's timeout lives in
memory: a restart of DDC - a rebuild takes 60 to 90 seconds - lost every
timer, and the panels stayed until each person dismissed them by hand.

So each open private panel is written down with the token that can delete it
and how long that token lives (cogs/ddc_ui.py DDCView notes them), and the
start of DDC deletes every one whose token still works (operator, 2026-10-02).
A panel whose token has run out cannot be deleted by anyone but its viewer.

The file holds interaction tokens for at most fifteen minutes each, in the
config directory that only DDC can read.
"""

import json
import threading
import time
from typing import Any, Dict, Optional

from utils.logging_utils import get_module_logger

logger = get_module_logger('private_panels')

TOKEN_SECONDS = 15 * 60
_FILE = "private_panels.json"
_lock = threading.Lock()
API = "https://discord.com/api/v10"


def _path():
    from utils.config_paths import get_config_dir
    return get_config_dir() / _FILE


def _read() -> Dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        logger.warning(f"{_FILE} could not be read ({e}) - open private panels are not known")
        return {}


def _write(records: Dict[str, Any]) -> None:
    from utils.atomic_io import atomic_write_json
    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, records)
    except (OSError, TypeError, ValueError) as e:
        logger.warning(f"{_FILE} could not be written ({e}) - a restart may leave a private panel")


def remember(key: str, application_id: Any, token: Optional[str], target: Any,
             now: Optional[float] = None) -> None:
    """Note (or renew) the way to delete one open panel: its token lives 15 minutes from now."""
    if not key or not application_id or not token or not target:
        return
    now = time.time() if now is None else now
    with _lock:
        records = {k: v for k, v in _read().items()
                   if isinstance(v, dict) and v.get("until", 0) > now}
        records[key] = {"application_id": str(application_id), "token": token,
                        "target": str(target), "until": now + TOKEN_SECONDS}
        _write(records)


def forget(key: str) -> None:
    """The panel is gone; its way to delete it is no longer needed."""
    with _lock:
        records = _read()
        if key in records:
            records.pop(key)
            _write(records)


async def _delete(session, record: Dict[str, Any]) -> int:
    url = (f"{API}/webhooks/{record['application_id']}/{record['token']}"
           f"/messages/{record['target']}")
    async with session.delete(url) as answer:
        return answer.status


async def delete_left_behind(now: Optional[float] = None, delete=None) -> int:
    """At start: delete every noted panel whose token still works, then clear the notes.

    ``delete`` is (record) -> HTTP status; by default an aiohttp DELETE on the
    interaction webhook, which needs no bot authorisation. Returns how many
    were deleted.
    """
    now = time.time() if now is None else now
    with _lock:
        records = _read()
        _write({})
    open_ones = [r for r in records.values() if isinstance(r, dict) and r.get("until", 0) > now]
    if not open_ones:
        return 0
    deleted = 0
    session = None
    try:
        if delete is None:
            import aiohttp
            session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))

            async def delete(record):
                return await _delete(session, record)
        for record in open_ones:
            try:
                status = await delete(record)
            except Exception as e:  # noqa: BLE001 - one panel must not stop the others
                logger.info(f"A private panel left by the restart could not be deleted: {e}")
                continue
            if status in (200, 204):
                deleted += 1
            elif status != 404:          # 404: dismissed by hand already
                logger.info(f"A private panel left by the restart was not deleted (HTTP {status})")
    finally:
        if session is not None:
            await session.close()
    return deleted
