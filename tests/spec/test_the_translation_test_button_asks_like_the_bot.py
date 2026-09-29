# -*- coding: utf-8 -*-
"""The panel's translation Test button asks the provider the way the bot does.

THE FINDING (stage 4 review before v3.1.0, section 33 pass 4 F8): the Test
button re-implements the provider calls, and differed from the bot where it
matters. For Microsoft it never sent Ocp-Apim-Subscription-Region, although
the operator sets the region in the panel and the bot sends it - a regional
Azure key tested as "Microsoft API error: HTTP 401" while the bot translated
fine. And it cut every language code to two letters instead of using the
bot's rule: Chinese went out as "zh" (Microsoft wants "zh-Hans"), Norwegian
as "nb" (Google wants "no").

THE CONTRACT: region header and language codes as the bot sends them
(translation_service._normalize_language_code).

HOW THIS TEST CAN FAIL: the region or the code differs from the bot's again.

COUNTER-CHECK (2026-09-29): the Microsoft and Google cases red before the
change; the DeepL case green before and after.
"""

import io
import json
import urllib.parse

import pytest

from app.blueprints import translation_routes as routes
from services.translation.translation_config_service import TranslationSettings
from tests.spec.test_an_unreadable_key_is_not_a_missing_key import client  # noqa: F401 - fixture


class _Config:
    def __init__(self, provider):
        self.provider = provider

    def get_settings(self):
        settings = TranslationSettings()
        settings.provider = self.provider
        settings.api_key_env = "DDC_SPEC_TRANSLATION_KEY"
        settings.microsoft_region = "westeurope"
        return settings


def _ask(client, monkeypatch, provider, target, answer):  # noqa: F811
    monkeypatch.setenv("DDC_SPEC_TRANSLATION_KEY", "k")
    monkeypatch.setattr(routes, "get_translation_config_service", lambda: _Config(provider))
    sent = {}

    class _Response(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def _urlopen(request, timeout=None, context=None):
        sent["request"] = request
        return _Response(json.dumps(answer).encode())
    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    client.post("/api/translation/test", json={"text": "hi", "target_language": target})
    request = sent["request"]
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(request.full_url).query))
    body = request.data.decode() if request.data else ""
    return request, query, body


def test_microsoft_gets_the_region_and_its_own_chinese(client, monkeypatch):  # noqa: F811
    request, query, _ = _ask(client, monkeypatch, "microsoft", "ZH",
                             [{"translations": [{"text": "x"}]}])
    assert request.get_header("Ocp-apim-subscription-region") == "westeurope", request.headers
    assert query.get("to") == "zh-Hans", query


def test_google_gets_its_own_norwegian(client, monkeypatch):  # noqa: F811
    _, _, body = _ask(client, monkeypatch, "google", "NB",
                      {"data": {"translations": [{"translatedText": "x"}]}})
    assert dict(urllib.parse.parse_qsl(body)).get("target") == "no", body


def test_deepl_is_unchanged(client, monkeypatch):  # noqa: F811
    _, _, body = _ask(client, monkeypatch, "deepl", "EN-GB",
                      {"translations": [{"text": "x"}]})
    assert json.loads(body)["target_lang"] == "EN-GB"
