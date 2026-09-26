# -*- coding: utf-8 -*-
"""A maintenance pause is set from the panel and from Discord (operator, 2026-09-26).

The panel: the Maintenance tab of the auto-action dialog and its three routes.
Discord: 🔧 on the admin overview, for the admin list, in row 1 (row 0 holds
five buttons, Discord's maximum). Both write the same pauses
(services/automation/maintenance.py, tested in
test_a_container_in_maintenance_is_left_alone.py).

HOW THIS TEST CAN FAIL: a route that pauses an unknown container or skips the
login, a button missing from the overview or crowding row 0, a Discord pause
that is not written, or a non-admin who may set one.

COUNTER-CHECK (2026-09-26): the unknown-container check removed - its case
went red; the admin check in the button removed - the non-admin case went red.
"""

import base64
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from werkzeug.security import generate_password_hash

from services.automation import maintenance

PASSWORD = "a-long-enough-panel-password"
SECURE = "https://panel.test"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def config(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir()
    (containers / "Valheim.json").write_text(json.dumps({"container_name": "Valheim", "active": True}))
    return tmp_path


@pytest.fixture
def panel(monkeypatch):
    monkeypatch.setenv("DDC_ENABLE_BACKGROUND_REFRESH", "false")
    monkeypatch.setenv("DDC_ENABLE_MECH_DECAY", "false")
    monkeypatch.delenv("DDC_TLS_MODE", raising=False)
    import app.auth as auth_module
    from app.auth import auth_limiter, clear_credential_cache
    from app.web import create_app

    hashed = generate_password_hash(PASSWORD)
    monkeypatch.setattr(auth_module, "load_config",
                        lambda: {"web_ui_user": "admin", "web_ui_password_hash": hashed})
    auth_limiter.ip_dict.clear()
    clear_credential_cache()
    return create_app({"TESTING": True, "WTF_CSRF_ENABLED": False}).test_client()


def _basic():
    return {"Authorization": "Basic " + base64.b64encode(f"admin:{PASSWORD}".encode()).decode()}


def test_the_panel_pauses_lists_and_ends(panel):
    started = panel.post("/api/watchdog/maintenance", json={"container": "Valheim", "minutes": 60},
                         headers=_basic(), base_url=SECURE)
    assert started.status_code == 200, started.get_data(as_text=True)
    assert maintenance.is_paused("Valheim")

    listed = panel.get("/api/watchdog/maintenance", headers=_basic(), base_url=SECURE).get_json()
    assert "Valheim" in listed["containers"] and "Valheim" in listed["pauses"]

    panel.delete("/api/watchdog/maintenance/Valheim", headers=_basic(), base_url=SECURE)
    assert not maintenance.is_paused("Valheim")


def test_the_panel_refuses_an_unknown_container(panel):
    answer = panel.post("/api/watchdog/maintenance", json={"container": "nope", "minutes": 60},
                        headers=_basic(), base_url=SECURE)

    assert answer.status_code == 400
    assert maintenance.pauses() == {}


def test_nobody_logged_in_pauses_nothing(panel):
    answer = panel.post("/api/watchdog/maintenance", json={"container": "Valheim", "minutes": 60},
                        base_url=SECURE)

    assert answer.status_code in (302, 401)
    assert maintenance.pauses() == {}


@pytest.mark.asyncio
async def test_the_overview_carries_the_button_in_its_own_row():
    from cogs.admin_overview import AdminOverviewView

    view = AdminOverviewView(MagicMock(), 123, has_running_containers=True, every_button=True)
    ids = [item.custom_id for item in view.children]
    rows = [item.row for item in view.children]

    assert "admin_overview_maintenance_123" in ids
    assert rows.count(0) <= 5


class _Interaction:
    def __init__(self, user_id=1):
        self.user = SimpleNamespace(id=user_id, __str__=lambda self: "op")
        self.response = SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock(),
                                        is_done=lambda: False)
        self.followup = SimpleNamespace(send=AsyncMock(return_value=MagicMock()))


@pytest.mark.asyncio
async def test_discord_writes_the_same_pause(monkeypatch):
    from cogs.watchdog_maintenance import MaintenanceView

    view = MaintenanceView(["Valheim"], {})
    view.chosen = "Valheim"
    hour = next(item for item in view.children if getattr(item, "label", None) == "1 h")

    await hour.callback(_Interaction())

    assert maintenance.is_paused("Valheim")


@pytest.mark.asyncio
async def test_only_an_admin_may_open_it(monkeypatch):
    import services.admin.admin_service as admin_module
    from cogs import admin_overview
    from cogs.watchdog_maintenance import AdminOverviewMaintenanceButton

    monkeypatch.setattr(admin_overview, "_admin_button_braked", AsyncMock(return_value=False))
    monkeypatch.setattr(admin_module, "get_admin_service",
                        lambda: SimpleNamespace(is_user_admin_async=AsyncMock(return_value=False)))
    interaction = _Interaction()

    await AdminOverviewMaintenanceButton(MagicMock(), 123).callback(interaction)

    sent = interaction.followup.send.await_args
    assert sent is not None and "admin" in str(sent.args[0]).lower()
    assert "view" not in sent.kwargs


def test_the_entry_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/maintenance.test.js by hand")
    result = subprocess.run([node, str(ROOT / "tests" / "js" / "maintenance.test.js")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("ok   - ") == 2, result.stdout
