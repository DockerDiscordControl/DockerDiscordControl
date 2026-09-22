# -*- coding: utf-8 -*-
"""A cleanup that ran out of time is not a finished cleanup.

THE FINDING (review D4, pass 2, section 14 F1): `cleanup_channel` ends with

    result.success = result.permission_errors == 0

`timeout_errors` is raised at line 388 when `channel.purge(...)` exceeds
`purge_timeout`, and it is read nowhere. On that timeout the method falls
back to walking `history(limit=min(message_limit, 50))` - at most 50 messages,
however many matched - and then reports success, because no permission was
refused. Half the work, reported as done: the shape SPEC.md Z3 exists to
forbid.

The line above it carries the note of review A11, which fixed the same
`success` line when it said True unconditionally. Pass 1 repaired one layer
of this; the layer underneath stayed.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from services.discord.channel_cleanup_service import (
    ChannelCleanupRequest, ChannelCleanupService)


class _Message:
    def __init__(self, number, author):
        self.id = number
        self.author = author
        self.created_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        self.deleted = False

    async def delete(self):
        self.deleted = True


class _Channel:
    """A channel whose purge never returns in time."""

    def __init__(self, messages, purge_hangs=True):
        self.id = 777
        self._messages = messages
        self._purge_hangs = purge_hangs
        self.purged = []

    def history(self, limit=None):
        async def _iterator():
            for message in self._messages[:limit]:
                yield message
        return _iterator()

    async def purge(self, limit=None, check=None):
        if self._purge_hangs:
            await asyncio.sleep(3600)        # never inside the timeout
        hit = [m for m in self._messages[:limit] if check is None or check(m)]
        self.purged.extend(hit)
        return hit


BOT = object()


def _request(channel, **kwargs):
    return ChannelCleanupRequest(
        channel=channel, reason="test", message_limit=200, bot_only=False,
        custom_filter=lambda message: True, use_purge=True,
        purge_timeout=0.01, **kwargs)


@pytest.fixture
def service():
    return ChannelCleanupService(bot=None)


@pytest.mark.asyncio
async def test_a_purge_that_timed_out_is_not_a_success(service):
    """200 messages match; the fallback can reach at most 50 of them."""
    channel = _Channel([_Message(n, BOT) for n in range(200)])

    result = await service.cleanup_channel(_request(channel))

    assert result.success is False, (
        f"{result.messages_deleted} of {result.messages_found} deleted after a "
        f"timeout, and the cleanup reports success"
    )


@pytest.mark.asyncio
async def test_the_timeout_is_named(service):
    channel = _Channel([_Message(n, BOT) for n in range(200)])

    result = await service.cleanup_channel(_request(channel))

    assert result.error, "the cleanup fell short and says nothing about why"
    assert "time" in result.error.lower() or "timeout" in result.error.lower(), result.error


@pytest.mark.asyncio
async def test_a_purge_that_finished_is_still_a_success(service):
    """Counter-check: refusing to call anything a success would pass above."""
    channel = _Channel([_Message(n, BOT) for n in range(10)], purge_hangs=False)

    result = await service.cleanup_channel(_request(channel))

    assert result.success is True
    assert result.error is None


@pytest.mark.asyncio
async def test_a_refused_permission_still_fails(service):
    """Counter-check: the fix of review A11 must keep holding."""
    channel = _Channel([_Message(n, BOT) for n in range(3)], purge_hangs=False)
    result_holder = {}

    original = service._delete_messages

    async def _refuse(request, messages, result):
        result.permission_errors += len(messages)
        result_holder["called"] = True

    service._delete_messages = _refuse
    request = _request(channel)
    request.use_purge = False

    result = await service.cleanup_channel(request)
    service._delete_messages = original

    assert result_holder.get("called")
    assert result.success is False


@pytest.mark.asyncio
async def test_a_missing_permission_outranks_a_timeout(service):
    """Both can happen in one run: the fallback after a timeout deletes
    individually and can be refused while doing it. The operator then needs to
    hear about the permission - that is the one they can fix - not about the
    clock (found by mutation M3 of review D4).
    """
    import discord

    class _Refused(_Message):
        async def delete(self):
            raise discord.Forbidden(
                type("Response", (), {"status": 403, "reason": "Forbidden"})(),
                "Missing Permissions")

    # The fallback after a timeout deletes each message itself, so the refusal
    # has to come from the message - stubbing _delete_messages would never be
    # reached on this path.
    channel = _Channel([_Refused(n, BOT) for n in range(200)])

    result = await service.cleanup_channel(_request(channel))

    assert result.success is False
    assert "permission" in (result.error or "").lower(), (
        f"the timeout hid the missing permission: {result.error}"
    )
