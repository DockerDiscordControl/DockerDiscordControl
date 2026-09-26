# -*- coding: utf-8 -*-
"""The Microsoft Translator region can be set.

THE FINDING (translation audit, 2026-09-26, #6): MicrosoftTranslatorProvider
takes a region and sends it as Ocp-Apim-Subscription-Region, but nothing ever
passed one: every request said "global". An Azure Translator resource is
usually created in a region (westeurope, eastus, ...), and its key is refused
with 401 under "global" - so choosing Microsoft in the panel could not work
for most keys, with no field that would have fixed it.

HOW THIS TEST CAN FAIL: it saves a region and builds the provider (the region
must arrive), saves one with a header break in it (it must not), and reads
the panel (the field must be there and be sent on save). Without a region,
"global" stays - keys made as global resources keep working.

COUNTER-CHECK (2026-09-26): red before - the setting was dropped, the
provider said "global", the panel had no field.
"""

from pathlib import Path

from services.translation.translation_config_service import TranslationSettings
from services.translation.translation_service import TranslationService

ROOT = Path(__file__).resolve().parents[2]


def _provider(settings):
    service = TranslationService.__new__(TranslationService)
    return service._get_provider(settings, "a-key")


def test_a_saved_region_reaches_the_provider():
    settings = TranslationSettings.from_dict({"provider": "microsoft", "microsoft_region": "westeurope"})
    assert settings.to_dict()["microsoft_region"] == "westeurope"
    assert _provider(settings).region == "westeurope"


def test_without_a_region_it_stays_global():
    settings = TranslationSettings.from_dict({"provider": "microsoft"})
    assert _provider(settings).region == "global"


def test_a_region_cannot_carry_a_header():
    settings = TranslationSettings.from_dict({"provider": "microsoft",
                                              "microsoft_region": "eu\r\nX-Evil: 1"})
    assert settings.microsoft_region == "global"


def test_the_panel_has_the_field_and_sends_it():
    markup = (ROOT / "app" / "templates" / "_channel_translation_settings.html").read_text(encoding="utf-8")
    script = (ROOT / "app" / "static" / "js" / "channel_translation.js").read_text(encoding="utf-8")
    assert 'id="ctMsRegion"' in markup
    assert "microsoft_region: document.getElementById('ctMsRegion')" in script
