# -*- coding: utf-8 -*-
"""An admins.json of the wrong shape answers "not an admin" instead of raising.

THE FINDING (stage 4 review before v3.1.0, section 10 pass 4 F4, verified
2026-09-29). _load_admin_users and _load_admin_containers read a file that
parses but whose top level is not an object ('[]', a string), or whose
admin list is null, and raised AttributeError/TypeError past both except
clauses: every admin check - the buttons in status channels, /addadmin -
failed with a stack trace until the file was fixed.

THE CONTRACT: such a file counts as "no admins" for the checks (logged),
like an unreadable one does in these two readers.

HOW THIS TEST CAN FAIL: a misshapen file raises out of an admin check again.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import pytest

USER = "111111111111111111"


@pytest.mark.parametrize("content", ["[]", '"text"', '{"discord_admin_users": null}',
                                     '{"discord_admin_users": ["%s"], "admin_containers": []}' % USER])
def test_a_misshapen_file_is_answered_not_raised(tmp_path, monkeypatch, content):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    (tmp_path / "admins.json").write_text(content, encoding="utf-8")
    from services.admin.admin_service import AdminService

    service = AdminService()
    is_admin = service.is_user_admin(USER, force_refresh=True)
    service.may_control(USER, "a", force_refresh=True)

    assert is_admin in (True, False)
