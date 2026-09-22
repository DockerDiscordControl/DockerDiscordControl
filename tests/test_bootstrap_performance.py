# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

from __future__ import annotations

import gc
import logging
from types import SimpleNamespace

import pytest

from app.bootstrap.performance import apply_runtime_tweaks


class DummyLogger(logging.Logger):
    def __init__(self) -> None:
        super().__init__("ddc.test.performance")
        self.messages = []

    def debug(self, msg, *args, **kwargs):  # type: ignore[override]
        self.messages.append((msg, args))


@pytest.fixture
def logger() -> DummyLogger:
    return DummyLogger()


def test_apply_runtime_tweaks_adjusts_thresholds(monkeypatch, logger: DummyLogger) -> None:
    recorded = SimpleNamespace(set_args=None, froze=False)

    monkeypatch.setattr(gc, "get_threshold", lambda: (700, 10, 11))

    def fake_set_threshold(*args):
        recorded.set_args = args

    def fake_freeze():
        recorded.froze = True

    monkeypatch.setattr(gc, "set_threshold", fake_set_threshold)
    monkeypatch.setattr(gc, "freeze", fake_freeze, raising=False)

    apply_runtime_tweaks(logger)

    assert recorded.set_args == (700, 10, 10)
    assert recorded.froze is True
    # The MALLOC_TRIM_THRESHOLD_ assertion was dropped together with the code that set it:
    # it only checked that an environment variable was assigned, never that it had any effect.
    # glibc reads that variable when the allocator initialises - long before this runs - and the
    # production image is Alpine (musl), whose allocator ignores it entirely. To be precise about
    # the evidence: that is established behaviour of those allocators, not something measured in
    # this project, which is exactly why a test asserting the assignment proved nothing.


def test_apply_runtime_tweaks_respects_freeze_override(monkeypatch, logger: DummyLogger) -> None:
    monkeypatch.setenv("DDC_DISABLE_GC_FREEZE", "true")
    monkeypatch.setattr(gc, "get_threshold", lambda: (700, 10, 10))

    called = SimpleNamespace(froze=False)

    def fake_freeze():
        called.froze = True

    monkeypatch.setattr(gc, "freeze", fake_freeze, raising=False)

    apply_runtime_tweaks(logger)

    assert called.froze is False
