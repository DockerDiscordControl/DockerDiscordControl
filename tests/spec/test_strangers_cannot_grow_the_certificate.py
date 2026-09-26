# -*- coding: utf-8 -*-
"""Strangers cannot grow the self-signed certificate without end.

THE FINDING (audit 2026-09-26). The panel learns every address it is reached
on - from the SNI of a handshake, the Host of a plain request, the Host of a
served one - and a new name reissues the certificate. That is how a bookmark
on a new address works without a warning. But the learning happens before any
login, from anybody who can reach the port, and nothing capped it: a stream of
ClientHellos with SNI a1.x, a2.x, ... cost a key generation each, grew the
SAN list without end until handshakes broke, and changed the fingerprint every
time - undoing the operator's one trust step and teaching him to click
through warnings.

THE CONTRACT: the panel learns at most MAX_LEARNED_NAMES addresses. After
that a new name is not kept and causes no reissue; the names already learned
keep working. Real installations are reached on a handful of names (IP,
hostname, maybe a DNS name or two); an operator who needs more names them in
DDC_TLS_HOSTNAMES, which the cap does not touch.

HOW THIS TEST CAN FAIL: a name past the cap is kept, or the cap stops the
names below it from being learned.

COUNTER-CHECK (2026-09-26): red before the fix (no cap existed), and red again
with the constant in place but its check disabled: 200 names were kept.
"""

from app.web import tls


def test_names_past_the_cap_are_not_kept(tmp_path):
    for number in range(200):
        tls.remember_name(tmp_path, f"host{number}.example.test")

    learned = tls.known_names(tmp_path)

    assert len(learned) == tls.MAX_LEARNED_NAMES, len(learned)
    assert tls.remember_name(tmp_path, "one-more.example.test") is False


def test_the_names_below_the_cap_are_learned(tmp_path):
    """Counter-case: the cap must not stop the feature it bounds."""
    assert tls.remember_name(tmp_path, "192.168.1.249") is True
    assert tls.remember_name(tmp_path, "tower.local") is True
    assert set(tls.known_names(tmp_path)) == {"192.168.1.249", "tower.local"}


def test_the_cap_is_a_handful_not_a_hundred():
    """A number, pinned as a range rather than a mirror of the constant: large
    enough for real installations, small enough that the certificate and the
    reissues stay bounded."""
    assert 8 <= tls.MAX_LEARNED_NAMES <= 32
