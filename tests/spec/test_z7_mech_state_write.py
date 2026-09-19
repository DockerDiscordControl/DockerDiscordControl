# -*- coding: utf-8 -*-
# @covers Z7
"""Z7, site 4 of 5 - the mech state.

``MechResetService.reset_mech_state`` (``services/mech/mech_reset_service.py:168``)
reads ``mech_state.json``, resets values and writes them back out with a
plain ``open(..., 'w')`` (:194). An abort in between leaves the file empty.

What gets lost is more than a counter: the method KEEPS the existing
structure and only sets values (:181-192). The file holds
``last_glvl_per_channel`` and ``mech_expanded_states`` - i.e. which Discord channel
had which mech level and which view was expanded there. A crash destroys this
mapping; afterwards nobody knows which channel belongs where.
So what is checked is not merely "file not empty", but that the mapping
is preserved.

INTERCEPTION POINT: the method reads the file FIRST (:175-177). An interceptor
that raises on every ``open`` therefore already fails on the read, the method
reports ``False``, and the write path is never reached - the test would be
green without proving anything. Exactly that happened to
``tests/unit/extended/test_docker_infra_gaps.py`` and cost two repair attempts
there. Here, therefore, only write accesses fail.

Existing tests (25 touch points, fully checked): all work with real files
in ``tmp_path`` and intercept nothing. None is made blunt by the switch to
``atomic_write_json`` - unlike ``_deactivate_container``, where one had to be
adjusted along with it. There is nothing to adjust here.

COUNTER-CHECK (performed 2026-09-16) - hit on the FIRST attempt::

    assert ''   # The mech state is empty

The guard ``hit`` did not fire (so the interception took effect), and
``result.success is False`` held (the exception is handled as expected).
Neither of the two failure possibilities named beforehand occurred.

That it worked right away this time is not luck: the two traps that cost two
attempts each in the previous Z7 passes had been named beforehand - the
interception point must lie BEHIND the truncation, and it may hit ONLY write
accesses, because the method reads first.

After the fix to ``atomic_write_json``: 3 green,
``tests/unit/services/mech`` unchanged 447 green.

PROOF OF EFFECT by mutation: with an ``atomic_write_text`` that swallows all
errors, this test turns red; restored, green again.

Checked and found harmless: ``mech_reset_service.py:302`` also accesses
``mech_state_file``, but only for reading (``'r'``) in
``get_current_status``. Not a Z7 case.
"""

import json
import os

import pytest

from services.mech.mech_reset_service import MechResetService

ORIGINAL = {
    "last_glvl_per_channel": {"111": 7, "222": 3},
    "mech_expanded_states": {"111": True},
    "last_update": "2026-01-01T00:00:00",
}


class _OnlyWritingFails:
    """Allows reading, makes every write fail.

    Intercepts ``builtins.open`` and ``os.fdopen``, but only for write modes -
    the current version writes via ``open(..., 'w')``, an atomic one via
    ``mkstemp`` + ``os.fdopen``. The damage is thereby REPRODUCED and not
    prevented: the file is opened (and thus truncated) before the error
    comes. If you raise earlier, the old content survives and the test proves
    nothing - this mistake happened twice in the member count test.
    """

    def __init__(self, monkeypatch):
        self.hit = False
        real_open, real_fdopen = open, os.fdopen

        def _raises(*_a, **_k):
            raise OSError("no space left on device")

        def _open(file, mode="r", *a, **kw):
            if "w" in mode or "a" in mode:
                self.hit = True
                fh = real_open(file, mode, *a, **kw)  # truncates
                fh.write = _raises
                return fh
            return real_open(file, mode, *a, **kw)

        def _fdopen(fd, mode="r", *a, **kw):
            fh = real_fdopen(fd, mode, *a, **kw)
            if "w" in mode or "a" in mode:
                self.hit = True
                fh.write = _raises
            return fh

        monkeypatch.setattr("builtins.open", _open)
        monkeypatch.setattr(os, "fdopen", _fdopen)


@pytest.fixture
def service_and_file(tmp_path):
    """Reset service with a populated mech state in its own storage."""
    file = tmp_path / "mech_state.json"
    file.write_text(json.dumps(ORIGINAL, indent=2), encoding="utf-8")
    return MechResetService(config_dir=str(tmp_path)), file


def test_aborted_write_leaves_the_state_intact(service_and_file, monkeypatch):
    """If the write fails, the channel mapping is still fully there."""
    service, file = service_and_file
    failure = _OnlyWritingFails(monkeypatch)

    result = service.reset_mech_state()

    assert failure.hit, (
        "The write error was not triggered at all - then this test checks "
        "nothing. Presumably something writes via a third path."
    )
    assert result.success is False, "A failed write must not count as success"

    content = file.read_text(encoding="utf-8")
    assert content.strip(), (
        "The mech state is empty - with it the mapping of which Discord "
        "channel had which level is lost"
    )
    state_after = json.loads(content)
    assert state_after["last_glvl_per_channel"] == ORIGINAL["last_glvl_per_channel"], (
        f"The channel mapping was damaged: {state_after!r}"
    )


def test_successful_reset_resets_and_keeps_the_channels(service_and_file):
    """The opposite direction: without errors the reset is done correctly.

    Without this case one could harden the method to "never writes" and
    the test above would stay green.
    """
    service, file = service_and_file

    result = service.reset_mech_state()

    assert result.success is True
    state_after = json.loads(file.read_text(encoding="utf-8"))
    assert state_after["last_glvl_per_channel"] == {"111": 1, "222": 1}, "Levels not reset"
    assert state_after["mech_expanded_states"] == {"111": False}, "View not collapsed"


def test_no_temp_leftovers_after_success(service_and_file):
    """An atomic implementation cleans up its temp file.

    Inventory before versus after - not "everything except the target file". The
    naive version of this check was red for the wrong reason in the member
    count test, because further regular files live in that storage.
    """
    service, file = service_and_file
    before = {p.name for p in file.parent.iterdir() if p.is_file()}

    service.reset_mech_state()

    after = {p.name for p in file.parent.iterdir() if p.is_file()}
    assert sorted(after - before) == [], f"Temp leftovers remained: {sorted(after - before)}"
