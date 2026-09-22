# -*- coding: utf-8 -*-
# @covers Z1
"""Z1 - an unreadable automation configuration is never overwritten with an empty one.

THE FINDING (stage 4 review pass 1, stage B, section 10 F1, re-checked
2026-09-20): ``AutoActionConfigService._load_config_file`` answers a
``JSONDecodeError`` or ``IOError`` with an EMPTY structure
(``{"global_settings": {}, "auto_actions": []}``). Every writer -
``add_rule``, ``update_rule``, ``update_global_settings`` - then saves that
empty structure back over the file and reports success. One unreadable read
(a partial copy, a hand edit, disk trouble) and every automation rule the
operator ever configured is gone, with a success message on top. The read
error itself is logged, the destruction is not.

Z1 is about the donation ledger, but its sentence is the same one: no
operation overwrites a record without a restorable copy. Here the record is
the rules file, and the answer is simpler - do not write at all when the
current content could not be read.
"""

import json

import pytest

from services.automation.auto_action_config_service import AutoActionConfigService

RULE = {"name": "Restart on crash",
        "trigger": {"channel_ids": ["123456789012345678"], "keywords": ["crash"]},
        "action": {"type": "restart", "containers": ["vrising"]},
        "enabled": True}
BROKEN = '{"global_settings": {"enabled": true}, "auto_actions": [ {"id": "r1",'


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    from utils import config_paths
    if hasattr(config_paths, "clear_config_dir_cache"):
        config_paths.clear_config_dir_cache()
    return AutoActionConfigService()


def _write_broken(service):
    service.config_file.write_text(BROKEN, encoding="utf-8")


def test_a_broken_file_is_not_replaced_by_add_rule(service):
    _write_broken(service)

    result = service.add_rule(dict(RULE))

    assert not result.success, "a rule was 'added' on top of a file that could not be read"
    assert service.config_file.read_text(encoding="utf-8") == BROKEN, (
        "the unreadable configuration was overwritten - every existing rule is gone"
    )


def test_a_broken_file_is_not_replaced_by_global_settings(service):
    _write_broken(service)

    result = service.update_global_settings({"enabled": False})

    assert not result.success
    assert service.config_file.read_text(encoding="utf-8") == BROKEN


def test_a_readable_file_still_takes_new_rules(service):
    """Counter-check: otherwise 'never write' would pass the tests above."""
    result = service.add_rule(dict(RULE))

    assert result.success, getattr(result, "error", None)
    saved = json.loads(service.config_file.read_text(encoding="utf-8"))
    assert [r["name"] for r in saved["auto_actions"]] == ["Restart on crash"]
