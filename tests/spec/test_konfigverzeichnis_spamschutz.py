# -*- coding: utf-8 -*-
"""Der Spamschutz muss seine Einstellungen in ``DDC_CONFIG_DIR`` suchen.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND. ``SpamProtectionService`` leitet sein Verzeichnis ohne Argument aus
``Path(__file__).parents[2] / "config"`` her. Seine Einstellungen stehen im
Abschnitt ``spam_protection`` von ``channels_config.json`` - einer Datei, die
er sich mit ``config_service`` teilt, und DER folgt der Variable. Mit gesetztem
``DDC_CONFIG_DIR`` gibt es damit ZWEI ``channels_config.json``: Was das Panel
als Spamschutz speichert, landet in der einen, was der Rest der Anwendung als
Kanalkonfiguration fuehrt, in der anderen.

WIE HIER GEPRUEFT WIRD: Der Test legt eine ``channels_config.json`` mit einem
eigenen Spamschutz-Wert ins eingestellte Verzeichnis. Der Dienst muss GENAU
diesen Wert liefern - die Vorgabe (``restart`` 20) unterscheidet sich davon.
"""

import json

import pytest

from services.infrastructure.spam_protection_service import SpamProtectionService


@pytest.fixture
def verzeichnis(tmp_path, monkeypatch):
    ziel = tmp_path / "eigene_konfig"
    ziel.mkdir()
    monkeypatch.setenv("DDC_CONFIG_DIR", str(ziel))
    return ziel


def test_die_einstellungen_kommen_aus_dem_verzeichnis(verzeichnis):
    (verzeichnis / "channels_config.json").write_text(json.dumps({
        "spam_protection": {"button_cooldowns": {"restart": 7}},
    }), encoding="utf-8")

    dienst = SpamProtectionService()

    assert dienst.config_file == verzeichnis / "channels_config.json"
    assert dienst.get_button_cooldown("restart") == 7, (
        "Der Spamschutz liest seine Einstellungen nicht aus DDC_CONFIG_DIR "
        "(Vorgabe waere 20)."
    )
