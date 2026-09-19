# -*- coding: utf-8 -*-
# @covers Z8
"""Z8 - a failed write of the game-query verdicts is visible in the log.

``game_query_support_service._atomic_update`` is the one writer of the
verdicts file: it carries the "supported" verdicts AND the ``testing`` flag
that drives the spinner of a manual re-test in the panel.

THE FINDING (stage 4 review pass 1, section 32 F1, re-checked 2026-09-19 -
the matter held, the reason did not): the reviewer blamed the bare
``except Exception: pass`` around ``support.set_testing(name, False)`` in
main_routes.py. That call cannot raise - ``_atomic_update`` below it already
swallows everything, and at DEBUG. So the spinner can indeed stay on
forever, but silently one level deeper than reported.
"""

import logging

import pytest

from services.infrastructure import game_query_support_service as support


@pytest.fixture
def failing_write(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    real_replace = support.Path.replace

    def explode(self, target):
        if str(self).endswith(".tmp"):
            raise OSError("no space left on device")
        return real_replace(self, target)

    monkeypatch.setattr(support.Path, "replace", explode)


def test_a_failed_verdict_write_is_an_error(failing_write, caplog):
    with caplog.at_level(logging.DEBUG):
        support.set_testing("vrising", True)

    assert [r for r in caplog.records if r.levelno >= logging.ERROR], (
        "the verdicts file could not be written - the panel's spinner keeps turning "
        "and nothing says why"
    )
