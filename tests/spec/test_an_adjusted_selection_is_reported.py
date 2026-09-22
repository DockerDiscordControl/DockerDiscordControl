# -*- coding: utf-8 -*-
"""
THE FINDING (review C43, section 33 F4): unchecking every action for a
container saves something else than what was submitted, and says so only in the
server's own log.

    allowed_actions = server.get('allowed_actions', [])
    if not allowed_actions:
        allowed_actions = ['status']
        logger.warning("... allowed_actions was empty, defaulting to ['status']")

The operator asked for no actions at all. The container is saved with
`status` allowed. The result handed back to the web UI is a plain True, exactly
like a save that did what it was told, so the panel shows success and the
operator finds their choice changed the next time they look.

Defaulting is defensible - a container with no actions at all cannot even be
shown. Doing it silently is not.

The counter-check (test_an_untouched_selection_is_not_flagged) keeps the note
to the case that earned it.
"""

import pytest

from app.utils import container_info_web_handler as handler


class _SaveService:
    def __init__(self):
        self.saved = []

    def save_container_config(self, container_name, container_config):
        self.saved.append((container_name, dict(container_config)))
        return True


class _ServerService:
    def get_all_servers(self):
        return []

    def get_server_by_docker_name(self, name):
        return None


@pytest.fixture
def save_service(monkeypatch):
    service = _SaveService()
    import services.config.container_config_save_service as save_module
    import services.config.server_config_service as server_module
    monkeypatch.setattr(save_module, "get_container_config_save_service", lambda: service)
    monkeypatch.setattr(server_module, "get_server_config_service", lambda: _ServerService())
    return service


def test_an_empty_selection_is_reported_as_adjusted(save_service):
    """THE FINDING: the answer must not read like an unchanged save."""
    results = handler.save_container_configs_from_web(
        [{"docker_name": "web", "allowed_actions": []}])

    assert results["web"] is not True, (
        "the panel cannot tell that the selection was changed")


def test_the_adjustment_names_what_happened(save_service):
    """The note has to say what was done, not just that something was."""
    results = handler.save_container_configs_from_web(
        [{"docker_name": "web", "allowed_actions": []}])

    assert "status" in str(results["web"]).lower()


def test_the_container_is_still_saved(save_service):
    """COUNTER-CHECK: reporting the adjustment is not refusing the save."""
    handler.save_container_configs_from_web(
        [{"docker_name": "web", "allowed_actions": []}])

    assert save_service.saved[0][1]["allowed_actions"] == ["status"]


def test_an_untouched_selection_is_not_flagged(save_service):
    """COUNTER-CHECK: a normal save still answers plain True."""
    results = handler.save_container_configs_from_web(
        [{"docker_name": "web", "allowed_actions": ["start", "stop"]}])

    assert results["web"] is True
