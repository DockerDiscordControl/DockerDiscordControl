# -*- coding: utf-8 -*-
"""One unreadable web setting does not throw away the password hash beside it.

THE FINDING (stage 4 review before v3.1.0, section 13 pass 3 F5 + pass 4
F6): extract_web_config built its result in one expression; a
session_timeout of "abc" made int() raise, and the handler returned the
DEFAULT web config - without the password hash. The v1.1.x migration then
wrote web_config.json with no hash, and the panel came up in first-run mode
(admin/setup accepted).

THE CONTRACT: an unreadable field falls back on its own; the others,
the hash above all, are kept.

HOW THIS TEST CAN FAIL: the hash is lost to another field's error again.

COUNTER-CHECK (2026-09-30): red before the change.
"""

from services.config.config_validation_service import ConfigValidationService

HASH = "pbkdf2:sha256:1$a$b"


def test_the_hash_survives_an_odd_timeout():
    web = ConfigValidationService.extract_web_config({"web_ui_password_hash": HASH,
                                                       "session_timeout": "abc"})
    assert web["web_ui_password_hash"] == HASH
    assert web["session_timeout"] == 3600


def test_a_readable_timeout_is_kept():
    assert ConfigValidationService.extract_web_config({"session_timeout": "1800"})["session_timeout"] == 1800
