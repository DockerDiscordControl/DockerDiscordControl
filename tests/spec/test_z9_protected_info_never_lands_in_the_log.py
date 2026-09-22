# -*- coding: utf-8 -*-
# @covers Z9
"""Z9 in spirit - a protected password never lands in the log.

Z9 says the BOT TOKEN is never on disk in plain text, "not in logs". The same
sentence has to hold for the other secret the panel stores: the password of a
container's protected info, and the protected text behind it.

THE FINDING (stage 4 review, stage B, section 07 F3, re-checked 2026-09-20):
both info modals logged the WHOLE info dict at INFO on every open -
``logger.info(f"Loaded info for {container_name}: {self.container_info}")``
and its twin in ProtectedInfoModal - including ``protected_password`` and
``protected_content`` in plain text. The action log is downloadable from the
web panel, so opening the modal once put the password into a file the panel
hands out.
"""

import logging
from unittest.mock import MagicMock

import pytest

import cogs.enhanced_info_modal_simple as modals

PASSWORD = "hunter2-very-secret"
CONTENT = "rcon://secret-host:1234"
INFO = {"enabled": True, "custom_text": "public", "custom_ip": "", "custom_port": "",
        "show_ip": False, "protected_enabled": True, "protected_content": CONTENT,
        "protected_password": PASSWORD}


@pytest.fixture
def servers(monkeypatch):
    service = MagicMock()
    service.get_all_servers.return_value = [
        {"docker_name": "vrising", "name": "vrising", "info": dict(INFO)}]
    service.get_server_by_docker_name.return_value = {
        "docker_name": "vrising", "name": "vrising", "info": dict(INFO)}
    monkeypatch.setattr(modals, "get_server_config_service", lambda: service, raising=False)
    monkeypatch.setattr("services.config.server_config_service.get_server_config_service",
                        lambda: service)
    info_service = MagicMock()
    monkeypatch.setattr(
        "services.infrastructure.container_info_service.get_container_info_service",
        lambda: info_service)
    return service


@pytest.mark.asyncio
@pytest.mark.parametrize("modal_class", ["SimplifiedContainerInfoModal", "ProtectedInfoModal"])
async def test_opening_a_modal_logs_no_secret(servers, caplog, modal_class):
    """Async: py-cord's Modal needs a running event loop to be built."""
    with caplog.at_level(logging.DEBUG):
        getattr(modals, modal_class)(MagicMock(), "vrising", "V-Rising")

    logged = " ".join(record.getMessage() for record in caplog.records)
    assert PASSWORD not in logged, "the protected password was written to the log"
    assert CONTENT not in logged, "the protected content was written to the log"
