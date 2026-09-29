# -*- coding: utf-8 -*-
"""An admin's container assignment edited in admins.json takes effect after the cache time.

THE FINDING (stage 4 review before v3.1.0, section 10 pass 4 F2, verified
2026-09-29). get_admin_containers asked is_user_admin first, which on an
expired cache reloaded the user list and stamped the shared timestamp -
so the assignment cache checked right after always looked fresh and was
only ever loaded once. An assignment narrowed in admins.json outside the
process (host shell, docker exec) never took effect until a restart:
may_control kept granting the old, wider scope.

THE CONTRACT: the assignment is re-read when the admin list is, after the
cache time (5 minutes).

HOW THIS TEST CAN FAIL: the assignment cache outlives the list cache again.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import json
from datetime import timedelta

USER = "111111111111111111"


def test_a_narrowing_on_disk_is_read_after_the_cache_time(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    admins = tmp_path / "admins.json"
    admins.write_text(json.dumps({"discord_admin_users": [USER]}), encoding="utf-8")
    from services.admin.admin_service import AdminService

    service = AdminService()
    assert service.may_control(USER, "a") is True

    admins.write_text(json.dumps({"discord_admin_users": [USER],
                                  "admin_containers": {USER: ["b"]}}), encoding="utf-8")
    service._cache_timestamp -= timedelta(minutes=6)       # the cache time has passed

    assert service.may_control(USER, "a") is False, "the old, wider scope still applies"
    assert service.may_control(USER, "b") is True
