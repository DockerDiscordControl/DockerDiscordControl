# -*- coding: utf-8 -*-
"""Switching 2FA off offers it again, instead of the quiet notice for ever.

THE FINDING: the panel offers a 2FA setup dialog until the operator presses
"Later", which writes prompt_dismissed and leaves a small notice instead.
disable() clears the secret, the recovery codes and the enabled flag - but
not prompt_dismissed. So an operator who pressed "Later" once, then switched
2FA ON, then OFF again never sees the dialog again: the state says "they have
already declined", from a decision taken before they used it.

Turning it off is a fresh start: the dialog comes back.

COUNTER-CHECK (2026-09-22): red before - prompt_dismissed survived disable().
The second test keeps "Later" meaning what it says while 2FA is off.
"""

import time

import pytest

from services.web.two_factor_service import TwoFactorStore, secret_bytes, totp


@pytest.fixture
def store(tmp_path):
    return TwoFactorStore(tmp_path / "two_factor.json")


def _enable(store):
    store.begin_setup()
    now = time.time()
    return store.confirm_setup(totp(secret_bytes(store.pending_or_active_secret()), now - 30), now=now)


def test_the_dialog_comes_back_after_switching_off(store):
    store.dismiss_prompt()
    _enable(store)
    assert store.enabled

    assert store.disable(totp(secret_bytes(store.pending_or_active_secret()), time.time()))

    assert store.enabled is False
    assert store.prompt_dismissed() is False, (
        "the panel still treats a 'Later' from before 2FA was ever used as the answer")


def test_later_still_means_later_while_2fa_is_off(store):
    """Counter-check: the dialog must not come back on its own."""
    store.dismiss_prompt()
    assert store.prompt_dismissed() is True


def test_a_wrong_code_changes_nothing(store):
    """Counter-check, the other side: disable needs a valid code."""
    store.dismiss_prompt()
    _enable(store)

    assert store.disable("000000") is False
    assert store.enabled and store.prompt_dismissed() is True
