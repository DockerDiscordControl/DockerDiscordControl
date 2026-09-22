# -*- coding: utf-8 -*-
"""Which channels are control channels is decided in one place.

The update notice (services/infrastructure/update_notifier.py) found the
control channels itself, in both config formats. The container watchdog
(Phase 4a) needs the same answer for its default notice channel. A second
copy of that rule would drift from the first; both use
services.config.channel_roles.control_channel_ids now.

COUNTER-CHECK (2026-09-22): red before the helper existed and while the
notifier still had its own loop.
"""

from pathlib import Path


def test_both_config_formats():
    from services.config.channel_roles import control_channel_ids

    new = {"channel_permissions": {"111": {"commands": {"control": True}},
                                   "222": {"commands": {"control": False}},
                                   "bad": {"commands": {"control": True}}}}
    assert control_channel_ids(new) == [111]
    old = {"channels": [{"channel_id": "333", "permissions": ["control"]},
                        {"channel_id": "444", "permissions": ["status"]}]}
    assert control_channel_ids(old) == [333]
    assert control_channel_ids({}) == []


def test_the_update_notice_uses_it():
    source = (Path(__file__).resolve().parents[2] / "services" / "infrastructure"
              / "update_notifier.py").read_text(encoding="utf-8")
    assert "control_channel_ids(" in source
    assert ".get('control', False)" not in source, "the notifier still has its own copy of the rule"
