# -*- coding: utf-8 -*-
"""R2 - Zu jeder Zusicherung existiert mindestens ein Test.

Dieser Test deckt keine einzelne Zusicherung ab, sondern die Programmregel R2 aus
SPEC.md: keine Zusicherung darf ohne Markierung bleiben. Der Prompt nennt ihn
ausdruecklich - "ein weiterer Test kann pruefen, dass zu jeder Zusicherung
mindestens eine solche Markierung existiert".

Warum das noetig ist, und zwar belegt: Der Zustand "drei Zusicherungen haben
keinen Test" ist heute nur aufgefallen, weil beim Nachzaehlen zufaellig ein Grep
lief. Genau dieses Muster - etwas steht in keiner Liste, also sieht es niemand an -
ist die zentrale Warnung aus Stufe 4 des Programms, und es ist in dieser Sitzung
dreimal eingetreten (18 vergessene Testdateien, eine abgeschnittene Suchliste,
und eben diese Luecke).

Die Markierung muss eine eigenstaendige Kommentarzeile sein, also
``# at-deckt Z<Nummer>`` am Zeilenanfang. Fliesstext in einem Docstring zaehlt
NICHT mit - sonst haette dieser Test sich selbst als Abdeckung gezaehlt, und
genau das ist dem urspruenglichen Grep passiert.

Dieser Test ist bei seiner Entstehung ROT, und das ist sein Zweck: er benennt die
Luecke, statt sie zu verschweigen. Gruen wird er erst, wenn Z6, Z9 und Z10 Tests
haben.
"""

import re
from pathlib import Path

import pytest

PROJEKT = Path(__file__).resolve().parents[2]
SPEC = PROJEKT / "SPEC.md"
TESTS = PROJEKT / "tests"

# Eigenstaendige Kommentarzeile, Nummer zwingend. Ohne \d+ wuerde der Fliesstext
# dieses Docstrings als Treffer zaehlen.
MARKIERUNG = re.compile(r"^#\s*@deckt\s+Z(\d+)\s*$", re.MULTILINE)
UEBERSCHRIFT = re.compile(r"^###\s+Z(\d+)\s+—", re.MULTILINE)


def _zusicherungen() -> set[str]:
    """Alle Z-Nummern aus SPEC.md."""
    return {f"Z{n}" for n in UEBERSCHRIFT.findall(SPEC.read_text(encoding="utf-8"))}


def _markierungen() -> dict[str, list[str]]:
    """Z-Nummer -> Dateien, die sie markieren."""
    gefunden: dict[str, list[str]] = {}
    for datei in sorted(TESTS.rglob("test_*.py")):
        for nummer in MARKIERUNG.findall(datei.read_text(encoding="utf-8", errors="replace")):
            gefunden.setdefault(f"Z{nummer}", []).append(str(datei.relative_to(PROJEKT)))
    return gefunden


def test_spec_enthaelt_ueberhaupt_zusicherungen():
    """Sicherung gegen ein stumpfes Werkzeug.

    Findet das Muster keine Ueberschriften mehr - etwa weil jemand die
    Formatierung der SPEC aendert -, wuerden die beiden Tests unten leer
    durchlaufen und nichts mehr pruefen.
    """
    zusicherungen = _zusicherungen()
    assert len(zusicherungen) >= 8, (
        f"Nur {len(zusicherungen)} Zusicherungen in SPEC.md gefunden - vermutlich "
        f"passt das Suchmuster nicht mehr auf die Ueberschriften: {sorted(zusicherungen)}"
    )


def test_jede_zusicherung_hat_mindestens_einen_test():
    """Keine Zusicherung ohne Markierung."""
    zusicherungen = _zusicherungen()
    markiert = _markierungen()
    ohne = sorted(zusicherungen - markiert.keys(), key=lambda z: int(z[1:]))

    assert not ohne, (
        f"Ohne Test: {', '.join(ohne)}. Eine Zusicherung ohne Test ist eine "
        f"Absichtserklaerung - sie kann nicht gebrochen werden, weil niemand "
        f"nachsieht. Abgedeckt sind: "
        f"{', '.join(sorted(markiert, key=lambda z: int(z[1:])))}"
    )


def test_keine_markierung_zeigt_ins_leere():
    """Jede Markierung verweist auf eine Zusicherung, die es gibt.

    Faengt Tippfehler ab: ``@deckt Z11`` sieht nach Abdeckung aus, deckt aber
    nichts, wenn es keine Z11 gibt.
    """
    zusicherungen = _zusicherungen()
    markiert = _markierungen()
    verwaist = {z: dateien for z, dateien in markiert.items() if z not in zusicherungen}

    assert not verwaist, (
        f"Markierungen ohne passende Zusicherung in SPEC.md: {verwaist}"
    )
