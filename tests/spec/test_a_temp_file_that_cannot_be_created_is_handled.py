# -*- coding: utf-8 -*-
"""A save that cannot even create its temp file fails cleanly.

No ``@covers`` marker: two findings, not a guarantee.

THE FINDING (stage 4 review, stage B, section 10 F4 and section 11 F2 - the
same two lines in two sibling services, re-checked 2026-09-20): both
``_save_config_file`` (auto_action_config_service) and ``_save_state``
(auto_action_state_service) do

    fd, temp_path = tempfile.mkstemp(...)   # inside the try

and their except handler then asks ``os.path.exists(temp_path)``. If
``mkstemp`` itself fails - an unwritable config directory, no inodes left,
too many open files - ``temp_path`` was never bound, so the handler raises
UnboundLocalError while cleaning up. The original OSError is replaced by a
confusing one, and ``_save_config_file``, which promises a bool, raises
instead: ``delete_rule()`` has no try of its own around it.
"""

import tempfile
from unittest.mock import patch

import pytest


@pytest.fixture
def config_service(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    from services.automation.auto_action_config_service import AutoActionConfigService
    return AutoActionConfigService()


@pytest.fixture
def state_service(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    from services.automation.auto_action_state_service import AutoActionStateService
    return AutoActionStateService()


def test_a_working_save_reports_success(config_service):
    """Premise: the normal path still saves and says so."""
    assert config_service._save_config_file({"auto_actions": []}) is True


def test_the_config_save_survives_a_failing_mkstemp(config_service):
    with patch.object(tempfile, "mkstemp", side_effect=OSError("no space left on device")):
        result = config_service._save_config_file({"auto_actions": []})

    assert result is False, "a save that could not happen must say so, not raise"


def test_the_state_save_survives_a_failing_mkstemp(state_service):
    with patch.object(tempfile, "mkstemp", side_effect=OSError("no space left on device")):
        state_service._save_state()  # must not raise
