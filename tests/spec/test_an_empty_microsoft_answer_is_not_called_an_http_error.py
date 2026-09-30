# -*- coding: utf-8 -*-
"""A Microsoft answer without a translation is not reported as an HTTP error.

THE FINDING (stage 4 review before v3.1.0, section 33 pass 4): when
Microsoft answered HTTP 200 with a body that holds no usable translation
([{}], [{"translations": []}] or []), the Test button's route fell
through to "Microsoft API error: HTTP 200" - a failure text for a call
that succeeded, which sends the operator looking at keys and regions.

THE CONTRACT: such an answer is reported as "answered without a
translation".

HOW THIS TEST CAN FAIL: "HTTP 200" is called an error again.

COUNTER-CHECK (2026-09-30): red before the change ("HTTP 200").
"""

import io
import json

import pytest

from app.blueprints import translation_routes as routes
from tests.spec.test_an_unreadable_key_is_not_a_missing_key import client  # noqa: F401 - fixture
from tests.spec.test_the_translation_test_button_asks_like_the_bot import _Config


@pytest.mark.parametrize("answer", [[{}], [{"translations": []}], []])
def test_the_error_says_what_happened(client, monkeypatch, answer):  # noqa: F811
    monkeypatch.setenv("DDC_SPEC_TRANSLATION_KEY", "k")
    monkeypatch.setattr(routes, "get_translation_config_service", lambda: _Config("microsoft"))

    class _Response(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda request, timeout=None, context=None: _Response(json.dumps(answer).encode()))

    body = client.post("/api/translation/test", json={"text": "hi", "target_language": "DE"}).get_json()

    assert body["success"] is False
    assert "HTTP 200" not in body["error"]
    assert "without a translation" in body["error"]
