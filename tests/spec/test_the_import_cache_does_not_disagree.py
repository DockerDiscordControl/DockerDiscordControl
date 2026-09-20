# -*- coding: utf-8 -*-
"""
THE FINDING (review C40, section 35 F7): after uvloop fails to install, the
module's two ways of asking "is uvloop usable?" give two different answers.

`import_uvloop()` calls `safe_import('uvloop')`, which caches
`('uvloop' -> (module, True))`. If the `uvloop.install()` that follows raises,
`import_uvloop()` returns `success=False` for that call - but leaves the cache
saying True. A later `safe_import('uvloop')` reads the cache and reports the
library as available, although the install that makes it do anything failed.

Two answers to one question, from one module, depending on which door you use.

WHAT IS TRUE ABOUT THE REACH: nothing in the project calls `import_uvloop()`,
and the install failure needs a running event loop on top of that. A trap, not
a live bug - and the kind that only shows up under exactly the conditions where
one is trying to work out why async performance is poor.

The counter-checks keep both other paths: a uvloop that installs cleanly stays
True, and one that cannot be imported at all stays False.
"""

import sys
import types

import pytest

from utils import import_utils as iu


@pytest.fixture(autouse=True)
def empty_cache(monkeypatch):
    monkeypatch.setattr(iu, "_import_cache", {})
    yield


def _fake_uvloop(monkeypatch, install_error=None):
    module = types.ModuleType("uvloop")

    def _install():
        if install_error:
            raise install_error

    module.install = _install
    monkeypatch.setitem(sys.modules, "uvloop", module)
    return module


def test_a_failed_install_is_not_cached_as_available(monkeypatch):
    """THE FINDING: both doors must give the same answer."""
    _fake_uvloop(monkeypatch, install_error=RuntimeError("event loop running"))

    _module, from_import_uvloop = iu.import_uvloop()
    _module2, from_safe_import = iu.safe_import("uvloop")

    assert from_import_uvloop is False
    assert from_safe_import is False, "the cache still says uvloop is usable"


def test_asking_twice_gives_the_same_answer(monkeypatch):
    """The same question through the same door, twice."""
    _fake_uvloop(monkeypatch, install_error=RuntimeError("event loop running"))

    first = iu.import_uvloop()[1]
    second = iu.import_uvloop()[1]

    assert first == second is False


def test_a_clean_install_stays_available(monkeypatch):
    """COUNTER-CHECK: a uvloop that works is still reported as working."""
    _fake_uvloop(monkeypatch)

    assert iu.import_uvloop()[1] is True
    assert iu.safe_import("uvloop")[1] is True


def test_a_missing_library_stays_missing(monkeypatch):
    """COUNTER-CHECK: nothing changes for a library that is not there."""
    monkeypatch.setitem(sys.modules, "uvloop", None)

    assert iu.import_uvloop()[1] is False
