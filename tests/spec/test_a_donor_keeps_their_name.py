# -*- coding: utf-8 -*-
"""A donor called Müller is thanked as Müller, not as Mller.

THE FINDING (independent review of the donation path, 2026-09-23): the panel
strips a donor's name with

    DONOR_NAME_PATTERN = r'[^a-zA-Z0-9\\s\\-_\\.]'

before it reaches the ledger. Everything outside ASCII goes, silently:

    Müller    -> Mller
    José      -> Jos
    Ægir      -> gir
    日本語     -> ""  -> "Anonymous"

The mangled name goes into the DonationAdded payload, which is append-only and
replayed on every rebuild, and from there into the public Discord thank-you:
"**Mller** donated **$50.00** to DDC". Nobody is asked, nothing is logged, and
it cannot be corrected afterwards except by deleting the donation.

WHY IT IS SAFE TO KEEP THE LETTERS: the strip is not what makes the name safe
to show. The panel writes it with ``textContent``
(_donation_management_modal.html:224) and says so in its own comment - "never
by inline JS built from donor names" - and a Discord embed is markdown, not
HTML. What a name must NOT carry is a line break (it would break the embed
layout) and the invisible characters that can make text read backwards or
hide inside another name. Those are still removed, and this test pins that.

HOW THIS TEST CAN FAIL: it books names from ordinary European and Asian
alphabets and reads back what was stored. Anything missing is red.

COUNTER-CHECK (2026-09-23): red before - "Mller", "Jos", and "Anonymous" for
日本語. The last tests keep the dangerous characters out, so widening this is
not the same as dropping it.
"""

import pytest

from services.web.donation_service import DonationRequest, DonationService


def _clean(name):
    """What would be written to the ledger for this name."""
    request = DonationRequest(amount=10.0, donor_name=name)
    result = DonationService()._validate_and_sanitize_request(request)
    assert result.success, result.error
    return request.donor_name


@pytest.mark.parametrize("name", [
    "Müller",        # German, the operator's own language
    "José",          # Spanish
    "Ægir",          # Norwegian
    "Łukasz",        # Polish
    "Björn Åke",     # Swedish, with a space
    "Θεοδώρα",       # Greek
    "Ольга",         # Cyrillic
    "日本語",         # Japanese
])
def test_a_name_survives_being_booked(name):
    """THE FINDING: it was cut down to its ASCII letters, for ever."""
    assert _clean(name) == name, (
        f"{name!r} was stored as {_clean(name)!r} - the ledger is append-only, "
        "so that is what the public thank-you says for ever")


def test_a_plain_ascii_name_is_untouched():
    """Counter-check: the everyday case did work and still does."""
    assert _clean("Bob Smith-Jones_2") == "Bob Smith-Jones_2"


def test_a_line_break_is_still_removed():
    """It would break the embed layout, and it is never part of a name."""
    assert "\n" not in _clean("Bob\nDDC OFFICIAL")
    assert "\r" not in _clean("Bob\r\nsecond line")


@pytest.mark.parametrize("sneaky", [
    "‮Bob",      # right-to-left override: makes the rest read backwards
    "Bo​b",      # zero-width space: two different names look identical
    "Bob\u0000",      # NUL
    "Bob\u001b[31m",  # an escape sequence
])
def test_invisible_and_control_characters_are_still_removed(sneaky):
    """Counter-check: widening the filter must not let these through."""
    cleaned = _clean(sneaky)
    for ch in cleaned:
        assert ch.isprintable() or ch == " ", (
            f"{ch!r} survived in {cleaned!r}")
    assert "‮" not in cleaned and "​" not in cleaned


def test_html_in_a_name_cannot_grow_into_markup():
    """The panel writes with textContent, but the ledger keeps it for ever."""
    cleaned = _clean("<script>alert(1)</script>")

    assert "<" not in cleaned and ">" not in cleaned, cleaned


def test_a_name_of_only_separators_still_falls_back():
    """Counter-check: the Anonymous fallback is still reached."""
    assert _clean("   ") == "Anonymous"
    assert _clean("<<<>>>") == "Anonymous"


def test_the_length_cap_still_holds():
    """Counter-check: 50 characters, counted after the cleaning."""
    assert len(_clean("Ä" * 200)) == 50
