# -*- coding: utf-8 -*-
"""A pair the bot switched off after five failures says so in the panel.

THE FINDING (translation audit, 2026-09-26, #8): after five failed
translations in a row the service stops using a pair - in memory, not in the
file. The panel kept showing it with its switch ON: a pair that translated
nothing, looking exactly like one that works. Only toggling it off and on
cleared the state, and nothing told the operator to do that. Fixing the pair
in the editor (the wrong language, say) left it switched off as well.

HOW THIS TEST CAN FAIL: it marks a pair as auto-disabled and reads the pair
list (the flag must be there), saves the pair in the editor (the flag must be
gone), and renders the list in node (a badge must show). A pair that works
must carry no flag.

COUNTER-CHECK (2026-09-26): red before on the flag and on the reset; the
working pair green on both sides.
"""

import base64
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "a-long-enough-panel-password"


def _basic():
    return {"Authorization": "Basic " + base64.b64encode(f"admin:{PASSWORD}".encode()).decode()}


@pytest.fixture
def panel(monkeypatch, tmp_path):
    (tmp_path / "config.json").write_text('{"language": "en"}')
    (tmp_path / "tasks.json").write_text("[]")
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("DDC_ENABLE_BACKGROUND_REFRESH", "false")
    monkeypatch.setenv("DDC_ENABLE_MECH_DECAY", "false")
    monkeypatch.delenv("DDC_TLS_MODE", raising=False)

    import app.auth as auth_module
    from app.auth import auth_limiter, clear_credential_cache
    from app.web import create_app
    from services.translation.translation_service import TranslationService

    hashed = generate_password_hash(PASSWORD)
    monkeypatch.setattr(auth_module, "load_config",
                        lambda: {"web_ui_user": "admin", "web_ui_password_hash": hashed})
    auth_limiter.ip_dict.clear()
    clear_credential_cache()

    pairs = [SimpleNamespace(id=pid, to_dict=lambda pid=pid: {"id": pid, "name": pid})
             for pid in ("broken", "working")]
    config = MagicMock()
    config.get_pairs.return_value = pairs
    config.get_pair.return_value = pairs[0]
    config.update_pair.return_value = MagicMock(success=True)
    service = TranslationService.__new__(TranslationService)
    import threading
    service._state_lock = threading.Lock()
    service._auto_disabled_pairs = {"broken"}
    service._consecutive_failures = {"broken": 5}
    monkeypatch.setattr("app.blueprints.translation_routes.get_translation_config_service",
                        lambda: config)
    monkeypatch.setattr("app.blueprints.translation_routes.get_translation_service",
                        lambda: service)
    yield create_app({"TESTING": True, "WTF_CSRF_ENABLED": False}), service
    auth_limiter.ip_dict.clear()


def _flags(app):
    answer = app.test_client().get("/api/translation/pairs", headers=_basic())
    return {p["id"]: p.get("auto_disabled") for p in answer.get_json()["pairs"]}


def test_the_list_says_which_pair_the_bot_switched_off(panel):
    app, _service = panel
    assert _flags(app) == {"broken": True, "working": False}


def test_saving_the_pair_gives_it_another_chance(panel):
    app, service = panel
    answer = app.test_client().put("/api/translation/pairs/broken", json={"name": "broken"},
                                   headers=_basic())
    assert answer.status_code == 200
    assert "broken" not in service._auto_disabled_pairs, (
        "the pair was fixed in the editor and stayed switched off")


def test_the_list_shows_a_badge_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/translation_pair_badges.test.js by hand")
    result = subprocess.run([node, str(ROOT / "tests" / "js" / "translation_pair_badges.test.js")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("ok     ") == 2, result.stdout
