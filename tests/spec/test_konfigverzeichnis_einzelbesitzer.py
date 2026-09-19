# -*- coding: utf-8 -*-
"""Fuenf Dienste mit je eigener Datei muessen ``DDC_CONFIG_DIR`` folgen.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND. Jeder dieser Dienste ist der einzige Leser/Schreiber seiner Datei
und leitet sie aus ``Path(__file__).parents[2] / "config"`` her::

    TranslationConfigService  channel_translations.json  (schreibt im Konstruktor)
    UpdateNotifier            update_status.json         (mkdir im Konstruktor)
    server_order              server_order.json          (Modulwert beim Import)
    load_custom_timeout_config container_timeouts.json   (nur lesend)
    SchedulerRuntime          tasks.json                  (Ausweichwert)

Folgen wie bei der Admin-Liste (8ac5427) und den Auto-Aktionen (71176fa):
Mit ``DDC_CONFIG_DIR`` auf dem Volume liegen Uebersetzungs-Kanaele,
Server-Reihenfolge und ZEITAUFTRAEGE ausserhalb davon und sind nach dem
Neuanlegen des Containers weg; eigene Zeitueberschreitungen werden nicht
gelesen. Und Z2: zwei Konstruktoren schreiben ins ECHTE config/.

ZWEI ABGRENZUNGEN, weil hier schon Umleitungen existieren:
1. ``DDC_SCHEDULER_CONFIG_DIR`` behaelt Vorrang vor ``DDC_CONFIG_DIR`` - nur
   der AUSWEICHWERT des Schedulers aendert sich.
2. ``server_order.ORDER_FILE`` bleibt ein setzbarer Modulwert - sieben
   vorhandene Tests leiten ihn per monkeypatch um. Ungesetzt (None) kommt der
   Pfad beim Aufruf aus der gemeinsamen Quelle.
"""

import json

import pytest

from services.docker_service import docker_utils
from services.docker_service import server_order
from services.infrastructure.update_notifier import UpdateNotifier
from services.scheduling.runtime import SchedulerRuntime
from services.translation.translation_config_service import TranslationConfigService


@pytest.fixture
def verzeichnis(tmp_path, monkeypatch):
    ziel = tmp_path / "eigene_konfig"
    ziel.mkdir()
    monkeypatch.setenv("DDC_CONFIG_DIR", str(ziel))
    monkeypatch.delenv("DDC_SCHEDULER_CONFIG_DIR", raising=False)
    return ziel


def test_uebersetzungs_kanaele_liegen_im_verzeichnis(verzeichnis):
    dienst = TranslationConfigService()
    assert dienst.config_file == verzeichnis / "channel_translations.json"
    assert dienst.config_file.exists(), "Die Vorgabedatei entstand nicht in DDC_CONFIG_DIR."


def test_update_status_liegt_im_verzeichnis(verzeichnis):
    assert UpdateNotifier().status_file == verzeichnis / "update_status.json"


def test_die_server_reihenfolge_wird_im_verzeichnis_gespeichert(verzeichnis, monkeypatch):
    monkeypatch.setattr(server_order, "ORDER_FILE", None, raising=False)

    assert server_order.save_server_order(["b", "a"]) is True

    datei = verzeichnis / "server_order.json"
    assert datei.exists(), "server_order.json entstand nicht in DDC_CONFIG_DIR."
    assert json.loads(datei.read_text(encoding="utf-8"))["server_order"] == ["b", "a"]
    assert server_order.load_server_order() == ["b", "a"]


def test_eigene_zeitueberschreitungen_kommen_aus_dem_verzeichnis(verzeichnis, monkeypatch):
    monkeypatch.setattr(docker_utils, "_custom_config_loaded", False)
    monkeypatch.setattr(docker_utils, "_custom_timeout_config", None)
    inhalt = {"container_overrides": {"probe": {"stats_timeout": 42.0}}}
    (verzeichnis / "container_timeouts.json").write_text(json.dumps(inhalt), encoding="utf-8")

    assert docker_utils.load_custom_timeout_config() == inhalt


def test_zeitauftraege_liegen_im_verzeichnis(verzeichnis):
    assert SchedulerRuntime().config_dir == verzeichnis


def test_die_eigene_scheduler_variable_behaelt_vorrang(verzeichnis, tmp_path, monkeypatch):
    """Abgrenzung 1."""
    eigenes = tmp_path / "nur_scheduler"
    monkeypatch.setenv("DDC_SCHEDULER_CONFIG_DIR", str(eigenes))
    assert SchedulerRuntime().config_dir == eigenes


def test_ein_gesetzter_order_file_gilt_weiter(verzeichnis, tmp_path, monkeypatch):
    """Abgrenzung 2: die Umleitung der vorhandenen Tests."""
    datei = tmp_path / "anderswo" / "reihenfolge.json"
    monkeypatch.setattr(server_order, "ORDER_FILE", datei)

    assert server_order.save_server_order(["x"]) is True
    assert datei.exists()
    assert not (verzeichnis / "server_order.json").exists()
