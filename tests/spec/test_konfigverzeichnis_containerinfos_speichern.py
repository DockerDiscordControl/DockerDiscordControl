# -*- coding: utf-8 -*-
"""Das Speichern der Container-Infos muss die Container aus ``DDC_CONFIG_DIR``
finden.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND. ``ConfigurationSaveService._save_configuration_files``
(``configuration_save_service.py:282``) sammelt die Container mit
``Path('config/containers')`` - RELATIV zum Arbeitsverzeichnis, ohne die
Variable. Aus dieser Liste speist sich ``save_container_info_from_web``, und
nur wenn sie NICHT leer ist::

    if all_container_names:
        ... Infos deaktivierter Container leeren ...
        save_container_info_from_web(form_data, all_container_names)

Mit gesetzter Variable (oder anderem Arbeitsverzeichnis) ist die Liste leer:
Info-Aenderungen aus dem Web-Formular werden STUMM nicht gespeichert, und die
Infos deaktivierter Container bleiben stehen. Im Container stimmt der relative
Pfad heute nur, weil das Arbeitsverzeichnis zufaellig /app ist.

Gefunden hat diese Stelle erst die zweite, breitere Suche der Sperrklinke
(test_konfigverzeichnis_eine_quelle.py) - die erste Scanner-Fassung sah
relative "config/..."-Pfade nicht.

WIE HIER GEPRUEFT WIRD: Die beiden Speicherfunktionen und ``save_config`` sind
Mitschreiber - geprueft wird, WAS an sie uebergeben wird. Die Container-Dateien
liegen im Test-Verzeichnis; die Erwartung stammt aus dem Test.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from services.web.configuration_save_service import ConfigurationSaveService


@pytest.fixture
def verzeichnis(tmp_path, monkeypatch):
    ziel = tmp_path / "eigene_konfig"
    (ziel / "containers").mkdir(parents=True)
    for name in ("aktiv", "ruhend"):
        (ziel / "containers" / f"{name}.json").write_text(
            json.dumps({"container_name": name}), encoding="utf-8")
    monkeypatch.setenv("DDC_CONFIG_DIR", str(ziel))
    return ziel


def _speichere(form_data):
    info = MagicMock(return_value={})
    with patch("services.config.config_service.save_config"), \
            patch("app.utils.container_info_web_handler.save_container_configs_from_web",
                  return_value={}), \
            patch("app.utils.container_info_web_handler.save_container_info_from_web", info):
        ergebnis = ConfigurationSaveService()._save_configuration_files(
            {"servers": [{"docker_name": "aktiv"}]}, form_data, False)
    return ergebnis, info


def test_die_infos_aller_container_werden_gespeichert(verzeichnis):
    """DER BEFUND: Ohne gefundene Container wird gar nichts gespeichert."""
    ergebnis, info = _speichere({})

    assert ergebnis.success, getattr(ergebnis, "error", None)
    info.assert_called_once()
    assert sorted(info.call_args.args[1]) == ["aktiv", "ruhend"], (
        "Die Container-Infos werden nicht fuer die Container aus "
        f"DDC_CONFIG_DIR gespeichert: {info.call_args}"
    )


def test_die_infos_deaktivierter_container_werden_geleert(verzeichnis):
    """DER BEFUND, zweite Folge."""
    form_data = {}
    _speichere(form_data)

    assert form_data.get("info_enabled_ruhend") == "0", (
        "Der deaktivierte Container 'ruhend' behaelt seine Infos."
    )
    assert "info_enabled_aktiv" not in form_data
