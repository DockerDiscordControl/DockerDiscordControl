# -*- coding: utf-8 -*-
"""A changed language or timezone is noticed - and the caches are cleared.

THE FINDING: the save pipeline checks for "critical" settings (language,
timezone) by loading the configuration and comparing it with what is being
saved - but the step BEFORE it has already written the new configuration to
disk, and load_config reads that file. Old and new were therefore always the
same, changes.changed was always False, the cache invalidation never ran, and
the answer always said critical_settings_changed: false.

What the operator sees: they switch the panel to German, are told the
configuration was saved, and the panel stays English until DDC restarts.

The values are now read BEFORE the write and handed to the check.

COUNTER-CHECK (2026-09-22): red before - the comparison read the config it
had just written and reported no change.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from services.web.configuration_save_service import (ConfigurationSaveRequest,
                                                     ConfigurationSaveService)


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    (tmp_path / "containers").mkdir()
    return ConfigurationSaveService()


def _run(service, stored, processed):
    """One save, with the file behaving like the real one: the processing step
    writes, so a later read gives the NEW values."""
    state = {"config": dict(stored)}

    def _load():
        return dict(state["config"])

    def _process(form):
        state["config"] = dict(processed)   # this is what the real step does
        return dict(processed), True, "ok"

    with patch("services.config.config_service.load_config", side_effect=_load), \
         patch.object(service, "_initialize_dependencies",
                      return_value=SimpleNamespace(success=True)), \
         patch.object(service, "_process_configuration", side_effect=_process), \
         patch.object(service, "_save_server_order"), \
         patch.object(service, "_save_configuration_files",
                      return_value=SimpleNamespace(success=True, config_files=[], error=None)), \
         patch.object(service, "_handle_critical_changes") as handled:
        result = service.save_configuration(ConfigurationSaveRequest(form_data={}))
    return result, handled


def test_a_language_change_is_seen(service):
    result, handled = _run(service, {"language": "en"}, {"language": "de"})

    assert result.critical_settings_changed is True, "the language change went unnoticed"
    handled.assert_called_once()


def test_a_timezone_change_is_seen(service):
    result, _handled = _run(service, {"timezone": "Europe/Berlin"}, {"timezone": "UTC"})

    assert result.critical_settings_changed is True


def test_an_unchanged_language_is_not_reported(service):
    """Counter-check: every save must not claim a critical change."""
    result, handled = _run(service, {"language": "de"}, {"language": "de"})

    assert result.critical_settings_changed is False
    handled.assert_not_called()
