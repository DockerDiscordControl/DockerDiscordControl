# -*- coding: utf-8 -*-
"""Switching channel translation on or off changes nothing else.

THE FINDING (audit 2026-09-26). The global switch (channel_translation.js
toggleGlobalCT) posts five fields - provider, DeepL URL, two limits and
"enabled". The service REPLACED the settings with what it was sent, so every
field the switch did not name fell back to its default: "show original link"
and "provider footer" came back on, and a set api_key_env or
google_project_id was dropped. The operator would notice days later, in
Discord. A refused save also said nothing.

THE CONTRACT: a settings save merges - what a request does not name keeps its
value; the encrypted key is never taken from a request.

COUNTER-CHECK (2026-09-26): red before the fix - show_original_link read
True again after the switch.
"""

import pytest


@pytest.fixture
def service(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    from services.translation.translation_config_service import TranslationConfigService

    return TranslationConfigService()


def test_the_switch_keeps_the_display_settings(service):
    assert service.update_settings({"provider": "deepl", "show_original_link": False,
                                    "show_provider_footer": False,
                                    "google_project_id": "my-project"}).success

    # exactly what toggleGlobalCT posts
    assert service.update_settings({"provider": "deepl",
                                    "deepl_api_url": "https://api-free.deepl.com/v2/translate",
                                    "rate_limit_per_minute": 60, "max_text_length": 5000,
                                    "enabled": True}).success

    settings = service.get_settings()
    assert settings.enabled is True
    assert settings.show_original_link is False
    assert settings.show_provider_footer is False
    assert settings.google_project_id == "my-project"


def test_a_named_field_still_changes(service):
    """Counter-case: merging must not freeze the settings."""
    service.update_settings({"provider": "deepl", "show_original_link": False})
    service.update_settings({"provider": "deepl", "show_original_link": True})

    assert service.get_settings().show_original_link is True
