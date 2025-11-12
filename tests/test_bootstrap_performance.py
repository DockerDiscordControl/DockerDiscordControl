from __future__ import annotations

import gc
import logging
import os
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
    monkeypatch.delenv("MALLOC_TRIM_THRESHOLD_", raising=False)

    def fake_set_threshold(*args):
        recorded.set_args = args

    def fake_freeze():
        recorded.froze = True

    monkeypatch.setattr(gc, "set_threshold", fake_set_threshold)
    monkeypatch.setattr(gc, "freeze", fake_freeze, raising=False)

    apply_runtime_tweaks(logger)

    assert recorded.set_args == (700, 10, 10)
    assert recorded.froze is True
    assert os.environ["MALLOC_TRIM_THRESHOLD_"] == "131072"
    monkeypatch.delenv("MALLOC_TRIM_THRESHOLD_", raising=False)


def test_apply_runtime_tweaks_respects_freeze_override(monkeypatch, logger: DummyLogger) -> None:
    monkeypatch.setenv("DDC_DISABLE_GC_FREEZE", "true")
    monkeypatch.setattr(gc, "get_threshold", lambda: (700, 10, 10))

    called = SimpleNamespace(froze=False)

    def fake_freeze():
        called.froze = True

    monkeypatch.setattr(gc, "freeze", fake_freeze, raising=False)

    apply_runtime_tweaks(logger)

    assert called.froze is False
