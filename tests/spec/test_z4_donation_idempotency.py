# -*- coding: utf-8 -*-
# @covers Z4
"""Z4 - money is never credited twice or without proof.

Every donation carries an idempotency key that does not depend on the time of
day. Submitting the same thing twice yields one entry, not two - but a real
second donation from the same donor does yield two.

Decided by the operator (2026-09-16): the browser generates a one-time token
when the donation dialog opens and sends it along; the Discord path uses
``interaction.id``. Deliberately NOT chosen was a time window over
(donor, amount): that would have swallowed a real quick second donation and
thereby lost real money.

The finding is a pass-through bug, not a missing mechanism:
``ProgressService.add_donation`` already supports idempotency and is tested for
it (``tests/unit/services/mech/test_progress_service.py:322``). But the key gets
lost between the entry point and the service - ``DonationRequest`` has no field
for it, and ``processors.py:36/52`` passes none on. Without a key,
``progress_service.py:1024`` builds one from
``mech_id|donor|amount|utcnow().isoformat()``; two identical submissions
microseconds apart therefore count as different.

What is checked is the observable behaviour at the entry point, not the wiring
in between - otherwise the test would check the implementation instead of the
guarantee.

COUNTER-CHECK (done 2026-09-16), in two unequal halves:

*The three service tests* failed before the fix with
``TypeError: ... unexpected keyword argument 'idempotency_key'``. That is an
honest but **weak** red: it proves that the mechanism was missing at the entry
point, not that the guarantee was violated. Since the fix they check booking
counts instead of signatures and can therefore also fail in future if the
pass-through regresses.

*The two contract tests for the UI* were at first red for the WRONG reason -
the bug was in them, not in the code: the excerpt ended at the nested
``resetSubmitButton()``, and the list of allowed spellings did not recognise
the actual guard ``(window.crypto && crypto.randomUUID)``. Working code was
almost rebuilt until a broken test turned green. After fixing the test, the
counter-check was genuinely redone: ``idempotency_key`` renamed in the frontend
and the guard defused -> exactly these two tests red (9 green); file
restored -> 11 green.

Found and fixed along the way: ``FakeMechService.add_donation`` in
``tests/test_unified_donation_service.py`` pinned the old signature and
swallowed the key in the async path.
"""

import uuid
from pathlib import Path

import pytest

from services.donation.unified_donation_service import (
    process_discord_donation,
    process_web_ui_donation,
)
from services.mech.progress_service import read_events


def _count_donations(marker: str) -> int:
    """Count booked donations whose donor name contains ``marker``.

    Counting absolutely would be unreliable: the event log is shared within a
    test run. The marker is unique per test.
    """
    return sum(
        1
        for e in read_events()
        if e.type == "DonationAdded" and marker in str(e.payload.get("donor") or "")
    )


@pytest.fixture
def marker() -> str:
    """Unique donor name so that tests do not count each other."""
    return f"z4-{uuid.uuid4().hex[:12]}"


async def test_discord_same_key_twice_books_once(marker):
    """The same submission processed twice: one booking.

    Corresponds to the case that exists in reality: the same
    ``interaction.id`` reaches the service twice (retry, duplicate delivery).
    """
    key = f"interaction-{uuid.uuid4().hex}"

    for _ in range(2):
        result = await process_discord_donation(
            discord_username=marker,
            amount=1.0,
            user_id="42",
            bot_instance=None,
            idempotency_key=key,
        )
        assert result.success is True

    assert _count_donations(marker) == 1, (
        "The same submission was booked more than once - the donation ledger "
        "shows more money than was received"
    )


async def test_discord_different_keys_book_twice(marker):
    """Two real donations of the same amount must both go through.

    The opposite direction of the guarantee, and the reason against a time
    window over (donor, amount): a real second donation must never be
    swallowed.
    """
    for _ in range(2):
        result = await process_discord_donation(
            discord_username=marker,
            amount=1.0,
            user_id="42",
            bot_instance=None,
            idempotency_key=f"interaction-{uuid.uuid4().hex}",
        )
        assert result.success is True

    assert _count_donations(marker) == 2, (
        "A real second donation was discarded as a duplicate - money was "
        "received that is not in the ledger"
    )


def test_web_same_token_twice_books_once(marker):
    """The token from the browser is passed all the way to the donation ledger."""
    token = f"web-{uuid.uuid4().hex}"

    for _ in range(2):
        result = process_web_ui_donation(marker, 1.0, idempotency_key=token)
        assert result.success is True

    assert _count_donations(marker) == 1, (
        "Resubmitting the same form booked a second time"
    )


# ---------------------------------------------------------------------------
# Contract with the call site
#
# The tests above check the service entry points. They would also be green if
# only the backend passed the key on and the browser never sent one - then Z4
# would still be broken in everyday use. Exactly this case ("the function is
# tested, the call site is not") was a finding from stage 0, which is why the
# UI source code is read here. The project already uses the same means in
# test_pkg_a_web.py and test_pkg_d2_mech_difficulty_contract.py.
# ---------------------------------------------------------------------------

CONFIG_HTML = (
    Path(__file__).resolve().parents[2] / "app" / "static" / "js" / "mech_panel.js"
)


def _function_body(source: str, name: str) -> str:
    """Cut out the body of a top-level function from ``mech_panel.js``.

    It was in an inline <script> in config.html until 2026-09-23.

    Top-level functions there are indented by 8 spaces, nested ones by 12. A
    naive cut at the next ``function `` therefore ends at the nested
    ``resetSubmitButton()`` - the first version of this test did exactly that
    and stayed red although the code was correct.
    """
    start = source.index(f"function {name}()")
    rest = source[start:]
    next_pos = rest.find("\n        function ")
    return rest if next_pos == -1 else rest[:next_pos]


def _token_assignment(body: str) -> str:
    """The one statement that creates the token (up to the semicolon)."""
    tail = body[body.index("window.__ddcDonationToken ="):]
    return tail[: tail.index(";") + 1]


def test_ui_sends_a_token_along():
    """``submitDonation()`` creates a token and sends it in the body.

    Note on robustness: this is a test over source text, not executed
    JavaScript. It fails if nobody sends a token any more - but also if someone
    renames the function. The project uses the same means in
    ``test_pkg_a_web.py`` and ``test_pkg_d2_mech_difficulty_contract.py``.
    """
    body = _function_body(CONFIG_HTML.read_text(encoding="utf-8"), "submitDonation")

    assert "idempotency_key" in body, (
        "The donation dialog sends no token - a retry after the timeout would "
        "book a second time"
    )
    assert "__ddcDonationToken" in body, "no token created"


def test_token_has_a_fallback_without_https():
    """``crypto.randomUUID`` is missing without a secure context.

    DDC deliberately runs as plain HTTP on the LAN (SPEC.md B3). There
    ``crypto.randomUUID`` is not available; without a fallback no token would
    be created at all and the submission would go out unprotected, unnoticed.

    What is checked is the assignment itself - guard AND fallback - instead of
    particular spellings: enumerating allowed spellings was the bug in the
    first version of this test.
    """
    body = _function_body(CONFIG_HTML.read_text(encoding="utf-8"), "submitDonation")
    assignment = _token_assignment(body)

    assert "randomUUID" in assignment, "no token generator in the assignment"
    assert ("window.crypto" in assignment or "typeof crypto" in assignment), (
        "randomUUID is used without an availability check - over HTTP the "
        "function is undefined"
    )
    assert ("?" in assignment and ":" in assignment) or "||" in assignment, (
        "no fallback when randomUUID is missing - then no token would be "
        "created at all and the donation would go out unprotected"
    )
