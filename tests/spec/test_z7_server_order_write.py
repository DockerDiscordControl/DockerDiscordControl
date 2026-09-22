# -*- coding: utf-8 -*-
# @covers Z7
"""Z7, place 5 of 5 - the server order.

``save_server_order`` (``services/docker_service/server_order.py:30``) writes
the file with a plain ``open(ORDER_FILE, 'w')`` (:45). An abort in the middle
leaves it empty.

Why this belongs here despite being "cosmetic": the loss is **invisible**.
``load_server_order`` (:54) catches ``json.JSONDecodeError`` and silently
returns ``[]`` for a broken file (:72-74). There is no error message and no
hint - the order the user arranged by hand in the panel is afterwards simply
the default order. "Unnoticed rarely strikes": the damage is small, but it
never announces itself.

So what is checked is not "the file has bytes", but the user-facing
statement: after the failed write, ``load_server_order()`` still returns the
old order.

The write is triggered in two places, both without any user action at the
moment of writing: ``cogs/docker_control.py:242`` (when building the server
list) and ``services/web/configuration_save_service.py:246`` (when saving the
configuration).

INTERCEPTION POINT: unlike ``_deactivate_container`` and ``reset_mech_state``,
this function does NOT read beforehand. So intercepting every ``open`` would
not be green for the wrong reason here. It is still limited to write
accesses - first, because the version after the fix writes via ``os.fdopen``,
second, because the second test in this file reads.

Existing tests (fully checked, ``tests/unit/extended/test_coverage_push_v3.py:138-225``,
7 of them): all redirect ``ORDER_FILE`` into ``tmp_path`` via ``monkeypatch``
and work with real files. One patches ``os.makedirs`` (:182), which comes
before the write and is untouched by the conversion. None intercepts the write
itself, none is blunted by ``atomic_write_json``. There is nothing to adjust -
unlike ``_deactivate_container``, where one test had to be updated too.

COUNTER-CHECK (performed 2026-09-16): before the fix red at exactly the
user-facing guarantee - ``load_server_order()`` returned ``[]`` instead of the
arranged order. Both guards held: ``hit`` fired (so the interception worked),
and ``result is False`` held. The log showed the whole chain: first
``Error saving server order``, then ``Error loading server order: Expecting
value: line 1 column 1`` - and after that nothing more.

EVIDENCE OF EFFECT by mutation: with an ``atomic_write_text`` whose
``except BaseException`` swallows the error instead of passing it on, this
test turns red - and at the right place::

    assert True is False
    # A failed write must not count as success

Restored, 3 green again, with no mutation residue. That is the sharper probe
than a mere revert: it proves that the test also catches a SUBTLER breakage -
a write error that is swallowed and reported as success.

Added 2026-09-17: this paragraph was missing, although the mutation was run on
2026-09-16 (documented in SPEC.md, Z7 section). The four other Z7 tests carry
their evidence with them, this one did not - whoever read it later would have
considered it unchecked. Found while counting for the stage 3 report.
"""

import json
import os

import pytest

from services.docker_service import server_order as so

ORIGINAL = ["nginx", "plex", "redis", "sonarr"]


class _OnlyWritingFails:
    """Allows reading, makes every write fail.

    Intercepts ``builtins.open`` and ``os.fdopen``, but only for write modes -
    today's version writes via ``open(..., 'w')``, an atomic one via
    ``mkstemp`` + ``os.fdopen``. The damage is REPRODUCED, not prevented: the
    file is opened (and thereby truncated) before the error comes. If you raise
    earlier, the old content survives and the test proves nothing - this
    mistake happened twice in the member count test.
    """

    def __init__(self, monkeypatch):
        self.hit = False
        real_open, real_fdopen = open, os.fdopen

        def _raises(*_a, **_k):
            raise OSError("no space left on device")

        def _open(file, mode="r", *a, **kw):
            if "w" in mode or "a" in mode:
                self.hit = True
                fh = real_open(file, mode, *a, **kw)  # truncates on open
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
def storage(tmp_path, monkeypatch):
    """Server order file with an arranged order in its own storage.

    ``ORDER_FILE`` is a module value; the seven existing tests in
    ``test_coverage_push_v3.py`` use the same redirection.
    """
    file = tmp_path / "server_order.json"
    file.write_text(json.dumps({"server_order": ORIGINAL}, indent=2), encoding="utf-8")
    monkeypatch.setattr(so, "ORDER_FILE", file)
    return file


def test_aborted_write_leaves_the_order_in_place(storage, monkeypatch):
    """If writing fails, loading still returns the old order."""
    failure = _OnlyWritingFails(monkeypatch)

    result = so.save_server_order(["completely", "different", "order"])

    assert failure.hit, (
        "The write error was not triggered at all - then this test checks "
        "nothing. Probably the write goes through a third path."
    )
    assert result is False, "A failed write must not count as success"

    assert so.load_server_order() == ORIGINAL, (
        "The server order arranged by the user is gone. It does not announce itself: "
        "load_server_order catches the JSON error and silently returns [], "
        "the display falls back to the default order without comment"
    )


def test_successful_save_replaces_the_order(storage):
    """The opposite direction: without an error the write is correct.

    Without this case one could tighten ``save_server_order`` to "never
    writes" and the test above would stay green.
    """
    new = ["redis", "nginx"]

    assert so.save_server_order(new) is True

    assert json.loads(storage.read_text(encoding="utf-8")) == {"server_order": new}
    assert so.load_server_order() == new


def test_no_temp_leftovers_after_success(storage):
    """An atomic implementation cleans up its temp file.

    Inventory before versus after - not "everything except the target file".
    The naive version of this check was red for the wrong reason in the member
    count test, because further regular files live in that storage.
    """
    before = {p.name for p in storage.parent.iterdir() if p.is_file()}

    so.save_server_order(["redis", "nginx"])

    after = {p.name for p in storage.parent.iterdir() if p.is_file()}
    assert sorted(after - before) == [], f"Temp leftovers remained: {sorted(after - before)}"
