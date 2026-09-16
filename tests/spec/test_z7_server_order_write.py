# -*- coding: utf-8 -*-
# @deckt Z7
"""Z7, Stelle 5 von 5 - die Serverreihenfolge.

``save_server_order`` (``services/docker_service/server_order.py:30``) schreibt
die Datei mit einem schlichten ``open(ORDER_FILE, 'w')`` (:45). Ein Abbruch
mitten darin laesst sie leer zurueck.

Warum das trotz "kosmetisch" hierher gehoert: Der Verlust ist **unsichtbar**.
``load_server_order`` (:54) faengt ``json.JSONDecodeError`` ab und gibt bei einer
kaputten Datei stillschweigend ``[]`` zurueck (:72-74). Es gibt keine Fehlermeldung
und keinen Hinweis - die Reihenfolge, die der Nutzer im Panel per Hand gelegt hat,
ist danach einfach die Standardreihenfolge. "Unbemerkt schlaegt selten": Der
Schaden ist klein, aber er meldet sich nie.

Geprueft wird deshalb nicht "die Datei hat Bytes", sondern die nutzerseitige
Aussage: ``load_server_order()`` liefert nach dem gescheiterten Schreibvorgang
noch die alte Reihenfolge.

Ausgeloest wird der Schreibvorgang an zwei Stellen, beide ohne Zutun des Nutzers
im Moment des Schreibens: ``cogs/docker_control.py:242`` (beim Aufbau der
Serverliste) und ``services/web/configuration_save_service.py:246`` (beim
Speichern der Konfiguration).

ABFANGPUNKT: Anders als bei ``_deactivate_container`` und ``reset_mech_state``
liest diese Funktion vorher NICHT. Ein Abfang auf jedem ``open`` waere hier also
nicht aus dem falschen Grund gruen. Er bleibt trotzdem auf Schreibzugriffe
beschraenkt - erstens, weil die Fassung nach der Korrektur ueber ``os.fdopen``
schreibt, zweitens, weil der zweite Test in dieser Datei liest.

Vorhandene Tests (vollstaendig geprueft, ``tests/unit/extended/test_coverage_push_v3.py:138-225``,
7 Stueck): Alle leiten ``ORDER_FILE`` per ``monkeypatch`` in ``tmp_path`` um und
arbeiten mit echten Dateien. Einer patcht ``os.makedirs`` (:182), das vor dem
Schreiben steht und von der Umstellung unberuehrt bleibt. Keiner faengt den
Schreibvorgang selbst ab, keiner wird durch ``atomic_write_json`` stumpf. Es gibt
nichts nachzuziehen - anders als bei ``_deactivate_container``, wo ein Test
mitgezogen werden musste.

GEGENPROBE: ausstehend - wird nach dem Messen eingetragen, nicht vorher.
"""

import json
import os

import pytest

from services.docker_service import server_order as so

URSPRUNG = ["nginx", "plex", "redis", "sonarr"]


class _NurSchreibenScheitert:
    """Laesst Lesen zu, laesst jeden Schreibvorgang scheitern.

    Faengt ``builtins.open`` und ``os.fdopen`` ab, aber nur fuer Schreibmodi -
    die heutige Fassung schreibt ueber ``open(..., 'w')``, eine atomare ueber
    ``mkstemp`` + ``os.fdopen``. Der Schaden wird dabei NACHGESTELLT und nicht
    verhindert: Die Datei wird geoeffnet (und damit gekuerzt), bevor der Fehler
    kommt. Wirft man vorher, ueberlebt der alte Inhalt und der Test beweist
    nichts - dieser Fehler ist beim Mitgliederzahl-Test zweimal passiert.
    """

    def __init__(self, monkeypatch):
        self.getroffen = False
        echtes_open, echtes_fdopen = open, os.fdopen

        def _wirft(*_a, **_k):
            raise OSError("kein Platz auf dem Geraet")

        def _open(datei, modus="r", *a, **kw):
            if "w" in modus or "a" in modus:
                self.getroffen = True
                fh = echtes_open(datei, modus, *a, **kw)  # kuerzt beim Oeffnen
                fh.write = _wirft
                return fh
            return echtes_open(datei, modus, *a, **kw)

        def _fdopen(fd, modus="r", *a, **kw):
            fh = echtes_fdopen(fd, modus, *a, **kw)
            if "w" in modus or "a" in modus:
                self.getroffen = True
                fh.write = _wirft
            return fh

        monkeypatch.setattr("builtins.open", _open)
        monkeypatch.setattr(os, "fdopen", _fdopen)


@pytest.fixture
def ablage(tmp_path, monkeypatch):
    """Serverreihenfolge-Datei mit gelegter Reihenfolge in eigener Ablage.

    ``ORDER_FILE`` ist ein Modulwert; dieselbe Umleitung nutzen die sieben
    vorhandenen Tests in ``test_coverage_push_v3.py``.
    """
    datei = tmp_path / "server_order.json"
    datei.write_text(json.dumps({"server_order": URSPRUNG}, indent=2), encoding="utf-8")
    monkeypatch.setattr(so, "ORDER_FILE", datei)
    return datei


def test_abgebrochener_schreibvorgang_laesst_die_reihenfolge_stehen(ablage, monkeypatch):
    """Scheitert das Schreiben, liefert das Laden noch die alte Reihenfolge."""
    fehler = _NurSchreibenScheitert(monkeypatch)

    ergebnis = so.save_server_order(["ganz", "andere", "reihenfolge"])

    assert fehler.getroffen, (
        "Der Schreibfehler wurde gar nicht ausgeloest - dieser Test prueft dann "
        "nichts. Vermutlich wird ueber einen dritten Weg geschrieben."
    )
    assert ergebnis is False, "Ein gescheiterter Schreibvorgang darf nicht als Erfolg gelten"

    assert so.load_server_order() == URSPRUNG, (
        "Die vom Nutzer gelegte Serverreihenfolge ist weg. Sie meldet sich nicht: "
        "load_server_order faengt den JSON-Fehler ab und gibt stillschweigend [] "
        "zurueck, die Anzeige faellt kommentarlos auf die Standardreihenfolge"
    )


def test_erfolgreiches_speichern_ersetzt_die_reihenfolge(ablage):
    """Die Gegenrichtung: ohne Fehler wird korrekt geschrieben.

    Ohne diesen Fall koennte man ``save_server_order`` auf "schreibt nie"
    verschaerfen und der Test oben bliebe gruen.
    """
    neu = ["redis", "nginx"]

    assert so.save_server_order(neu) is True

    assert json.loads(ablage.read_text(encoding="utf-8")) == {"server_order": neu}
    assert so.load_server_order() == neu


def test_keine_temp_reste_nach_erfolg(ablage):
    """Eine atomare Umsetzung raeumt ihre Temp-Datei auf.

    Bestand vorher gegen nachher - nicht "alles ausser der Zieldatei". Die
    naive Fassung dieser Pruefung war beim Mitgliederzahl-Test aus dem falschen
    Grund rot, weil in jener Ablage weitere regulaere Dateien liegen.
    """
    vorher = {p.name for p in ablage.parent.iterdir() if p.is_file()}

    so.save_server_order(["redis", "nginx"])

    nachher = {p.name for p in ablage.parent.iterdir() if p.is_file()}
    assert sorted(nachher - vorher) == [], f"Temp-Reste geblieben: {sorted(nachher - vorher)}"
