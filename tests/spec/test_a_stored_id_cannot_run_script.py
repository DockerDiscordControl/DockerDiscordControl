# -*- coding: utf-8 -*-
"""An id of a rule or translation pair cannot run script in the panel.

THE FINDING (translation audit, 2026-09-26, #9): the rule list and the pair
list wrote the id into onclick="openRuleEditor('${safeId}')" after an HTML
escape that left the single quote alone - and an escaped &#39; would not have
helped, because the browser decodes it before the handler runs. An id of
``x');alert(1);//`` ran as script when the panel opened. Both ``add_rule``
and ``add_pair`` took the id from the request, and a restored backup brings
its own files, so the id was the sender's to choose.

The admin list's "every container" switch had the same pattern; admin ids
are checked for digits on save, but not on a restored backup.

THE TWO HALVES, each on its own: the server now makes the id of every NEW
rule and pair itself, and the lists write any id - old, restored - as a
JavaScript string (``ddcJsArg`` in escape.js). tests/js/list_ids_stay_data.test.js
checks the second half in node.

COUNTER-CHECK (2026-09-26): red before - the chosen id was stored as sent,
and in node both lists opened an onmouseover attribute from the id.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EVIL = "x');alert(1);//"


@pytest.fixture
def config_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    return tmp_path


def test_a_new_rule_gets_an_id_from_the_server(config_dir):
    from services.automation.auto_action_config_service import AutoActionConfigService

    result = AutoActionConfigService().add_rule({
        "id": EVIL, "name": "r", "enabled": True,
        "trigger": {"channel_ids": ["123456789012345678"], "keywords": ["x"]},
        "action": {"type": "NOTIFY", "containers": []},
    })
    assert result.success, result.error
    assert result.data.id != EVIL, "the rule was stored under the id the request chose"


def test_a_new_pair_gets_an_id_from_the_server(config_dir):
    from services.translation.translation_config_service import TranslationConfigService

    result = TranslationConfigService().add_pair({
        "id": EVIL, "name": "p", "enabled": True,
        "source_channel_id": "123456789012345678", "target_channel_id": "223456789012345678",
        "target_language": "DE",
    })
    assert result.success, result.error
    assert result.data.id != EVIL, "the pair was stored under the id the request chose"


def test_the_lists_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/list_ids_stay_data.test.js by hand")
    result = subprocess.run([node, str(ROOT / "tests" / "js" / "list_ids_stay_data.test.js")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("ok     ") == 3, result.stdout
