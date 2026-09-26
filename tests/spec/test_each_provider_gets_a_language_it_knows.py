# -*- coding: utf-8 -*-
"""Each translation provider is sent a language code it accepts.

THE FINDING (translation audit, 2026-09-26, #7): the panel offers one list of
codes (DeepL's) for all three providers, and the conversion was "upper case
for DeepL, the first two letters in lower case for the rest". That fails
exactly where the list is richer than two letters:

* DeepL takes EN-GB, EN-US, PT-BR, PT-PT only as a TARGET. As a source it
  wants EN or PT - a pair "from English (British)" got HTTP 400 on every
  message and was auto-disabled after five.
* Microsoft has no "zh"; Chinese is zh-Hans. Every pair into Chinese failed.
* PT-PT became "pt" for Microsoft and Google - Brazilian Portuguese, while
  the operator chose European.
* NB became "nb" for Google, which calls Norwegian "no".

HOW THIS TEST CAN FAIL: it lets each provider build its request against a
recording session and reads the codes it sent. Plain codes (DE, EN-GB as a
DeepL target) must stay as they were.

COUNTER-CHECK (2026-09-26): red before on every case above, the plain codes
green on both sides.
"""

import asyncio

import pytest

from services.translation.translation_service import (DeepLProvider, GoogleTranslateProvider,
                                                       MicrosoftTranslatorProvider)


class _Recorder:
    def __init__(self):
        self.sent = {}

    def post(self, url, **kwargs):
        self.sent = kwargs
        recorder = self

        class _Response:
            status = 500

            async def text(self):
                return ""

            async def json(self):
                return {}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        return _Response()


def _sent(provider, target, source=None):
    session = _Recorder()
    asyncio.run(provider.translate("hello", target, source, session))
    return session.sent


def _deepl(target, source=None):
    payload = _sent(DeepLProvider("k"), target, source)["json"]
    return payload["target_lang"], payload.get("source_lang")


def _google(target, source=None):
    form = _sent(GoogleTranslateProvider("k"), target, source)["data"]
    return form["target"], form.get("source")


def _microsoft(target, source=None):
    params = _sent(MicrosoftTranslatorProvider("k"), target, source)["params"]
    return params["to"], params.get("from")


@pytest.mark.parametrize("source, expected", [("EN-GB", "EN"), ("PT-BR", "PT"), ("PT-PT", "PT")])
def test_deepl_gets_a_base_code_as_the_source(source, expected):
    assert _deepl("DE", source)[1] == expected


def test_deepl_keeps_the_variant_as_the_target():
    assert _deepl("EN-GB", "DE") == ("EN-GB", "DE")


def test_microsoft_gets_simplified_chinese():
    assert _microsoft("ZH")[0] == "zh-Hans"


def test_european_portuguese_stays_european():
    assert _microsoft("PT-PT")[0] == "pt-pt"
    assert _google("PT-PT")[0] == "pt-PT"


def test_google_calls_norwegian_no():
    assert _google("NB")[0] == "no"


def test_plain_codes_are_unchanged():
    assert _google("DE", "EN-GB") == ("de", "en")
    assert _microsoft("DE", "EN-US") == ("de", "en")
