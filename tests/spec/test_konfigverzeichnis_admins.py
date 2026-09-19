# -*- coding: utf-8 -*-
"""Die Admin-Liste muss im Verzeichnis aus ``DDC_CONFIG_DIR`` liegen.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND. ``AdminService`` leitet ``admins.json`` an drei Stellen selbst her
(``Path(__file__).parents[2] / 'config'``, admin_service.py:45/156/195) und
beachtet die Variable nicht. Anders als bei den Containern gibt es hier keinen
zweiten Leser - der Dienst ist mit sich einig. Die Folge ist eine andere:

1. Wer ``DDC_CONFIG_DIR`` auf sein Volume zeigt (so beschreibt es
   docs/CONFIGURATION.md), hat die Admin-Liste AUSSERHALB davon. Beim Neuanlegen
   des Containers ist sie weg - und mit ihr jede Admin-Berechtigung.
2. Z2: Im Testlauf (conftest setzt die Variable) schreibt ``save_admin_data``
   ins ECHTE config/.

WIE HIER GEPRUEFT WIRD: Schreiben, Lesen und Rechtepruefung laufen gegen ein
frisches Verzeichnis. Fuer das Lesen legt der TEST die Datei an - sonst bewiese
ein gruener Lesetest nur, dass Schreiben und Lesen denselben falschen Ort
benutzen.
"""

import json

import pytest

from services.admin.admin_service import AdminService


@pytest.fixture
def verzeichnis(tmp_path, monkeypatch):
    ziel = tmp_path / "eigene_konfig"
    ziel.mkdir()
    monkeypatch.setenv("DDC_CONFIG_DIR", str(ziel))
    return ziel


def _lege_an(verzeichnis, nutzer):
    (verzeichnis / "admins.json").write_text(
        json.dumps({"discord_admin_users": nutzer, "admin_notes": {}}), encoding="utf-8")


def test_gespeichert_wird_ins_verzeichnis(verzeichnis):
    """DER BEFUND, erste Folge: Die Liste landet ausserhalb des Volumes."""
    assert AdminService().save_admin_data(["111"], {"111": "Probe"}) is True

    datei = verzeichnis / "admins.json"
    assert datei.exists(), "admins.json wurde nicht in DDC_CONFIG_DIR geschrieben."
    assert json.loads(datei.read_text(encoding="utf-8"))["discord_admin_users"] == ["111"]


def test_die_admindaten_kommen_aus_dem_verzeichnis(verzeichnis):
    _lege_an(verzeichnis, ["222"])

    assert AdminService().get_admin_data()["discord_admin_users"] == ["222"]


def test_die_rechtepruefung_liest_das_verzeichnis(verzeichnis):
    """Der Weg, der Berechtigungen entscheidet (_load_admin_users)."""
    _lege_an(verzeichnis, ["333"])

    assert AdminService()._load_admin_users() == ["333"]
