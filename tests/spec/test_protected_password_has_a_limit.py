# -*- coding: utf-8 -*-
"""Guessing a container's protected password is limited to 3 tries per minute.

No ``@covers`` marker: an operator decision, taken on 2026-09-20.

THE FINDING (stage 4 review, stage B, section 07 F4): ``PasswordValidationModal``
compared the entered password with ``!=`` and had no limit at all - anyone
who may open the modal (everyone in a control channel, SPEC.md B1) could
resubmit it as often as they liked, and every wrong try was only written to
the action log. The operator decided the limit: **three attempts per minute**
per person.

The fourth try inside the window is refused WITHOUT looking at the password,
the window is rolling, and a correct password clears the record so the owner
is never locked out by their own earlier typos.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import cogs.enhanced_info_modal_simple as modals
from cogs.enhanced_info_modal_simple import PasswordValidationModal

INFO = {"protected_enabled": True, "protected_content": "the secret",
        "protected_password": "right-one"}


@pytest.fixture(autouse=True)
def fresh_attempts(monkeypatch):
    monkeypatch.setattr(modals, "_PASSWORD_ATTEMPTS", {}, raising=False)


def _modal(monkeypatch):
    modal = PasswordValidationModal.__new__(PasswordValidationModal)
    modal.cog = SimpleNamespace()
    modal.container_name = "vrising"
    modal.display_name = "V-Rising"
    modal.container_info = dict(INFO)
    modal.password_input = SimpleNamespace(value="")
    monkeypatch.setattr("services.infrastructure.action_logger.log_user_action",
                        MagicMock(), raising=False)
    return modal


def _try(modal, password):
    modal.password_input = SimpleNamespace(value=password)
    interaction = MagicMock()
    interaction.user = SimpleNamespace(id=4711, name="guesser", display_name="guesser",
                                       __str__=lambda self: "guesser")
    interaction.guild = SimpleNamespace(name="guild")
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    asyncio.run(modal.callback(interaction))
    texts = []
    for call in interaction.response.send_message.await_args_list:
        texts += [str(a) for a in call.args]
        embed = call.kwargs.get("embed")
        if embed is not None:                      # the success answer is an embed
            texts += [str(embed.title), str(embed.description)]
    return " ".join(texts)


def test_three_tries_are_allowed(monkeypatch):
    modal = _modal(monkeypatch)

    answers = [_try(modal, "wrong") for _ in range(3)]

    assert all("Incorrect password" in answer for answer in answers), answers


def test_the_fourth_try_within_a_minute_is_refused(monkeypatch):
    modal = _modal(monkeypatch)
    for _ in range(3):
        _try(modal, "wrong")

    answer = _try(modal, "right-one")      # even the CORRECT one must not get through

    assert "wait" in answer.lower(), f"the fourth try was answered with: {answer!r}"
    assert "the secret" not in answer


def test_after_the_minute_it_works_again(monkeypatch):
    modal = _modal(monkeypatch)
    for _ in range(3):
        _try(modal, "wrong")

    later = modals.time.time() + 2 * modals.PASSWORD_ATTEMPT_WINDOW_SECONDS
    monkeypatch.setattr(modals.time, "time", lambda: later)

    answer = _try(modal, "right-one")

    assert "the secret" in answer or "Protected Information" in answer, answer


def test_a_correct_password_frees_the_person_again(monkeypatch):
    """Otherwise the owner locks themselves out with two typos and one success."""
    modal = _modal(monkeypatch)
    _try(modal, "wrong")
    _try(modal, "wrong")

    assert "the secret" in _try(modal, "right-one"), "premise: the third try gets through"

    answer = _try(modal, "wrong")

    assert "Incorrect password" in answer, (
        f"after a correct password the count must start over; got: {answer!r}"
    )
