# -*- coding: utf-8 -*-
"""A watchdog alarm reaches somebody even when Discord cannot be reached.

THE REQUEST (operator, 2026-09-26): every watchdog notice went to Discord and
nowhere else - with the token revoked, Discord down or the bot kicked, a dead
container went unreported. One URL now closes that: ntfy, Gotify, or any
webhook that takes JSON (services/automation/alert_webhook.py), sent only
when Discord failed ("fallback", the default) or always.

HOW THIS TEST CAN FAIL: no webhook call when Discord failed or there is no
bot at all, a call in fallback mode although Discord took the notice, the
wrong shape for ntfy/Gotify, a secret-bearing URL in the log, or a URL DDC
cannot post to accepted by the settings.

COUNTER-CHECK (2026-09-26): _alert() reduced to Discord only - the fallback
and no-bot cases went red; the mode check inverted - the "always"/"fallback"
cases went red.
"""

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.automation import alert_webhook
from services.automation.auto_action_config_service import AutoActionRule
from services.automation.container_watch import WatchEvent

STOPPED = WatchEvent("web", "stopped", "Container 'web' stopped (it was running).")
NTFY = "https://ntfy.sh/ddc-secret-topic"


@pytest.mark.parametrize("url, kind", [
    ("https://ntfy.sh/topic", "ntfy"), ("http://ntfy.local:8080/alerts", "ntfy"),
    ("https://gotify.example/message?token=abc", "gotify"),
    ("http://homeassistant:8123/api/webhook/ddc", "generic"),
])
def test_the_url_says_what_it_is(url, kind):
    assert alert_webhook.kind_of(url) == kind


def test_each_kind_gets_its_shape():
    headers, body = alert_webhook.build_request(NTFY, "DDC: web - stopped", "text", "web", "stopped")
    assert headers["Title"] == "DDC: web - stopped" and body == b"text"

    headers, body = alert_webhook.build_request("https://g/message?token=x", "T", "text")
    assert json.loads(body) == {"title": "T", "message": "text", "priority": 8}

    headers, body = alert_webhook.build_request("https://hook/x", "T", "text", "web", "stopped")
    assert json.loads(body)["container"] == "web" and json.loads(body)["kind"] == "stopped"


def test_the_log_names_the_host_not_the_url(caplog):
    def refuses(*_a, **_k):
        raise OSError("down")

    with caplog.at_level(logging.WARNING, logger="ddc.alert_webhook"):
        assert alert_webhook.send(NTFY, "T", "text", post=refuses) is False

    assert "ntfy.sh" in caplog.text and "secret-topic" not in caplog.text


@pytest.mark.parametrize("url, ok", [("", True), (NTFY, True), ("ftp://x/y", False),
                                     ("javascript:alert(1)", False), ("https://", False)])
def test_only_a_postable_url_is_accepted(url, ok):
    assert alert_webhook.valid_url(url) is ok


@pytest.fixture
def engine(monkeypatch):
    from services.automation import automation_service as mod

    service = mod.AutomationService.__new__(mod.AutomationService)
    service.config_service = MagicMock()
    settings = {"enabled": True, "protected_containers": [], "alert_webhook_url": NTFY,
                "alert_webhook_mode": "fallback"}
    service.config_service.get_global_settings.return_value = settings
    service.config_service.get_rules.return_value = [AutoActionRule.from_dict({
        "id": "r1", "name": "Tell me", "enabled": True, "priority": 1,
        "trigger": {"type": "container_state", "states": ["stopped"]},
        "action": {"type": "NOTIFY", "containers": []}, "safety": {"cooldown_minutes": 1}})]
    service.state_service = MagicMock()
    service.state_service.acquire_execution_locks.return_value = (True, "", None)
    monkeypatch.setattr(mod, "_own_container_name", lambda: "", raising=False)
    posted = []
    monkeypatch.setattr(alert_webhook, "send",
                        lambda url, title, message, container="", kind="": posted.append((url, container)) or True)
    return service, settings, posted


def _bot(delivers):
    channel = SimpleNamespace(send=AsyncMock())
    return SimpleNamespace(get_channel=lambda _id: channel if delivers else None)


@pytest.mark.asyncio
async def test_when_discord_fails_the_webhook_carries_it(engine):
    service, _settings, posted = engine

    await service.process_container_events([STOPPED], bot=_bot(False), control_channel_id=7)

    assert posted == [(NTFY, "web")]
    assert service.state_service.record_trigger.call_args.args[4] == "SUCCESS"


@pytest.mark.asyncio
async def test_without_a_bot_at_all_the_webhook_still_goes(engine):
    service, _settings, posted = engine

    await service.process_container_events([STOPPED], bot=None, control_channel_id=7)

    assert posted == [(NTFY, "web")]


@pytest.mark.asyncio
async def test_fallback_stays_quiet_when_discord_took_it(engine):
    service, _settings, posted = engine

    await service.process_container_events([STOPPED], bot=_bot(True), control_channel_id=7)

    assert posted == []


@pytest.mark.asyncio
async def test_always_sends_beside_discord(engine):
    service, settings, posted = engine
    settings["alert_webhook_mode"] = "always"

    await service.process_container_events([STOPPED], bot=_bot(True), control_channel_id=7)

    assert posted == [(NTFY, "web")]


def test_the_settings_refuse_a_url_ddc_cannot_post_to(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    (tmp_path / "auto_actions.json").write_text(json.dumps({"global_settings": {}, "auto_actions": []}))
    from services.automation.auto_action_config_service import AutoActionConfigService

    service = AutoActionConfigService()

    assert not service.update_global_settings({"alert_webhook_url": "ftp://x/y"}).success
    assert not service.update_global_settings({"alert_webhook_mode": "sometimes"}).success
    assert service.update_global_settings({"alert_webhook_url": NTFY, "alert_webhook_mode": "always"}).success
