# -*- coding: utf-8 -*-
"""A groups.json with a wrongly typed field costs the groups, not the admin menu.

THE FINDING (stage 4 review before v3.1.0, section 38 pass 4): invalid
JSON in groups.json was handled - _read turned it into an OSError, and the
admin list offered the containers without the groups. A syntactically
valid file with a wrongly typed field was not: {"containers": null} or
"allowed_actions": 5 made _read raise TypeError, which group_entries does
not catch, so both admin buttons lost the whole menu - against the
promise in group_entries ("a failure here costs the groups, not the
menu"). The trigger is a hand edit; the panel always writes lists.

THE CONTRACT: a file whose groups cannot be read as groups is a file that
cannot be read - said out loud, as an OSError.

HOW THIS TEST CAN FAIL: the TypeError escapes again and the menu is gone.

COUNTER-CHECK (2026-09-30): red before the change (TypeError).
"""

import json

import pytest

from cogs.group_control import controllable_entries
from services.config import group_service


@pytest.mark.parametrize("group", [
    {"name": "G", "containers": None},
    {"name": "G", "containers": ["web"], "allowed_actions": 5},
    {"name": "G", "containers": 7},
])
def test_the_containers_are_still_offered(tmp_path, monkeypatch, group):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    (tmp_path / "groups.json").write_text(json.dumps({"groups": [group]}), encoding="utf-8")
    group_service.reset_group_service()
    try:
        entries = controllable_entries([{"docker_name": "web"}])
        assert [entry["name"] for entry in entries] == ["web"]
        with pytest.raises(OSError):
            group_service.get_group_service().get_groups()
    finally:
        group_service.reset_group_service()
