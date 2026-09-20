# -*- coding: utf-8 -*-
"""
THE FINDING (review C31, section 33 F1): one container's save failure throws
away everything the operator just edited.

`save_container_configs_from_web` runs two loops. The second one, which saves
the settings the operator actually changed, guards each container:

    except (AttributeError, KeyError, RuntimeError, TypeError,
            docker.errors.APIError, docker.errors.DockerException) as e:
        logger.error(...)
        results[container_name] = False

The FIRST loop - the one that marks containers inactive - calls the very same
`save_container_config()` with no guard at all. If it raises for one container,
the exception leaves the whole function: the rest of the inactive list is
skipped, the entire active loop below never runs, and none of them appear in
the returned `results`. The operator pressed Save, and the settings they edited
were never written, because an unrelated container that was being switched off
failed.

Two calls to the same method, twenty lines apart, one guarded and one not.

The counter-check (test_a_clean_save_still_reports_every_container) keeps the
ordinary path: every container still reports its own result.
"""

import pytest

from app.utils import container_info_web_handler as handler


class _SaveService:
    """Records every save and fails for the names it was told to fail for."""

    def __init__(self, failing=()):
        self.failing = set(failing)
        self.saved = []

    def save_container_config(self, container_name, container_config):
        if container_name in self.failing:
            raise RuntimeError(f"cannot write {container_name}")
        self.saved.append((container_name, dict(container_config)))
        return True


class _ServerService:
    def __init__(self, existing):
        self._existing = existing

    def get_all_servers(self):
        return [dict(entry) for entry in self._existing]

    def get_server_by_docker_name(self, name):
        for entry in self._existing:
            if entry.get("docker_name") == name:
                return dict(entry)
        return None


@pytest.fixture
def wired(monkeypatch):
    """Point the handler at our two test doubles."""
    def _wire(existing, failing=()):
        save_service = _SaveService(failing)
        import services.config.container_config_save_service as save_module
        import services.config.server_config_service as server_module
        monkeypatch.setattr(save_module, "get_container_config_save_service",
                            lambda: save_service)
        monkeypatch.setattr(server_module, "get_server_config_service",
                            lambda: _ServerService(existing))
        return save_service
    return _wire


EXISTING = [
    {"container_name": "old-one", "docker_name": "old-one"},
    {"container_name": "old-two", "docker_name": "old-two"},
    {"container_name": "web", "docker_name": "web"},
]

SUBMITTED = [{"docker_name": "web", "display_name": "Web Server",
              "allowed_actions": ["start", "stop"]}]


def test_the_edited_container_is_saved_even_if_another_one_fails(wired):
    """THE FINDING: the operator's edit must not be lost to an unrelated
    container being switched off."""
    save_service = wired(EXISTING, failing={"old-one"})

    handler.save_container_configs_from_web(SUBMITTED)

    assert "web" in [name for name, _ in save_service.saved]


def test_every_container_gets_a_verdict(wired):
    """The failure is recorded, not swallowed, and the rest still run."""
    wired(EXISTING, failing={"old-one"})

    results = handler.save_container_configs_from_web(SUBMITTED)

    assert results.get("old-one") is False
    assert results.get("old-two") is True
    assert results.get("web") is True


def test_a_clean_save_still_reports_every_container(wired):
    """COUNTER-CHECK: nothing changes when nothing fails."""
    save_service = wired(EXISTING)

    results = handler.save_container_configs_from_web(SUBMITTED)

    assert results == {"old-one": True, "old-two": True, "web": True}
    assert sorted(name for name, _ in save_service.saved) == ["old-one", "old-two", "web"]
