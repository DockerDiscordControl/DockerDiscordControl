# -*- coding: utf-8 -*-
"""Rules and runtime state of the auto actions must live in
``DDC_CONFIG_DIR``.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

THE FINDING. ``AutoActionConfigService`` (auto_actions.json) and
``AutoActionStateService`` (auto_actions_state.json) derive their files from
``Path(__file__).parents[2] / "config"`` and ignore the variable. Each is the
only reader and writer of its file - there is no gap between two readers. The
consequences are the same as for the admin list (8ac5427):

1. Anyone who points ``DDC_CONFIG_DIR`` at their volume has the rules and the
   cooldown states outside of it - gone when the container is recreated.
2. Z2, more serious here: ``AutoActionConfigService`` already WRITES a default
   file in its constructor if none exists - so in the test run into the REAL
   config/.

HOW IT IS CHECKED HERE: the constructor is built against an empty directory
(the default file must be created THERE); the state is read from a file the
test creates.
"""

import json

import pytest

from services.automation.auto_action_config_service import AutoActionConfigService
from services.automation.auto_action_state_service import AutoActionStateService


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    target = tmp_path / "custom_config"
    target.mkdir()
    monkeypatch.setenv("DDC_CONFIG_DIR", str(target))
    return target


def test_the_default_file_is_created_in_the_directory(config_dir):
    """THE FINDING, Z2 part: the constructor writes."""
    service = AutoActionConfigService()

    assert service.config_file == config_dir / "auto_actions.json"
    assert (config_dir / "auto_actions.json").exists(), (
        "The default auto_actions.json was not created in DDC_CONFIG_DIR."
    )


def test_the_state_comes_from_the_directory(config_dir):
    (config_dir / "auto_actions_state.json").write_text(json.dumps({
        "global_last_triggered": 1234.5,
        "rule_cooldowns": {"rule_probe": 99.0},
        "container_cooldowns": {},
        "trigger_history": {},
    }), encoding="utf-8")

    service = AutoActionStateService()

    assert service.state_file == config_dir / "auto_actions_state.json"
    assert service.rule_cooldowns == {"rule_probe": 99.0}, (
        "The cooldown state of the auto actions does not come from DDC_CONFIG_DIR."
    )
