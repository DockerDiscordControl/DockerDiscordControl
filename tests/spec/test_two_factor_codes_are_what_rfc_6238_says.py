# -*- coding: utf-8 -*-
"""The second factor: TOTP by RFC 6238, recovery codes, and a file of its own (v3.0 step 9).

Operator decision 2026-09-22: 2FA is offered and strongly recommended, never
forced, and only over TLS. This file checks the core the web flow stands on:

* The codes are RFC 6238 TOTP (SHA-1, 30 s, six digits), checked against the
  RFC's own test vectors - not against a second copy of the formula, which
  would only prove the code agrees with itself.
* A code is accepted in the window the phone may drift into (one step either
  side) and never twice: a code read off the network or a shoulder is spent.
* Recovery codes are shown once, stored only as hashes, and each works once.
* Everything lives in ``two_factor.json`` in the config directory, mode 0600,
  a file v2.4.1 never reads or writes (V3 §5.5): a downgrade cannot drop the
  secret on its first save, so an upgrade back never finds 2FA silently off.

COUNTER-CHECK (2026-09-22): written before the service existed; then the
replay guard was disabled and the "never twice" test went red; restored, green.
"""

import os

import pytest

# RFC 6238, Appendix B: the SHA-1 seed is the ASCII string "12345678901234567890".
RFC_SECRET = b"12345678901234567890"
RFC_VECTORS = [  # (unix time, 8-digit TOTP from the RFC)
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
]


@pytest.mark.parametrize("unix_time,expected", RFC_VECTORS)
def test_totp_matches_the_rfc_vectors(unix_time, expected):
    from services.web.two_factor_service import totp

    assert totp(RFC_SECRET, unix_time, digits=8) == expected
    assert totp(RFC_SECRET, unix_time) == expected[-6:]


@pytest.fixture
def store(tmp_path):
    from services.web.two_factor_service import TwoFactorStore

    return TwoFactorStore(tmp_path / "two_factor.json")


def _code(store, when):
    from services.web.two_factor_service import totp, secret_bytes

    return totp(secret_bytes(store.pending_or_active_secret()), when)


def test_it_is_off_until_a_code_confirms_the_secret(store):
    assert not store.enabled
    store.begin_setup()
    assert not store.enabled, "a secret nobody has scanned must not lock the panel"
    assert not store.confirm_setup("000000", now=1_000_000)
    codes = store.confirm_setup(_code(store, 1_000_000), now=1_000_000)
    assert store.enabled and len(codes) == 10 and len(set(codes)) == 10


def test_a_code_is_accepted_in_the_drift_window_and_never_twice(store):
    store.begin_setup()
    store.confirm_setup(_code(store, 1_000_000), now=1_000_000)
    later = 1_000_000 + 300
    assert store.verify(_code(store, later - 30), now=later), "one step of drift must pass"
    assert not store.verify(_code(store, later - 30), now=later), "a spent code must not pass again"
    assert not store.verify(_code(store, later - 90), now=later), "three steps old is too old"


def test_a_recovery_code_works_once_and_is_never_stored_in_clear(store, tmp_path):
    store.begin_setup()
    codes = store.confirm_setup(_code(store, 1_000_000), now=1_000_000)
    raw = (tmp_path / "two_factor.json").read_text()
    assert not any(code in raw for code in codes)
    assert store.verify(codes[0], now=1_000_100)
    assert not store.verify(codes[0], now=1_000_200)
    assert store.remaining_recovery_codes() == 9


def test_the_file_is_private_and_survives_a_reload(store, tmp_path):
    from services.web.two_factor_service import TwoFactorStore

    store.begin_setup()
    store.confirm_setup(_code(store, 1_000_000), now=1_000_000)
    path = tmp_path / "two_factor.json"
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"
    again = TwoFactorStore(path)
    assert again.enabled and again.verify(_code(again, 1_000_600), now=1_000_600)


def test_disabling_needs_a_valid_code(store):
    store.begin_setup()
    store.confirm_setup(_code(store, 1_000_000), now=1_000_000)
    assert not store.disable("123456", now=1_000_300)
    assert store.enabled
    assert store.disable(_code(store, 1_000_300), now=1_000_300)
    assert not store.enabled


def test_an_unreadable_file_is_not_a_disabled_second_factor(tmp_path):
    """A damaged file must not open the panel without the second factor."""
    from services.web.two_factor_service import TwoFactorStore, TwoFactorUnreadable

    path = tmp_path / "two_factor.json"
    path.write_text("{not json")
    with pytest.raises(TwoFactorUnreadable):
        TwoFactorStore(path).enabled

