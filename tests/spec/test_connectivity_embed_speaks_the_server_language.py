# -*- coding: utf-8 -*-
"""The Docker-connectivity error embed must use the server's language.

No ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

THE FINDING. ``DockerConnectivityService.create_error_embed_data`` chose
between two hard-wired variants: ``language == 'en'`` got English, EVERY other
language got German ("German (default)"). The callers pass the configured
server language (status_handlers.py, docker_control.py), so a French, Spanish or
Japanese server saw this error in German.

THE FIX: the English texts are source strings of the translation catalog; the
German ones moved into ``locales/de.json``; the other locales carried the English
text, as the catalog key-parity contract requires. German servers keep
German, and no German is left in the code. Since 2026-09-27 every catalogue
translates these titles, so a French server reads French - never German.

HOW IT IS CHECKED: the real service, three languages, all three contexts. The
German expectation comes from the former hard-wired text, not from the catalog.
"""

import json
from pathlib import Path

import pytest

from services.infrastructure.docker_connectivity_service import (
    DockerConnectivityService,
    DockerErrorEmbedRequest,
)

CONTEXTS = ("serverstatus", "individual_container", "general")
ENGLISH_TITLES = {
    "serverstatus": "🚨 Container Monitoring Unavailable",
    "individual_container": "🚨 System Administrator Required",
    "general": "🚨 Docker Connectivity Issue",
}
# The texts that used to be hard-wired in the code for German.
GERMAN_TITLES = {
    "serverstatus": "🚨 Container-Überwachung nicht verfügbar",  # language data
    "individual_container": "🚨 Systemadministrator erforderlich",  # language data
    "general": "🚨 Docker-Verbindungsproblem",  # language data (reworded 2026-09-27)
}


def _embed(language, context):
    request = DockerErrorEmbedRequest(error_message="socket gone", language=language, context=context)
    result = DockerConnectivityService().create_error_embed_data(request)
    assert result.success, result.description
    return result


@pytest.mark.parametrize("context", CONTEXTS)
def test_a_french_server_does_not_get_german(context):
    """THE FINDING."""
    result = _embed("fr", context)
    # Since 2026-09-27 fr.json translates these titles, so a French server gets
    # French. What this case was always about stays: never the German variant.
    french = json.loads((Path(__file__).resolve().parents[2] / "locales" / "fr.json")
                        .read_text(encoding="utf-8"))
    assert result.title != GERMAN_TITLES[context], (
        f"A French server gets {result.title!r} - the German variant was the default "
        "for every language other than English."
    )
    assert result.title == french.get(ENGLISH_TITLES[context], ENGLISH_TITLES[context])
    assert "socket gone" in result.description


@pytest.mark.parametrize("context", CONTEXTS)
def test_a_german_server_keeps_german(context):
    """No regression for German servers: the text now comes from de.json."""
    result = _embed("de", context)
    assert result.title == GERMAN_TITLES[context]
    assert "socket gone" in result.description
    assert "https://ddc.bot" in result.footer_text


@pytest.mark.parametrize("context", CONTEXTS)
def test_an_english_server_keeps_english(context):
    result = _embed("en", context)
    assert result.title == ENGLISH_TITLES[context]
    assert "socket gone" in result.description
