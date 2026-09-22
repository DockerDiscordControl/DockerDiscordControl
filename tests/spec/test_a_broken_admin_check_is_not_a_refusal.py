# -*- coding: utf-8 -*-
"""A permission that could not be read is not a permission that was refused.

THE FINDING: the stack button's admin check answers "You don't have
permission for this action." for everything - including the case where the
admin service itself could not be asked (AttributeError, ImportError,
RuntimeError). ConfirmRestartAllButton distinguishes the two deliberately
("Your permission could not be checked. Nothing was done."), because an admin
who reads the first sentence concludes they were removed from the admin list
and goes looking in the wrong place.

Closed either way - a permission that cannot be read is not granted. Only the
sentence changes.

COUNTER-CHECK (2026-09-22): red before - both cases said the same thing; the
"a stranger is refused" case keeps the wording that belongs to a real refusal.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import cogs.admin_overview as ao
from cogs.stack_restart import ConfirmRestartStackButton, offer_stacks

CHANNEL = 300


def _interaction():
    inter = MagicMock()
    inter.response.defer = AsyncMock()
    inter.followup.send = AsyncMock()
    inter.user.id = 1
    return inter


def _admin_service(monkeypatch, behaviour):
    monkeypatch.setattr(ao, "get_admin_service", lambda: SimpleNamespace(is_user_admin_async=behaviour))


def _said(inter):
    return str(inter.followup.send.await_args.args[0]).lower()


def test_a_service_that_cannot_be_asked_says_so(monkeypatch):
    async def broken(user_id):
        raise RuntimeError("admin store unreadable")

    _admin_service(monkeypatch, broken)
    inter = _interaction()
    asyncio.run(offer_stacks(SimpleNamespace(), CHANNEL, inter))

    said = _said(inter)
    assert "could not be checked" in said, said
    assert "don't have permission" not in said


def test_a_stranger_is_still_told_they_are_not_an_admin(monkeypatch):
    async def says_no(user_id):
        return False

    _admin_service(monkeypatch, says_no)
    inter = _interaction()
    asyncio.run(ConfirmRestartStackButton(SimpleNamespace(_bulk_operation_in_progress=False),
                                          CHANNEL, "blog").callback(inter))

    assert "permission" in _said(inter)
    assert "could not be checked" not in _said(inter)


def test_neither_case_acts(monkeypatch):
    """Counter-check: the distinction is in the wording, not in what happens."""
    async def broken(user_id):
        raise ImportError("no admin service")

    _admin_service(monkeypatch, broken)
    cog = SimpleNamespace(_bulk_operation_in_progress=False)
    asyncio.run(ConfirmRestartStackButton(cog, CHANNEL, "blog").callback(_interaction()))

    assert cog._bulk_operation_in_progress is False
