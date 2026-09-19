# -*- coding: utf-8 -*-
"""Die Mech-Dateien muessen in ``DDC_CONFIG_DIR`` gesucht werden.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND. Sechs Mech-Stellen leiten ihre Dateien selbst her und beachten die
Variable nicht::

    EvolutionConfigService       mech/evolution.json      parents[2] / "config"
    get_evolution_level_info     mech/decay.json          parents[2] / "config"
    MechStoryService             mech/stories/            parents[2] / "config"
    speed_levels (beim Import)   mech/speed_translations  parents[2] / "config"
    MechStateManager             mech_state.json          RELATIV "config/..."
    progress_paths (Ausweichwert) progress/               RELATIV "config/progress"

MechStateManager legt seine Datei schon im Konstruktor an (Z2), und der
relative Pfad haengt vom Arbeitsverzeichnis ab. Bei progress_paths behalten
``DDC_PROGRESS_DATA_DIR`` und ``progress.data_dir`` aus der Konfiguration
Vorrang - nur der letzte Ausweichwert aendert sich, auf den Wert, den
docs/CONFIGURATION.md schon nennt ("/app/config/progress").

EIN EIGENER BEFUND, HIER NICHT BEHANDELT: evolution.json, decay.json, die
Geschichten und speed_translations.json liefert das Image NICHT mit und sie
waren nie im Repository (config/* steht in .gitignore). Auf dem Server des
Betreibers liegen sie (Stand 2025-11). Was eine Neuinstallation ohne sie zeigt,
ist eine Produktfrage und dem Betreiber vorgelegt.

WIE HIER GEPRUEFT WIRD: Die Dateien legt der Test im eingestellten Verzeichnis
an. ``speed_levels`` liest beim IMPORT - der Test laedt das Modul deshalb neu
und stellt es danach wieder her. progress_paths wird ueber ``_resolve_base_dir``
geprueft, am Zwischenspeicher vorbei - er bleibt unberuehrt.
"""

import importlib
import json

import pytest

from services.mech import mech_evolutions, progress_paths, speed_levels
from services.mech.mech_state_manager import MechStateManager
from services.mech.mech_story_service import MechStoryService


@pytest.fixture
def verzeichnis(tmp_path, monkeypatch):
    ziel = tmp_path / "eigene_konfig"
    (ziel / "mech").mkdir(parents=True)
    monkeypatch.setenv("DDC_CONFIG_DIR", str(ziel))
    return ziel


def test_evolution_json_liegt_im_verzeichnis(verzeichnis):
    assert mech_evolutions.EvolutionConfigService().config_path == verzeichnis / "mech" / "evolution.json"


def test_der_verfall_kommt_aus_dem_verzeichnis(verzeichnis):
    (verzeichnis / "mech" / "decay.json").write_text(
        json.dumps({"levels": {"3": 250}, "default": 100}), encoding="utf-8")

    info = mech_evolutions.get_evolution_level_info(3)

    assert info is not None
    assert info.decay_per_day == pytest.approx(2.5), (
        "decay.json aus DDC_CONFIG_DIR wurde nicht gelesen (250 Cent -> 2,50)."
    )


def test_die_geschichten_liegen_im_verzeichnis(verzeichnis):
    assert MechStoryService().story_dir == verzeichnis / "mech" / "stories"


def test_die_geschwindigkeits_uebersetzungen_kommen_aus_dem_verzeichnis(verzeichnis):
    inhalt = {"probe": {"de": "Probe"}}
    (verzeichnis / "mech" / "speed_translations.json").write_text(json.dumps(inhalt), encoding="utf-8")
    neu = importlib.reload(speed_levels)
    assert neu.SPEED_TRANSLATIONS == inhalt, (
        "speed_translations.json aus DDC_CONFIG_DIR wurde nicht gelesen."
    )


@pytest.fixture(autouse=True)
def _speed_levels_wiederherstellen():
    """Nach jedem Test neu laden - autouse wird zuerst auf- und zuletzt
    abgebaut, also NACHDEM monkeypatch die Umgebung zurueckgesetzt hat."""
    yield
    importlib.reload(speed_levels)


def test_der_mech_zustand_liegt_im_verzeichnis(verzeichnis):
    """Z2-Teil: Der Konstruktor legt die Datei an."""
    manager = MechStateManager()

    assert manager.state_file == str(verzeichnis / "mech_state.json")
    assert (verzeichnis / "mech_state.json").exists()


def test_fortschritt_faellt_auf_das_verzeichnis_zurueck(verzeichnis, monkeypatch):
    monkeypatch.delenv("DDC_PROGRESS_DATA_DIR", raising=False)
    monkeypatch.setattr(progress_paths, "_config_base_dir", lambda: None)

    assert progress_paths._resolve_base_dir() == verzeichnis / "progress"


def test_die_eigene_fortschritts_variable_behaelt_vorrang(verzeichnis, tmp_path, monkeypatch):
    """Abgrenzung."""
    eigenes = tmp_path / "nur_fortschritt"
    monkeypatch.setenv("DDC_PROGRESS_DATA_DIR", str(eigenes))

    assert progress_paths._resolve_base_dir() == eigenes
