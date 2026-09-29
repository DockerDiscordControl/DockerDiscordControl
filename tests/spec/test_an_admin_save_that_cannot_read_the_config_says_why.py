# -*- coding: utf-8 -*-
"""An admin-list save that cannot read the configuration fails with the real reason.

THE FINDING (stage 4 review before v3.1.0, section 10 pass 4 F5): the save
reads the configuration before it binds the admins.json path. When that read
raised an OSError, the handler's log line formatted the path that did not
exist yet and raised UnboundLocalError from inside the except block - the
caller got that instead of False, and the real cause was masked.

THE CONTRACT: False, and the cause in the log.

HOW THIS TEST CAN FAIL: UnboundLocalError escapes again.

COUNTER-CHECK (2026-09-29): red before the change.
"""

import logging

from services.admin.admin_service import get_admin_service


def test_the_save_returns_false_and_logs_the_cause(monkeypatch, caplog, tmp_path):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))

    def _broken():
        raise OSError("config directory unreadable: boom")
    monkeypatch.setattr("services.config.config_service.load_config", _broken)

    with caplog.at_level(logging.ERROR):
        assert get_admin_service().save_admin_data(["111111111111111111"]) is False

    assert any("boom" in r.getMessage() for r in caplog.records), "the real cause is not in the log"
