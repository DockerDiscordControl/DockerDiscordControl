# -*- coding: utf-8 -*-
"""DDC_ADMIN_PASSWORD acts once per value: a new value resets the password, the
same value never undoes a password changed in the panel.

THE OPERATOR, 2026-09-27: "if a user forgets the password and saves a new one
through the variable, the new password should apply - good idea or security
hole?" Both halves were true of the two obvious designs:

* acting only while NO password is set (the old rule) left no reset through
  the variable - a forgotten password stayed forgotten;
* acting at EVERY start would bring back an old password with the next update
  or reboot, after the operator had changed it in the panel - perhaps because
  it leaked. The panel would say "changed", the restart would quietly undo it.

So DDC stores a salted hash of the value it last applied and acts only when
the variable holds something else (app/utils/web_helpers.py
set_initial_password_from_env, services/config/config_service.py
ENV_PASSWORD_MARKER_KEY). An installation from before this rule has a password
but no marker: its variable is remembered, never applied, for the same reason.

HOW THIS TEST CAN FAIL:
* the first start with the variable does not set the password;
* a restart with the same value undoes a password changed in the panel;
* a restart with a new value does not reset it, or old sessions survive it;
* an old installation's password is overwritten on upgrade;
* an ordinary save of the settings drops the marker (the reset would then
  stop working without a word);
* the marker is a fast hash, i.e. a shortcut to the password;
* the start applies the variable over a configuration it could not read;
* the app stops calling the function at start (the call site).

COUNTER-CHECK (2026-09-27), each made on purpose and seen red:
* marker check removed (variable applied at every start)  -> the panel case red;
* "variable changed" ignored (old rule)                   -> the reset case red;
* old-installation branch applies instead of remembering  -> the upgrade case red;
* marker taken out of save_config's preserved fields      -> the save case red;
* marker hashed with another scheme (scrypt)              -> the marker case red.
* marker not written after the variable was applied      -> the reset case red.
"""

import json
import logging
import re
from pathlib import Path

import pytest
from flask import Flask
from werkzeug.security import generate_password_hash

import services.config.config_service as config_service_module
from services.config.config_service import ENV_PASSWORD_MARKER_KEY, ConfigService

ROOT = Path(__file__).resolve().parents[2]

FIRST = "first-variable-value"
PANEL = "changed-in-the-panel"
RESET = "second-variable-value"


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(ConfigService, "_instance", None)
    svc = ConfigService()
    monkeypatch.setattr(config_service_module, "_config_service_instance", svc)
    (tmp_path / "config.json").write_text(json.dumps({"language": "en", "web_ui_password_hash": None}))
    return svc


def _start(monkeypatch, value):
    """What a container start does with the variable."""
    import app.utils.web_helpers as wh
    monkeypatch.setenv("DDC_ADMIN_PASSWORD", value)
    wh.set_initial_password_from_env()


def _logs_in(password):
    from app.auth import verify_password
    app = Flask(__name__)
    app.secret_key = "t"
    with app.test_request_context():
        return verify_password("admin", password) == "admin"


def _binding():
    from app.auth import password_binding
    return password_binding()


def test_the_first_start_sets_the_password(service, monkeypatch):
    _start(monkeypatch, FIRST)
    assert _logs_in(FIRST)
    assert not _logs_in("setup"), "the first-run login stays open although a password is set"


def test_the_same_value_never_undoes_a_password_changed_in_the_panel(service, monkeypatch):
    _start(monkeypatch, FIRST)
    config_service_module.change_web_ui_password(PANEL)

    _start(monkeypatch, FIRST)  # the next update or reboot

    assert _logs_in(PANEL), "a restart undid the password changed in the panel"
    assert not _logs_in(FIRST), "the old variable value works again after a restart"


def test_a_new_value_resets_the_password_and_ends_every_session(service, monkeypatch):
    _start(monkeypatch, FIRST)
    config_service_module.change_web_ui_password(PANEL)
    session_before = _binding()

    _start(monkeypatch, RESET)  # the operator forgot PANEL and set a new value

    assert _logs_in(RESET), "a new variable value did not reset the password"
    assert not _logs_in(PANEL)
    assert _binding() != session_before, "sessions of the forgotten password survive the reset"

    _start(monkeypatch, RESET)  # and the next restart leaves it alone
    config_service_module.change_web_ui_password(PANEL)
    _start(monkeypatch, RESET)
    assert _logs_in(PANEL)


def test_an_installation_from_before_the_rule_keeps_its_password(service, monkeypatch):
    # A password of its own and no marker: set through the panel or /setup by an
    # earlier version, with some value still in the variable.
    config_service_module.change_web_ui_password(PANEL)
    assert service.get_config(force_reload=True).get(ENV_PASSWORD_MARKER_KEY) is None

    _start(monkeypatch, FIRST)
    assert _logs_in(PANEL), "the upgrade overwrote the operator's own password"
    assert not _logs_in(FIRST)

    _start(monkeypatch, RESET)  # from now on a new value is a reset
    assert _logs_in(RESET)


def test_saving_the_settings_keeps_the_marker(service, monkeypatch):
    _start(monkeypatch, FIRST)
    config = service.get_config(force_reload=True)
    config.pop(ENV_PASSWORD_MARKER_KEY)  # a save built without the field
    assert service.save_config(config).success

    config_service_module.change_web_ui_password(PANEL)
    _start(monkeypatch, RESET)
    assert _logs_in(RESET), "after a settings save the variable could no longer reset the password"


def test_the_form_cannot_write_the_marker():
    from services.config.config_form_parser_service import ConfigFormParserService
    assert ENV_PASSWORD_MARKER_KEY in ConfigFormParserService._PROTECTED_KEYS


def test_the_marker_is_no_shortcut_to_the_password(service, monkeypatch):
    _start(monkeypatch, FIRST)
    marker = service.get_config(force_reload=True)[ENV_PASSWORD_MARKER_KEY]
    stored = service.get_config(force_reload=True)["web_ui_password_hash"]
    # Salted and as slow as the password hash itself: never the value, never a fast digest.
    assert FIRST not in marker
    assert marker.split("$")[0] == stored.split("$")[0] == "pbkdf2:sha256:600000"


def test_an_unreadable_configuration_is_not_written_over(monkeypatch, caplog):
    import app.utils.web_helpers as wh
    written = []
    monkeypatch.setattr(config_service_module, "load_config",
                        lambda: {"web_ui_password_hash": None, "config_read_errors": ["denied"]})
    monkeypatch.setattr(config_service_module, "change_web_ui_password",
                        lambda *a, **k: written.append(a))
    monkeypatch.setattr(config_service_module, "update_config_fields",
                        lambda *a, **k: written.append(a))
    monkeypatch.setenv("DDC_ADMIN_PASSWORD", FIRST)
    with caplog.at_level(logging.ERROR):
        wh.set_initial_password_from_env()
    assert written == []
    assert any("could not be read" in r.getMessage() for r in caplog.records)


def test_the_app_applies_the_variable_at_start():
    source = (ROOT / "app" / "web_ui.py").read_text(encoding="utf-8")
    assert re.search(r"^set_initial_password_from_env\(\)", source, re.M), \
        "app/web_ui.py no longer calls set_initial_password_from_env() at start"


def test_an_old_default_password_is_still_replaced(service, monkeypatch):
    service.update_config_fields({"web_ui_password_hash":
                                  generate_password_hash("admin", method="pbkdf2:sha256:600000")})
    _start(monkeypatch, FIRST)
    assert _logs_in(FIRST) and not _logs_in("admin")
