# -*- coding: utf-8 -*-
"""Die Liste der aktiven Container fuer das Web-Panel muss ``DDC_CONFIG_DIR``
folgen.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND. ``app/utils/shared_data.py`` berechnet ``CONTAINERS_DIR`` beim
IMPORT aus ``Path(__file__).parents[2] / "config"`` und beachtet die Variable
nicht. ``load_active_containers_from_config`` speist daraus die aktiven
Container fuer die Konfigurationsseite (configuration_page_service.py:238), die
Aufgabenverwaltung (task_management_service.py:423) und den Web-Hintergrund
(app/web/background.py). Nach 16eca1e liest der Bot die Container aus
``DDC_CONFIG_DIR`` - diese Liste las weiter am alten Ort. Der Container-Spalt
war damit nicht ganz geschlossen; aufgefallen beim Lesen der naechsten
Fundstelle der Sperrklinke, nicht vorher.

WIE HIER GEPRUEFT WIRD: Die Container-Dateien legt der Test an, einen davon
inaktiv. Die geteilte Liste (Modulzustand) wird danach wiederhergestellt -
sonst faerbt dieser Test andere.
"""

import json

import pytest

from app.utils import shared_data


@pytest.fixture
def verzeichnis(tmp_path, monkeypatch):
    ziel = tmp_path / "eigene_konfig"
    (ziel / "containers").mkdir(parents=True)
    monkeypatch.setenv("DDC_CONFIG_DIR", str(ziel))
    vorher = shared_data.get_active_containers()
    try:
        yield ziel
    finally:
        shared_data.set_active_containers(vorher)


def test_die_aktiven_container_kommen_aus_dem_verzeichnis(verzeichnis):
    for name, aktiv in (("laeuft", True), ("ruht", False)):
        (verzeichnis / "containers" / f"{name}.json").write_text(
            json.dumps({"container_name": name, "active": aktiv}), encoding="utf-8")

    assert shared_data.load_active_containers_from_config() == ["laeuft"], (
        "Die aktiven Container fuer das Web-Panel kommen nicht aus DDC_CONFIG_DIR."
    )
    assert shared_data.get_active_containers() == ["laeuft"]
