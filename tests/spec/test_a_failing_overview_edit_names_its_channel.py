# -*- coding: utf-8 -*-
"""An overview edit that fails names its channel and its error in the log.

THE FINDING (stage 4 review before v3.1.0, section 40 pass 4): an
exception escaping _update_overview_message (a KeyError from the embed
build, an OSError during a recovery) was caught by asyncio.gather
(return_exceptions=True) and only counted. The exception, its traceback
and its channel were never logged; a channel whose overview failed every
beat showed up only as "Errors: 1".

THE CONTRACT: each failed edit is logged with its channel, message, kind
and the exception.

HOW THIS TEST CAN FAIL: the failure is only counted again.

COUNTER-CHECK (2026-09-30): red before the change (only the counts).
"""

from datetime import datetime, timedelta, timezone

import pytest

import cogs.message_updates as message_updates


@pytest.mark.asyncio
async def test_the_failure_is_logged_with_its_channel(monkeypatch):
    from cogs.docker_control import DockerControlCog

    config = {"channel_permissions": {"111": {"enable_auto_refresh": True, "update_interval_minutes": 1}}}
    monkeypatch.setattr(message_updates, "load_config", lambda: config)
    import services.discord.status_overview_service as overview_service

    def unavailable():
        raise RuntimeError("no decision service")
    monkeypatch.setattr(overview_service, "get_status_overview_service", unavailable)

    errors = []
    real_error = message_updates.logger.error

    def record(message, *args, **kwargs):
        errors.append((str(message), kwargs.get("exc_info")))
        return real_error(message, *args, **kwargs)
    monkeypatch.setattr(message_updates.logger, "error", record)

    cog = DockerControlCog.__new__(DockerControlCog)
    cog.initial_messages_sent = True
    cog.channel_server_message_ids = {111: {"overview": 9001}}
    cog.last_message_update_time = {111: {"overview": datetime.now(timezone.utc) - timedelta(hours=2)}}
    cog.last_channel_activity = {}

    async def no_refresh():
        return None
    cog._refresh_cache_for_cycle = no_refresh

    async def broken(channel_id, message_id, kind):
        raise KeyError("boom")
    cog._update_overview_message = broken

    await cog.edit_due_messages()

    named = [(text, exc) for text, exc in errors if "111" in text and "boom" in text]
    assert named, f"the failed edit was not named: {errors}"
    assert isinstance(named[0][1], KeyError), "no traceback for the failure"
