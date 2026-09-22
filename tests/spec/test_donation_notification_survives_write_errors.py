# -*- coding: utf-8 -*-
"""A failed write must not destroy the old donation notification.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision. In substance this test belongs to Z7.

THE FINDING (stage 2, point 2 - silent clearing away; found during the Z7
re-measurement, which I had previously carried out with the wrong pattern).

``services/web/donation_service.py:197`` writes the notification file like
this::

    with open(notification_file, "w") as f:
        json.dump(notification, f)

``open(..., "w")`` TRUNCATES the file the moment it is opened. Only then is
it written. In between lies a window in which the file exists and is empty or
half-written.

WHY THIS IS MORE THAN A CRASH RISK HERE: this file has a CONCURRENT READER.
``services/donation/notification_service.py:26`` reads it, and
``cogs/docker_control.py:5152`` polls it via ``@tasks.loop(seconds=30)``.
Both halves run in the SAME process - the web UI in a background thread, the
bot in the main thread.

And the reader is merciless: on ``json.JSONDecodeError`` it DELETES the file
(``notification_service.py:56-64``, comment "Try to delete corrupted file so
we don't get stuck") and returns ``None``. So if the poller hits the
truncation window, the donation announcement is gone - not delayed, but for
good. This is reported by a single ``logger.error`` line. No crash is needed
for it, only timing.

WHAT THIS TEST PROVES - and what not. It proves the property that Z7 states
LITERALLY: "A crash in the middle of writing leaves the old file intact."
That can be checked deterministically by making serialisation fail.
``atomic_write_json`` serialises BEFORE opening (``utils/atomic_io.py:66-69``),
so the target file stays untouched; by that point the direct writer has long
since truncated it.

It does NOT prove the 30-second race above. A test with thread interleaving
would be unreliable, and a flaky test is worse than none - it gets ignored,
and an ignored test is as worthless as a green one. The race is stated here
as the REASON why the property matters in practice, not as an assertion about
what was measured.

EXISTING COVERAGE, so that no twin arises here:
``tests/unit/extended/test_coverage_push_v3.py:77-122`` covers five branches
of the READER (no file, read+delete, invalid JSON, delete error, singleton).
For the WRITER there is no test of how it writes;
``tests/unit/services/donation/test_donation_web_services.py:184-186`` checks
THAT it writes, not HOW.

TWO-PART, and the second part is the lesson from a mistake made today:
part 1 checks the writer, part 2 proves that ``process_donation`` reaches it
at all. Without part 2, part 1 would be a statement about a function nobody
calls - exactly the pitfall from stage 3, check 3, where a detector in this
programme already became worthless.

COUNTER-CHECK (performed 2026-09-17) - three measurements, because three tests
had to be proven. TEST NAMES are given instead of line numbers: twice today I
noted a line number that the same write immediately made stale.

*1. The finding test was red BEFORE the fix* - on the byte assertion, not on
the existence check. And the measurement was WORSE than I expected: I had
assumed an empty file; in fact there was a HALF record that began validly::

    + b'{"type": "donation", "donor": "Bob", "amount": '
    - b'{"type": "donation", "donor": "Previous", "amount": 1.0, "timestamp": ...}'

``json.dump`` writes in a streaming fashion (the traceback shows ``for chunk
in iterable`` in json/__init__.py:181), so the first chunks of the new
notification were already on disk when serialisation failed with
``TypeError: Object of type object is not JSON serializable``. What remains is
not an empty nothing but something that starts like a real notification and
breaks off in the middle of a key. The poller reads it, ``json.load`` raises,
and the reader DELETES the file - old AND new notification are gone. After
the fix: 3 green.

*2. The wiring test was green from the start* and therefore unproven.
Mutation: ``process_donation`` skips step 3 (``discord_success = False``)::

    -> 1 failed, 2 passed

Exactly it turned red, on its own ``is_file()`` assertion; the other two
stayed green because they call the writer directly. So the mutation hit the
connection and nothing else.

*3. The fixture guard was likewise green throughout.* Mutation: the writer
stores the file under a different name::

    -> 2 failed, 1 passed

It turned red on its own ``is_file()`` assertion, and the log names the
reason: "Discord notification created: .../MUTATION_other_file.json". The
wiring test failed as an announced side effect (it looks for the same file),
the atomicity test stayed green - a failed write to a DIFFERENT name leaves
the old notification untouched, and that is exactly what it asserts.

*Four ways in which these reds would have been worthless* were fixed before
every run and never occurred: the respective test stays green (would be
hollow); it fails on a different assertion than the relationship under test;
the mutation turns more red than claimed; collection or import errors.

AFFECTED GROUPS, all measured green: services/donation 52, services/web 358,
spec 82, test_donation_system_functional 3, test_unified_donation_service 4,
integration 5, audit_2026_09 564, blueprints 276, extended 731, services/mech 433.
"""

import json
from unittest.mock import patch

import pytest

from services.web.donation_service import DonationRequest, DonationService

OLD_NOTIFICATION = {"type": "donation", "donor": "Previous", "amount": 1.0,
                    "timestamp": "2026-01-01T00:00:00"}


@pytest.fixture
def env(tmp_path):
    """DonationService whose notification directory points at a throwaway directory.

    ``NOTIFICATION_DIR`` is a class attribute with the value "/app/config"
    (donation_service.py:53). It is overridden on the INSTANCE - just as
    ``tests/unit/services/donation/test_donation_web_services.py:167`` already
    does; a second fixture next to it would be exactly the duplication this
    programme looks for.
    """
    service = DonationService()
    service.NOTIFICATION_DIR = str(tmp_path)
    return type("Environment", (), {
        "service": service,
        "directory": tmp_path,
        "file": tmp_path / "donation_notification.json",
    })


def test_the_fixture_writes_into_the_throwaway_directory(env):
    """Safeguard against a blunt tool.

    If the notification file does not end up where the test looks for it, the
    tests below would be green without proving anything - and in the worst
    case they would have written into the real store. This kind of setup has
    already made a detector worthless twice in this programme.
    """
    request = DonationRequest(amount=5.5, donor_name="Alice", publish_to_discord=True)

    assert env.service._handle_discord_notification(request) is True
    assert env.file.is_file(), (
        f"No notification file in {env.directory} - NOTIFICATION_DIR points elsewhere."
    )
    content = json.loads(env.file.read_text(encoding="utf-8"))
    assert content["donor"] == "Alice"
    assert content["amount"] == 5.5


def test_a_failed_write_does_not_destroy_the_old_notification(env):
    """THE FINDING: the previous notification must survive a failed write.

    The failure is forced via a non-serialisable amount - deterministic, no
    threads, no timing dependency. ``json.dump`` then raises ``TypeError``,
    which ``donation_service.py:208-210`` catches.

    The difference that matters: the direct writer has already truncated the
    file on opening, before serialisation even fails. ``atomic_write_json``
    serialises first and does not touch the target file at all
    (utils/atomic_io.py:66-69).
    """
    env.file.write_text(json.dumps(OLD_NOTIFICATION), encoding="utf-8")
    before = env.file.read_bytes()

    # A value json cannot serialise.
    request = DonationRequest(amount=object(), donor_name="Bob", publish_to_discord=True)

    assert env.service._handle_discord_notification(request) is False, (
        "A non-serialisable amount must be reported as a failure."
    )

    assert env.file.is_file(), (
        "The old notification has DISAPPEARED. open(..., 'w') truncates the file on "
        "opening - the failure afterwards can no longer save it."
    )
    assert env.file.read_bytes() == before, (
        "The old notification was damaged. Z7 requires that an abort in the middle "
        "of writing leaves the old file intact. Here that counts double: "
        "the bot polls this file every 30 seconds, and on invalid JSON it "
        "DELETES it (notification_service.py:56-64) - the donation announcement "
        "would be gone for good, reported only by a logger.error line."
    )


def test_process_donation_really_calls_the_writer(env):
    """Wiring: the public path must reach the writer above.

    Otherwise the test above would be a statement about a function nobody
    calls. It is checked via ``process_donation``; only the mech step is
    replaced, not the whole unified_donation_service scaffolding - its mocks
    live in a different test group and would have to be rebuilt here.

    ``_build_donation_response`` copes with ``mech_state=None``: every field
    falls back to a default value (donation_service.py:230-236).
    """
    request = DonationRequest(amount=7.25, donor_name="Carol", publish_to_discord=True)

    with patch.object(env.service, "_process_mech_donation",
                      return_value={"success": True, "mech_state": None}), \
         patch("services.infrastructure.action_logger.log_user_action"):
        result = env.service.process_donation(request)

    assert result.success is True
    assert env.file.is_file(), (
        "process_donation left no notification file - step 3 "
        "(donation_service.py:85) no longer reaches the writer."
    )
    content = json.loads(env.file.read_text(encoding="utf-8"))
    assert content["donor"] == "Carol"
    assert content["amount"] == 7.25
