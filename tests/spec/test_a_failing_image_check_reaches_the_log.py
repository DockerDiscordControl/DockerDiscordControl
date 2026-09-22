# -*- coding: utf-8 -*-
"""An image check that fails says so in DDC's log.

THE FINDING: the image-update check hands its events to the automation
service outside any try, and the cog's task tracker catches only
DiscordException, RuntimeError, ValueError and OSError. Anything else - a
TypeError from a rule the engine could not read, an AttributeError from a
stubbed bot - ended as asyncio's "exception was never retrieved" warning on
stderr, with nothing in the DDC log and no hint which check failed.

Every failure of the check now reaches the log with the reason, and the
status loop is not touched either way.

COUNTER-CHECK (2026-09-22): red before - the TypeError left no line in
ddc.docker_control's log; the second test keeps a working check quiet.
"""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cogs.docker_control import DockerControlCog


@pytest.fixture
def cog(monkeypatch):
    cog = object.__new__(DockerControlCog)
    cog.bot = object()
    monkeypatch.setattr("services.docker_service.client_factory.build_docker_client",
                        lambda **kw: SimpleNamespace(
                            containers=SimpleNamespace(get=lambda name: SimpleNamespace(
                                attrs={"Config": {"Image": "nginx:latest"}})),
                            images=SimpleNamespace(get=lambda name: SimpleNamespace(
                                attrs={"RepoDigests": ["nginx@sha256:" + "a" * 64]})),
                            close=lambda: None))
    monkeypatch.setattr("services.automation.image_updates.remote_digest",
                        AsyncMock(return_value="sha256:" + "b" * 64))
    return cog


def test_a_broken_engine_is_reported(cog, monkeypatch, caplog):
    def explode():
        raise TypeError("rules could not be read")

    monkeypatch.setattr("services.automation.automation_service.get_automation_service", explode)

    with caplog.at_level(logging.DEBUG):
        asyncio.run(cog._check_image_updates(["web"], 42))

    said = " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)
    assert "rules could not be read" in said, said


def test_a_working_check_says_nothing_alarming(cog, monkeypatch, caplog):
    """Counter-check: catching everything must not make every run look broken."""
    engine = SimpleNamespace(process_container_events=AsyncMock(return_value=[]))
    monkeypatch.setattr("services.automation.automation_service.get_automation_service", lambda: engine)

    with caplog.at_level(logging.DEBUG):
        asyncio.run(cog._check_image_updates(["web"], 42))

    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert engine.process_container_events.await_count == 1
