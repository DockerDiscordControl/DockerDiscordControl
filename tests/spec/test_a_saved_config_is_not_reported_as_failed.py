# -*- coding: utf-8 -*-
"""
THE FINDING (review C48, section 28 F4 and F2): the configuration is written to
disk and the operator is told the save failed.

F4 - `save_configuration` writes the main config, the container configs and the
     container info in steps 1 to 6. Step 7 then invalidates the caches, and
     `_handle_critical_changes` raises `ConfigCacheError` when that fails. The
     method's own handler catches `ConfigServiceError` and answers
     "Error saving configuration ..." - although everything had already been
     written. The same shape as reviews C26 and C45: the work is done, the
     report says it failed. A cache that could not be invalidated is worth
     saying, but it is not a failed save.

F2 - the file-save step returns a `SaveFilesResult`, and `save_configuration`
     returns that object straight to a caller annotated to receive a
     `ConfigurationSaveResult`. The route reads `save_result.error or
     save_result.message` on the failure path, so an empty `error` reaches
     `.message`, which `SaveFilesResult` does not have.

F3 IS REFUTED, with the reason: the reviewer noted that step 3 puts its reason
in `.message` while other paths use `.error`. The route reads
`save_result.error or save_result.message or 'Failed to save configuration.'`,
so the reason reaches the operator either way. No test can show a difference,
and nothing is changed for it.

The counter-checks keep a clean save clean and a real failure a failure.
"""

import pytest

from services.exceptions import ConfigCacheError
from services.web.configuration_save_service import (
    ConfigurationSaveRequest,
    ConfigurationSaveService,
    SaveFilesResult,
)


class _Changes:
    changed = True
    message = "timezone changed"
    # The save reads this too since 2026-09-23 (the panel's question about
    # existing tasks). None means there is nothing to ask about, which is what
    # this stand-in wants: these tests are about the cache, not the question.
    timezone_question = None


@pytest.fixture
def service(monkeypatch):
    instance = ConfigurationSaveService()
    monkeypatch.setattr(instance, "_initialize_dependencies",
                        lambda: type("R", (), {"success": True})())
    monkeypatch.setattr(instance, "_clean_form_data", lambda form: dict(form))
    monkeypatch.setattr(instance, "_process_configuration",
                        lambda cleaned: ({"servers": []}, True, "Configuration saved"))
    # Two arguments since 2026-09-22: the check is handed the configuration as it
    # was BEFORE the write, because reading it afterwards compared it with itself
    # (tests/spec/test_a_language_change_is_noticed_at_the_save.py).
    monkeypatch.setattr(instance, "_check_critical_changes",
                        lambda data, before=None: _Changes())
    monkeypatch.setattr(instance, "_save_server_order", lambda data: None)
    monkeypatch.setattr(instance, "_save_configuration_files",
                        lambda data, form, split: SaveFilesResult(success=True,
                                                                  config_files=["config.json"]))
    monkeypatch.setattr(instance, "_update_logging_settings", lambda: None)
    monkeypatch.setattr(instance, "_log_save_action", lambda: None)
    monkeypatch.setattr(instance, "_handle_critical_changes", lambda changes: None)
    return instance


def _request():
    return ConfigurationSaveRequest(form_data={"timezone": "Europe/Berlin"})


def test_a_cache_failure_after_the_write_is_not_a_failed_save(service, monkeypatch):
    """THE FINDING (F4): everything is on disk - say so."""
    def _explode(changes):
        raise ConfigCacheError("Failed to invalidate ConfigService cache",
                               error_code="CACHE_INVALIDATION_FAILED")

    monkeypatch.setattr(service, "_handle_critical_changes", _explode)

    result = service.save_configuration(_request())

    assert result.success is True, result.error


def test_the_cache_problem_is_still_mentioned(service, monkeypatch):
    """Not a failure, but not silence either."""
    def _explode(changes):
        raise ConfigCacheError("Failed to invalidate ConfigService cache",
                               error_code="CACHE_INVALIDATION_FAILED")

    monkeypatch.setattr(service, "_handle_critical_changes", _explode)

    result = service.save_configuration(_request())

    assert "cache" in (result.message or "").lower()


def test_a_file_save_failure_comes_back_as_the_documented_type(service, monkeypatch):
    """F2: the caller reads .message and .critical_settings_changed."""
    monkeypatch.setattr(service, "_save_configuration_files",
                        lambda data, form, split: SaveFilesResult(success=False, error=""))

    result = service.save_configuration(_request())

    assert result.success is False
    assert hasattr(result, "message")
    assert hasattr(result, "critical_settings_changed")


def test_a_clean_save_is_still_a_clean_save(service):
    """COUNTER-CHECK: nothing changes when nothing fails."""
    result = service.save_configuration(_request())

    assert result.success is True
    assert result.config_files == ["config.json"]
    assert result.critical_settings_changed is True


def test_a_real_config_error_is_still_a_failure(service, monkeypatch):
    """COUNTER-CHECK: a failure BEFORE the write is still a failure."""
    monkeypatch.setattr(service, "_process_configuration",
                        lambda cleaned: (None, False, "bad form data"))

    result = service.save_configuration(_request())

    assert result.success is False
