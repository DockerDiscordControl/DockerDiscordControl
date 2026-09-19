# -*- coding: utf-8 -*-
"""Der Mech-Verfall muss auch ohne eigene ``decay.json`` stimmen.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers. Entschieden ist die Arbeit: "Mitliefern".

DER BEFUND. ``config/mech/decay.json`` liefert das Image nicht mit, und sie war
nie im Repository (``config/*`` in .gitignore) - sie lag nur auf dem Server des
Betreibers. Ohne sie nimmt ``progress_service.decay_per_day`` fuer JEDE Stufe
100 Cent pro Tag - auch fuer Stufe 11 (OMEGA), die laut Datei UND laut
Code-Kommentar in mech_evolutions.py ("IMMORTAL!") nicht verfallen soll. Die
Stufen 4-10 verfallen laut Datei staerker (120 bis 200 Cent).

DIE KORREKTUR: Die Datei wird als schreibgeschuetzte Vorgabe mitgeliefert
(``services/mech/defaults/decay.json``, byteweise vom Server des Betreibers
uebernommen, Pruefsumme verglichen). ``<Konfigverzeichnis>/mech/decay.json``
bleibt eine Ueberschreibung und gewinnt, wenn sie existiert.

WIE HIER GEPRUEFT WIRD: ``DDC_CONFIG_DIR`` zeigt auf ein LEERES Verzeichnis -
genau die Lage einer Neuinstallation. Der Zwischenspeicher von
``get_decay_config_data`` (10 s) wird vorher und nachher geleert.
"""

import json

import pytest

from services.mech import mech_evolutions, progress_service


@pytest.fixture
def neuinstallation(tmp_path, monkeypatch):
    ziel = tmp_path / "leere_konfig"
    ziel.mkdir()
    monkeypatch.setenv("DDC_CONFIG_DIR", str(ziel))
    progress_service._decay_config_cache.update({"data": None, "last_load": 0})
    try:
        yield ziel
    finally:
        progress_service._decay_config_cache.update({"data": None, "last_load": 0})


def test_omega_verfaellt_nicht(neuinstallation):
    """DER BEFUND, schaerfste Form."""
    assert progress_service.decay_per_day(11) == 0, (
        "Auf einer Neuinstallation verfaellt OMEGA (Stufe 11) - ohne decay.json "
        "gilt fuer jede Stufe die Vorgabe 100 Cent."
    )


@pytest.mark.parametrize("stufe,cent", [(1, 100), (4, 120), (6, 150), (8, 180), (10, 200)])
def test_die_stufen_verfallen_wie_vorgesehen(neuinstallation, stufe, cent):
    assert progress_service.decay_per_day(stufe) == cent


def test_die_stufenauskunft_nennt_denselben_verfall(neuinstallation):
    """Zweiter Leser: get_evolution_level_info rechnet in Dollar."""
    assert mech_evolutions.get_evolution_level_info(10).decay_per_day == pytest.approx(2.0)


def test_eine_eigene_datei_gewinnt(neuinstallation):
    """Abgrenzung: Die Ueberschreibung des Betreibers bleibt wirksam."""
    (neuinstallation / "mech").mkdir()
    (neuinstallation / "mech" / "decay.json").write_text(
        json.dumps({"default": 100, "levels": {"11": 5}}), encoding="utf-8")

    assert progress_service.decay_per_day(11) == 5
