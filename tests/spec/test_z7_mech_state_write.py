# -*- coding: utf-8 -*-
# @deckt Z7
"""Z7, Stelle 4 von 5 - der Mech-Zustand.

``MechResetService.reset_mech_state`` (``services/mech/mech_reset_service.py:168``)
liest ``mech_state.json``, setzt Werte zurueck und schreibt sie mit einem
schlichten ``open(..., 'w')`` (:194) wieder hinaus. Ein Abbruch dazwischen laesst
die Datei leer zurueck.

Was dabei verloren geht, ist mehr als ein Zaehlerstand: Die Methode BEHAELT die
vorhandene Struktur und setzt nur Werte (:181-192). In der Datei stehen
``last_glvl_per_channel`` und ``mech_expanded_states`` - also welcher Discord-Kanal
welchen Mech-Stand hatte und welche Ansicht dort ausgeklappt war. Ein Absturz
vernichtet diese Zuordnung; danach weiss niemand mehr, welcher Kanal wohin gehoert.
Geprueft wird deshalb nicht bloss "Datei nicht leer", sondern dass die Zuordnung
erhalten bleibt.

ABFANGPUNKT: Die Methode liest die Datei ZUERST (:175-177). Ein Abfang, der bei
jedem ``open`` wirft, scheitert daher schon am Lesen, die Methode meldet ``False``,
und der Schreibpfad wird nie erreicht - der Test waere gruen, ohne etwas zu
beweisen. Genau das ist ``tests/unit/extended/test_docker_infra_gaps.py`` passiert
und kostete dort zwei Reparaturversuche. Hier scheitern deshalb nur
Schreibzugriffe.

Vorhandene Tests (25 Beruehrungspunkte, vollstaendig geprueft): Alle arbeiten mit
echten Dateien in ``tmp_path`` und fangen nichts ab. Keiner wird durch die
Umstellung auf ``atomic_write_json`` stumpf - anders als bei
``_deactivate_container``, wo einer mitgezogen werden musste. Es gibt hier nichts
nachzuziehen.

GEGENPROBE (durchgefuehrt 2026-09-16) - beim ERSTEN Anlauf getroffen::

    assert ''   # Der Mech-Zustand ist leer

Der Waechter ``getroffen`` schlug nicht an (der Abfang griff also), und
``ergebnis.success is False`` hielt (die Ausnahme wird wie erwartet behandelt).
Beide Fehlermoeglichkeiten, die vorher benannt worden waren, sind nicht
eingetreten.

Dass es diesmal auf Anhieb klappte, ist kein Glueck: Die zwei Fallen, die in den
vorigen Z7-Durchgaengen je zwei Anlaeufe kosteten, waren vorher benannt - der
Abfangpunkt muss HINTER der Kuerzung liegen, und er darf NUR Schreibzugriffe
treffen, weil die Methode vorher liest.

Nach der Korrektur auf ``atomic_write_json``: 3 gruen,
``tests/unit/services/mech`` unveraendert 447 gruen.

WIRKUNGSNACHWEIS per Mutation: mit einem ``atomic_write_text``, das alle Fehler
verschluckt, wird dieser Test rot; wiederhergestellt wieder gruen.

Geprueft und fuer unbedenklich befunden: ``mech_reset_service.py:302`` greift
ebenfalls auf ``mech_state_file`` zu, aber nur lesend (``'r'``) in
``get_current_status``. Kein Z7-Fall.
"""

import json
import os

import pytest

from services.mech.mech_reset_service import MechResetService

URSPRUNG = {
    "last_glvl_per_channel": {"111": 7, "222": 3},
    "mech_expanded_states": {"111": True},
    "last_update": "2026-01-01T00:00:00",
}


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
                fh = echtes_open(datei, modus, *a, **kw)  # kuerzt
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
def dienst(tmp_path):
    """Reset-Dienst mit einem gefuellten Mech-Zustand in eigener Ablage."""
    datei = tmp_path / "mech_state.json"
    datei.write_text(json.dumps(URSPRUNG, indent=2), encoding="utf-8")
    return MechResetService(config_dir=str(tmp_path)), datei


def test_abgebrochener_schreibvorgang_laesst_den_zustand_unversehrt(dienst, monkeypatch):
    """Scheitert das Schreiben, steht die Kanalzuordnung noch vollstaendig da."""
    service, datei = dienst
    fehler = _NurSchreibenScheitert(monkeypatch)

    ergebnis = service.reset_mech_state()

    assert fehler.getroffen, (
        "Der Schreibfehler wurde gar nicht ausgeloest - dieser Test prueft dann "
        "nichts. Vermutlich wird ueber einen dritten Weg geschrieben."
    )
    assert ergebnis.success is False, "Ein gescheiterter Schreibvorgang darf nicht als Erfolg gelten"

    inhalt = datei.read_text(encoding="utf-8")
    assert inhalt.strip(), (
        "Der Mech-Zustand ist leer - mit ihm ist die Zuordnung verloren, welcher "
        "Discord-Kanal welchen Stand hatte"
    )
    danach = json.loads(inhalt)
    assert danach["last_glvl_per_channel"] == URSPRUNG["last_glvl_per_channel"], (
        f"Die Kanalzuordnung wurde beschaedigt: {danach!r}"
    )


def test_erfolgreicher_reset_setzt_zurueck_und_behaelt_die_kanaele(dienst):
    """Die Gegenrichtung: ohne Fehler wird korrekt zurueckgesetzt.

    Ohne diesen Fall koennte man die Methode auf "schreibt nie" verschaerfen und
    der Test oben bliebe gruen.
    """
    service, datei = dienst

    ergebnis = service.reset_mech_state()

    assert ergebnis.success is True
    danach = json.loads(datei.read_text(encoding="utf-8"))
    assert danach["last_glvl_per_channel"] == {"111": 1, "222": 1}, "Stufen nicht zurueckgesetzt"
    assert danach["mech_expanded_states"] == {"111": False}, "Ansicht nicht eingeklappt"


def test_keine_temp_reste_nach_erfolg(dienst):
    """Eine atomare Umsetzung raeumt ihre Temp-Datei auf.

    Bestand vorher gegen nachher - nicht "alles ausser der Zieldatei". Die
    naive Fassung dieser Pruefung war beim Mitgliederzahl-Test aus dem falschen
    Grund rot, weil in jener Ablage weitere regulaere Dateien liegen.
    """
    service, datei = dienst
    vorher = {p.name for p in datei.parent.iterdir() if p.is_file()}

    service.reset_mech_state()

    nachher = {p.name for p in datei.parent.iterdir() if p.is_file()}
    assert sorted(nachher - vorher) == [], f"Temp-Reste geblieben: {sorted(nachher - vorher)}"
