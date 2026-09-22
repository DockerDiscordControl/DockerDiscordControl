# -*- coding: utf-8 -*-
"""A failed write must not destroy a state file.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision. In substance this test belongs to Z7.

THE FINDING: ``services/infrastructure/update_notifier.py:63`` writes with
``open(self.status_file, 'w')`` + ``json.dump``. ``open(..., "w")`` truncates the
file the moment it is opened, ``json.dump`` writes as a stream - if the
serialization fails, half a record is left behind. Z7 says literally: "A
crash in the middle of writing leaves the old file intact."

RANK: DELIBERATELY LOW. Unlike the donation notification (commit 4aed2cb), there
is no unforgiving reader here. ``update_notifier.py:56-58`` catches the error
and returns defaults; the consequence is an already dismissed update
notification that appears again. **Nobody loses data.** The finding is here
because Z7 literally demands it, not because it hurts.

WHAT IS NOT CHECKED HERE AND THEREFORE NOT FIXED EITHER:
``services/mech/mech_reset_service.py:243`` has the same construction - and the
case is more annoying, because the same file already imports ``atomic_write_json``
at :25 and uses it twelve lines earlier at :202, with a written-out
justification ("Previously a plain open(..., 'w'), which truncates the file the
moment ..."). A deliberate switch in which a sister method was left over.

Still it stays untouched: ``reset_evolution_mode`` builds its payload
itself (``use_dynamic``, ``difficulty_multiplier``, ``datetime.now().isoformat()``),
there is no injection point from outside. A failure could only be forced by
mocking ``json.dump`` - then the test checks the mock, not the code. The
programme text says about this: stop where what you change cannot be measured.

A MISSTEP OF MY OWN, which belongs here because it explains the construction of
this test: the first version wanted to force the failure via a READ-ONLY
DIRECTORY - ``atomic_write_json`` needs write permission on the directory for
its temp file, ``open(..., "w")`` does not. Measured, this gave something other
than expected: the write SUCCEEDED, both tests went red at
``assert result is False`` (``assert True is False``). Write permission on the
directory is needed to create and rename entries, not to open an existing
file - so nothing failed at all, and there was nothing that would have had to
survive.

Worse: the planned fix would have achieved the opposite in exactly this case.
``atomic_write_json`` would have FAILED there where the direct writer
succeeds. I would have broken a working write and called it
"Z7 fix". The failure paths noted in advance ("red on the bytes",
"all green") did not contain this third outcome; the list was
incomplete.

HOW IT IS CHECKED NOW: via a non-serializable value in the dictionary that
the CALLER supplies - the only point at which a failure can honestly be forced
here without mocking anything. In BOTH worlds the same ``TypeError`` is raised
(the catch list at :66 does not know it), the difference lies solely in the
content of the file.

DELIMITATION: the good case is already covered
(``tests/unit/services/infrastructure/test_infrastructure_services.py:893``) and
is not repeated here.

COUNTER-CHECK (performed 2026-09-17) - two measurements, because two tests had
to be proven. TEST NAMES are given instead of line numbers: twice today I noted
a line number that the same write immediately made outdated.

*1. The finding test was red BEFORE the fix*, on the byte assertion - and the
measured content confirmed the description instead of refuting it::

    + b'{\\n  "last_notified_version": "2.0",\\n  "notifications_shown": '
    - b'{"last_notified_version": "1.0", "notifications_shown": ["1.0"]}'

Half a record, cut off exactly where the non-serializable value was - not
empty. This distinction was on the list of possible missteps BEFORE the run
(with the donation finding I was wrong exactly the other way round: there I
expected empty and measured half). ``pytest.raises(TypeError)`` held, so the
catch list at :66 really does not know the TypeError. After the fix:
2 green.

*2. The fixture guard was green from the start* and thus unproven. It is the
one that ensures the check happens in the throwaway directory at all - if it
were blind, the finding test could one day run past the real storage.
Mutation: ``UpdateNotifier`` ignores its ``config_dir``::

    -> 1 failed, 1 passed

It went red on ITS own path assertion:
``PosixPath('/app/config') == PosixPath('/tmp/pytest-of-ddc/...')``. The
finding test stayed green - an outcome for which I had deliberately made no
prediction, because it could not be derived.

*Four ways in which these reds would have been worthless* were fixed before
every run and never occurred: the test stays green (would be hollow); it fails
on an assertion other than the checked relation; error instead of failure;
collection or import error.

AFFECTED GROUPS, all measured green: spec 84, services/infrastructure 197,
extended 731, app_modules 73.
"""

import json

import pytest

from services.infrastructure.update_notifier import UpdateNotifier

OLD_STATUS = {"last_notified_version": "1.0", "notifications_shown": ["1.0"]}


@pytest.fixture
def notifier(tmp_path):
    """UpdateNotifier on a throwaway directory, with a populated state file.

    The constructor accepts ``config_dir``; this is what
    ``tests/unit/services/infrastructure/test_infrastructure_services.py:887``
    already does. No bending of ``__file__`` needed.
    """
    service = UpdateNotifier(config_dir=str(tmp_path))
    service.status_file.write_text(json.dumps(OLD_STATUS), encoding="utf-8")
    return service


def test_the_fixture_is_set_up_correctly(notifier, tmp_path):
    """Safeguard against a blunt tool.

    If the service points elsewhere or the state file is missing, the test
    below misses its target and would be green without proving anything. This
    very construction has already made a notifier worthless twice in this programme.
    """
    assert notifier.status_file.parent == tmp_path
    assert json.loads(notifier.status_file.read_text(encoding="utf-8")) == OLD_STATUS


def test_the_old_state_survives_a_failed_write(notifier):
    """THE FINDING: update_notifier.py:63 truncates before the serialization fails.

    The ``TypeError`` is raised in both worlds - ``save_update_status``
    does not catch it (:66). So what is checked is not the behaviour of the
    method, but what is on disk afterwards.
    """
    before = notifier.status_file.read_bytes()

    with pytest.raises(TypeError):
        notifier.save_update_status({
            "last_notified_version": "2.0",
            "notifications_shown": object(),   # json cannot serialize this
        })

    assert notifier.status_file.read_bytes() == before, (
        "The old notification state was damaged. open(..., 'w') truncates "
        "the file on opening, and json.dump writes as a stream - on "
        "failure half a record is left behind. Z7 requires that an "
        "abort in the middle of writing leaves the old file intact; "
        "utils/atomic_io.py serializes BEFORE opening for that purpose "
        "(utils/atomic_io.py:66-69)."
    )
