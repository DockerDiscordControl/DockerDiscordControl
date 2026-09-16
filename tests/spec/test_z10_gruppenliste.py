# -*- coding: utf-8 -*-
# @deckt Z10
"""Z10, zweiter Teil - die Gruppenliste darf nicht wegdriften.

Das CI-Gatter laeuft ``tests/GROUPS.txt`` Zeile fuer Zeile ab, weil mehrere
Gruppen in einem gemeinsamen pytest-Lauf die Sammlung zerlegen (Begruendung
steht in der Datei selbst). Damit haengt die Frage "wird ueberhaupt alles
getestet?" an einer von Hand gepflegten Liste.

Genau das ist die Gefahr: Kommt ein Testverzeichnis dazu und traegt es niemand
ein, laeuft es **lautlos nie mit**. Nichts wird rot, nichts fehlt sichtbar - die
CI meldet weiterhin Erfolg, und der ungeprueften Teil waechst still. Das ist
dieselbe Bauart wie der Befund, der dieses Gatter ueberhaupt ausgeloest hat: ein
Testschritt, der Erfolg meldete, ohne zu testen.

Geprueft wird deshalb beides:

1. Jede Testdatei liegt in **genau einer** Gruppe. Keine ohne (liefe nie mit),
   keine in zweien (liefe doppelt und verlaengerte das Gatter grundlos).
2. Jeder Eintrag der Liste existiert auch. Ein Tippfehler wie ``tests/unit/cogss``
   laesst pytest mit Code 4 abbrechen - laut zwar, aber der Fehler gehoert hierher
   gemeldet, wo er die Ursache nennt, statt in einen CI-Lauf.

GEGENPROBE (durchgefuehrt 2026-09-17): beim ersten Lauf gruen - was diesen Test
verdaechtig macht, denn ein Vertragstest, der sofort haelt, koennte auch ins
Leere lesen. Dagegen steht ``test_die_liste_und_der_baum_sind_nicht_leer``: Er
belegt, dass beide Sammlungen gefuellt sind (>30 Gruppen, >50 Dateien), bevor
die Zuordnung geprueft wird.

Eine offene Frage war dabei echt: ``tests/load/`` hat ein ``__init__.py``, steht
aber nicht in GROUPS.txt. Der Test blieb gruen - das Verzeichnis enthaelt keine
Dateien, die pytest einsammeln wuerde. Haette es welche, waere genau das der
erste Fang gewesen.
"""

from pathlib import Path

import pytest

PROJEKT = Path(__file__).resolve().parents[2]
TESTS = PROJEKT / "tests"
LISTE = TESTS / "GROUPS.txt"


def _gruppen():
    """Die Eintraege aus GROUPS.txt, ohne Kommentare und Leerzeilen."""
    zeilen = LISTE.read_text(encoding="utf-8").splitlines()
    return [z.strip() for z in zeilen if z.strip() and not z.strip().startswith("#")]


def _testdateien():
    """Alle Dateien, die pytest als Test einsammeln wuerde."""
    return sorted(set(TESTS.rglob("test_*.py")) | set(TESTS.rglob("*_test.py")))


def test_die_liste_und_der_baum_sind_nicht_leer():
    """Sicherung gegen ein stumpfes Werkzeug.

    Liest eine der beiden Sammlungen ins Leere - weil die Datei umbenannt wurde
    oder das Suchmuster nicht mehr passt -, waeren die Tests unten gruen, ohne
    irgendetwas zu belegen.
    """
    assert LISTE.is_file(), f"{LISTE} fehlt - die Tests unten pruefen dann nichts"
    gruppen, dateien = _gruppen(), _testdateien()
    assert len(gruppen) > 30, f"Nur {len(gruppen)} Gruppen gelesen - vermutlich Leseproblem"
    assert len(dateien) > 50, f"Nur {len(dateien)} Testdateien gefunden - vermutlich Leseproblem"


def test_jeder_eintrag_der_liste_existiert():
    """Ein Tippfehler in der Liste laesst eine ganze Gruppe ausfallen."""
    fehlend = [g for g in _gruppen() if not (PROJEKT / g).exists()]
    assert not fehlend, (
        "Eintraege in tests/GROUPS.txt, die es nicht gibt: " + ", ".join(fehlend)
    )


def test_jede_testdatei_liegt_in_genau_einer_gruppe():
    """Keine Datei ohne Gruppe, keine in zweien."""
    gruppen = [(g, PROJEKT / g) for g in _gruppen()]

    ohne, doppelt = [], []
    for datei in _testdateien():
        treffer = [
            name for name, pfad in gruppen
            if datei == pfad or (pfad.is_dir() and pfad in datei.parents)
        ]
        rel = datei.relative_to(PROJEKT)
        if not treffer:
            ohne.append(str(rel))
        elif len(treffer) > 1:
            doppelt.append(f"{rel} -> {treffer}")

    assert not ohne, (
        "Testdateien, die in KEINER Gruppe liegen - sie laufen in der CI nie mit, "
        "ohne dass irgendetwas rot wird:\n  " + "\n  ".join(ohne)
    )
    assert not doppelt, (
        "Testdateien, die in MEHREREN Gruppen liegen - sie laufen doppelt und "
        "verlaengern das Gatter grundlos:\n  " + "\n  ".join(doppelt)
    )
