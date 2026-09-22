# -*- coding: utf-8 -*-
# @covers Z7
"""Z7, place 2 of 5 - the container configuration.

``ContainerStatusService._deactivate_container`` (``container_status_service.py:118``)
rewrites a container's configuration file with a plain ``open(..., "w")``
(:153). An abort in the middle of it leaves the file not stale but
**truncated or empty** - and that is the user-maintained configuration of this
container: display name, allowed actions, order, info texts.

The method is called automatically when Docker permanently reports a container
as not present. So the user does not trigger it and does not see it - "rarely
strikes unnoticed" in its expensive form.

Why this place comes before the other three: of the remaining four it is the
only one that writes user configuration. ``member_count`` affects donation
goals, ``mech_reset_service`` and ``server_order`` are recoverable or cosmetic.

COUNTER-CHECK (done 2026-09-16):

Before the fix, ``test_aborted_write_...`` failed at its own assertion, and
again the result was worse than expected::

    assert ''

The configuration file was not half written but **completely empty** -
``open(..., "w")`` truncates it on opening, before a single byte is written.
Affected are the user-maintained settings of this container.

The guard ``failure.hit`` did not fire, and ``_deactivate_container``
correctly reported ``False``. The feared second finding - a failed write
reported as success (Z3) - therefore did NOT occur.

After the fix: ``tests/spec`` 33 green (only the two intentional Z10 failures
open), ``tests/unit/extended`` 731 green,
``tests/unit/services/infrastructure`` 197 green.

Updated along with it: ``tests/unit/extended/test_docker_infra_gaps.py`` drives
the same error path. It contained TWO bugs, and the second only came to light
through measuring:

1. The test only patched ``builtins.open``. Since the write goes through
   ``os.fdopen``, the patch hit nothing.
2. The obvious way out - make every ``open`` fail - does not check the write
   at all: ``_deactivate_container`` READS the file first, the read raised, the
   method returned ``False``, and the assertion was satisfied without anything
   ever being written.

Proven by mutation: with an ``atomic_write_text`` that swallows all errors,
the test up here turned red - the one there stayed green. A green test simply
does not prove that it bites. It now fails only on write accesses, on both
paths.
"""

import json
import os

import pytest

from services.infrastructure.container_status_service import ContainerStatusService


class _FailOnWrite:
    """Lets files be opened, but makes every write fail.

    Intercepts ``builtins.open`` AND ``os.fdopen`` - independent of the
    implementation: today's version writes via ``open(...)``, an atomic one via
    ``mkstemp`` + ``os.fdopen``. Whoever intercepts only ``builtins.open`` builds
    a test that silently checks nothing after the fix - exactly what happened to
    ``tests/unit/extended/test_docker_infra_gaps.py:1112``, which drives the
    same error path via ``patch("builtins.open", ...)``.
    """

    def __init__(self, monkeypatch):
        self.hit = False
        real_open = open
        real_fdopen = os.fdopen

        def _prepare(fh):
            self.hit = True

            def _raise(*_a, **_k):
                raise OSError("no space left on device")

            fh.write = _raise
            return fh

        def _open(file, mode="r", *a, **kw):
            fh = real_open(file, mode, *a, **kw)
            return _prepare(fh) if ("w" in mode or "a" in mode) else fh

        def _fdopen(fd, mode="r", *a, **kw):
            fh = real_fdopen(fd, mode, *a, **kw)
            return _prepare(fh) if ("w" in mode or "a" in mode) else fh

        monkeypatch.setattr("builtins.open", _open)
        monkeypatch.setattr(os, "fdopen", _fdopen)


ORIGINAL = {
    "name": "nginx",
    "docker_name": "nginx",
    "active": True,
    "allowed_actions": ["start", "stop", "restart"],
    "display_name": "Webserver",
}


@pytest.fixture
def status_service(tmp_path, monkeypatch):
    """Service with a real container file in its own storage."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    folder = tmp_path / "containers"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "nginx.json").write_text(json.dumps(ORIGINAL, indent=2), encoding="utf-8")
    return ContainerStatusService(), folder / "nginx.json"


def test_aborted_write_leaves_the_configuration_intact(status_service, monkeypatch):
    """If the write fails, the configuration is still complete."""
    service, file = status_service
    failure = _FailOnWrite(monkeypatch)

    result = service._deactivate_container("nginx")

    assert failure.hit, (
        "The write error was not triggered at all - this test then checks "
        "nothing. The implementation probably writes via a third path."
    )
    assert result is False, "A failed write must not count as success"

    content = file.read_text(encoding="utf-8")
    assert content.strip(), (
        "The container configuration is empty - an abort during automatic "
        "deactivation destroyed the user-maintained settings"
    )
    assert json.loads(content) == ORIGINAL, (
        f"The configuration was damaged: {content!r}"
    )


def test_successful_deactivation_sets_active_false(status_service):
    """The opposite direction: without an error the write is correct.

    Without this case one could tighten ``_deactivate_container`` to "never
    writes" and the test above would stay green.
    """
    service, file = status_service

    assert service._deactivate_container("nginx") is True

    after = json.loads(file.read_text(encoding="utf-8"))
    assert after["active"] is False
    assert after["allowed_actions"] == ORIGINAL["allowed_actions"], (
        "Other settings were lost during deactivation"
    )


def test_no_temp_leftovers_after_success(status_service):
    """An atomic implementation cleans up its temp file."""
    service, file = status_service
    service._deactivate_container("nginx")

    leftovers = [p.name for p in file.parent.iterdir() if p.name != file.name]
    assert leftovers == [], f"Temp leftovers remained: {leftovers}"
