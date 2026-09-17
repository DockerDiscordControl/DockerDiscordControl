# -*- coding: utf-8 -*-
"""Der Zuschnitt aus Stufe 4 deckt den Anwendungscode lueckenlos ab.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

WORUM ES GEHT: Stufe 4 verlangt eine Durchsicht mit nachweisbarer Abdeckung.
Dafuer ist der Anwendungscode in ``docs/quality/ABSCHNITTE.txt`` in Abschnitte
von hoechstens 2000 Zeilen zerlegt. Der Nachweis ist nur so viel wert wie die
Zusicherung, dass diese Liste den Baum WIRKLICH vollstaendig abdeckt - sonst
wird ein Abschnitt uebersehen und niemand merkt es.

DIE FALLE, DIE HIER VERMIEDEN WIRD: Erwartung und Behauptung duerfen nicht aus
derselben Quelle kommen. Die **Behauptung** ist ABSCHNITTE.txt. Die
**Erwartung** ist der Baum selbst - alle ``.py`` unter cogs/, services/, app/,
utils/ mit ihrer echten Zeilenzahl. Zoege man beides aus der Abschnittsdatei,
waere das ein Spiegeltest; genau so einer ist mir heute beim Verdrahtungstest
unterlaufen und blieb bei entferntem CSRF-Schutz gruen.

GEGENPROBE (durchgefuehrt 2026-09-17): Dieser Test ist von Anfang an gruen - die
Zusicherung gilt ja gerade. Sein Wert haengt deshalb vollstaendig daran, ob er
ueberhaupt beissen kann. Vier Mutationen an ABSCHNITTE.txt, jede einzeln::

    Datei aus der Liste entfernt        -> 1 failed
    Luecke gerissen (Bereich ab 5)      -> 1 failed
    Abdeckung endet vor dem Dateiende   -> 1 failed
    Abschnitt kuenstlich ueber 2000 Z.  -> 2 failed

Die vierte macht zwei Tests rot, weil ein aufgeblaehter Bereich zugleich die
Abdeckung verfaelscht. Wiederhergestellt: 3 gruen, Datei bitgleich zur Sicherung.

Ohne diese Probe waere er ein Test, der nicht fehlschlagen kann - genau die
Gattung, die Stufe 3 aussiebt. Beim Verdrahtungstest (test_app_factory_
verdrahtung.py) war die erste Fassung tatsaechlich so einer: Sie zog Erwartung
UND Behauptung aus derselben Datei und blieb bei entferntem CSRF-Schutz gruen.

STAND DES ZUSCHNITTS: 37 Abschnitte, 188 Stuecke, 60.748 von 60.748 Zeilen in
183 Dateien. Vier Dateien liegen ueber 2000 Zeilen und mussten geteilt werden;
``DockerControlCog`` ist mit 4.485 Zeilen eine EINZIGE Klasse und laesst sich nur
an Methodengrenzen schneiden - ein eigener struktureller Befund, festgehalten im
Stufe-4-Bericht.
"""

import re
from collections import defaultdict
from pathlib import Path

import pytest

PROJEKT = Path(__file__).resolve().parents[2]
ABSCHNITTE = PROJEKT / "docs" / "quality" / "ABSCHNITTE.txt"
VERZEICHNISSE = ("cogs", "services", "app", "utils")
GRENZE = 2000

ZEILE = re.compile(r"^(?P<pfad>[^:#]+\.py):(?P<von>\d+)-(?P<bis>\d+)\s*$")


def _behauptung():
    """Was ABSCHNITTE.txt behauptet: {pfad: [(von, bis), ...]}, plus Abschnittsgroessen."""
    stuecke = defaultdict(list)
    groessen, aktuell = [], 0
    for zeile in ABSCHNITTE.read_text(encoding="utf-8").splitlines():
        if zeile.startswith("## Abschnitt"):
            if aktuell:
                groessen.append(aktuell)
            aktuell = 0
            continue
        treffer = ZEILE.match(zeile)
        if not treffer:
            continue
        von, bis = int(treffer["von"]), int(treffer["bis"])
        stuecke[treffer["pfad"]].append((von, bis))
        aktuell += bis - von + 1
    if aktuell:
        groessen.append(aktuell)
    return dict(stuecke), groessen


def _erwartung():
    """Was der Baum hergibt: {pfad: zeilenzahl}. Unabhaengig von der Abschnittsdatei."""
    baum = {}
    for verzeichnis in VERZEICHNISSE:
        for pfad in sorted((PROJEKT / verzeichnis).rglob("*.py")):
            rel = str(pfad.relative_to(PROJEKT))
            baum[rel] = len(pfad.read_text(encoding="utf-8", errors="replace").splitlines())
    return baum


def test_beide_seiten_sind_gefuellt():
    """Sicherung gegen ein stumpfes Werkzeug.

    Liest eine der beiden Seiten ins Leere - falscher Pfad, geaendertes Format -,
    waeren die Tests unten gruen, ohne etwas zu belegen.
    """
    assert ABSCHNITTE.is_file(), f"{ABSCHNITTE} fehlt"
    stuecke, groessen = _behauptung()
    baum = _erwartung()
    assert len(groessen) > 20, f"Nur {len(groessen)} Abschnitte gelesen - Format geaendert?"
    assert len(stuecke) > 100, f"Nur {len(stuecke)} Dateien in der Liste - Format geaendert?"
    assert len(baum) > 100, f"Nur {len(baum)} Dateien im Baum gefunden - Pfad falsch?"


def test_kein_abschnitt_ist_zu_gross():
    """Hoechstens 2000 Zeilen - sonst ist er nicht am Stueck lesbar."""
    _, groessen = _behauptung()
    zu_gross = [(i + 1, g) for i, g in enumerate(groessen) if g > GRENZE]
    assert not zu_gross, f"Abschnitte ueber {GRENZE} Zeilen: {zu_gross}"


def test_jede_quelldatei_liegt_in_genau_einem_abschnitt():
    """Lueckenlos und ueberschneidungsfrei - gegen den BAUM geprueft."""
    stuecke, _ = _behauptung()
    baum = _erwartung()

    fehlend = sorted(set(baum) - set(stuecke))
    assert not fehlend, (
        f"{len(fehlend)} Quelldateien stehen in KEINEM Abschnitt und wuerden bei "
        f"der Durchsicht uebersehen:\n  " + "\n  ".join(fehlend[:20])
    )

    ueberzaehlig = sorted(set(stuecke) - set(baum))
    assert not ueberzaehlig, (
        "Die Abschnittsliste nennt Dateien, die es nicht gibt - dort wuerde eine "
        f"Durchsicht ins Leere laufen:\n  " + "\n  ".join(ueberzaehlig[:20])
    )

    maengel = []
    for pfad, zeilenzahl in sorted(baum.items()):
        bereiche = sorted(stuecke[pfad])
        # lueckenlos von 1 bis zum Dateiende, ohne Ueberschneidung
        erwartet = 1
        for von, bis in bereiche:
            if von != erwartet:
                maengel.append(
                    f"{pfad}: {'Luecke' if von > erwartet else 'Ueberschneidung'} "
                    f"bei Zeile {erwartet} (naechstes Stueck beginnt {von})"
                )
                break
            erwartet = bis + 1
        else:
            if erwartet - 1 != zeilenzahl:
                maengel.append(
                    f"{pfad}: Abdeckung endet bei {erwartet - 1}, Datei hat {zeilenzahl} Zeilen"
                )
    assert not maengel, (
        f"{len(maengel)} Dateien sind nicht lueckenlos abgedeckt:\n  "
        + "\n  ".join(maengel[:20])
    )
