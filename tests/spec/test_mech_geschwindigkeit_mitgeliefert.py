# -*- coding: utf-8 -*-
"""Die uebersetzten Geschwindigkeitsstufen muessen auf jeder Installation da sein.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers. Entschieden ist die Arbeit: "Mitliefern".

DER BEFUND. ``config/mech/speed_translations.json`` lag nur auf dem Server des
Betreibers. Ohne sie liefert ``get_translated_speed_description`` fuer jede
Sprache den englischen Text. Sichtbar wird das dort, wo eine Sprache
mitgegeben wird: in der privaten Detailansicht
(mech_status_details_service.py:117) und in mech_data_store.py:609.

WAS HIER BEWUSST NICHT MITKOMMT, gemessen: ``evolution.json``. Ihre
Stufendaten sind feldgleich mit dem fest verdrahteten Ausweichwert (0
Abweichungen), die Community-Stufen liest nur ``calculate_dynamic_cost`` -
und das hat keinen Aufrufer -, und die Schwierigkeitseinstellung ist die
persoenliche des Betreibers. Mitliefern haette keine Wirkung gehabt.
Die Unendlichkeits-Meldung hat im Code denselben Ausweichtext.

WIE HIER GEPRUEFT WIRD: ``speed_levels`` liest beim IMPORT - neu laden gegen ein
leeres Konfigurationsverzeichnis, danach wiederherstellen.
"""

import importlib
import json

import pytest

from services.mech import speed_levels


@pytest.fixture(autouse=True)
def _wiederherstellen():
    yield
    importlib.reload(speed_levels)


@pytest.fixture
def neuinstallation(tmp_path, monkeypatch):
    ziel = tmp_path / "leere_konfig"
    ziel.mkdir()
    monkeypatch.setenv("DDC_CONFIG_DIR", str(ziel))
    return ziel


def test_deutsch_auf_einer_neuinstallation(neuinstallation):
    modul = importlib.reload(speed_levels)
    assert modul.get_translated_speed_description(5, "de") == "Todmüde schleppend", (
        "Auf einer Neuinstallation gibt es keine uebersetzten Geschwindigkeitsstufen."
    )


def test_englisch_bleibt_englisch(neuinstallation):
    """Waechter: der englische Text ist in Datei und Ausweichwert gleich."""
    modul = importlib.reload(speed_levels)
    assert modul.get_translated_speed_description(5, "en") == "Excruciatingly lethargic"


def test_die_eigene_datei_gewinnt(neuinstallation):
    (neuinstallation / "mech").mkdir()
    (neuinstallation / "mech" / "speed_translations.json").write_text(json.dumps(
        {"speed_descriptions": {"5": {"de": "Eigen"}}}), encoding="utf-8")

    modul = importlib.reload(speed_levels)
    assert modul.get_translated_speed_description(5, "de") == "Eigen"
