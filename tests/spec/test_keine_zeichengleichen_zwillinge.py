# -*- coding: utf-8 -*-
"""Dieselbe Funktion darf nicht zweimal zeichengleich dastehen.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND (Stufe 2, Punkt 3 - dieselbe Regel an zwei Stellen). Die
Bestandsaufnahme nennt 27 Faelle doppelter Logik; dieser Test deckt die
haerteste und zugleich am eindeutigsten pruefbare Teilmenge ab: Funktionen, die
Zeichen fuer Zeichen identisch an zwei Orten stehen.

    _validate_custom_address   control_ui.py:1177  /  status_info_integration.py:1016
    _get_container_logs        status_info_integration.py:608  /  :779

Warum das mehr ist als Stil: Eine Sicherheitspruefung, die zweimal dasteht, wird
einmal korrigiert. ``_validate_custom_address`` prueft Adressen "for security" -
faellt die Pruefung in einer der beiden Kopien strenger aus, gilt fuer denselben
Container je nach Weg eine andere Regel. Genau diese Bauart hatte heute schon
einen Z5-Bruch zur Folge: Der Aufgaben-Loeschknopf existierte zweimal, und nur
eine Fassung prueft das Kanalrecht.

WARUM DIE ZUSICHERUNG SO ENG GEFASST IST: "Keine doppelte Logik" waere eine
Stilregel und erzeugte Fehlalarme quer durchs Projekt - zwei ``__init__``, die
beide drei Attribute setzen, sind keine Doppelung. Geprueft wird deshalb nur der
harte Fall: **gleicher Name, zeichengleicher Rumpf**. Was hier anschlaegt, ist
ohne Urteilsfrage eine Kopie.

Ein Test mit Fehlalarmen wird ignoriert, und ein ignorierter Test ist so wertlos
wie ein gruener.

ABGRENZUNG: Nur ``cogs/``. Dort sitzen die beiden bekannten Paare, und dort ist
die Doppelung teuer, weil die Discord-Oberflaeche dieselbe Aktion oft auf zwei
Wegen anbietet. ``services/`` und ``app/`` sind bewusst aussen vor - sie haben
eigene Muster (Request/Result-Paare), die hier Laerm erzeugen wuerden, ohne dass
ein Befund dahinter steckt.

GEGENPROBE (durchgefuehrt 2026-09-17): rot mit **drei** Befunden, nicht mit den
erwarteten zwei - und der dritte war lehrreich::

    _get_container_logs       status_info_integration.py:608  /  :779
    _validate_custom_address  control_ui.py:1177  /  status_info_integration.py:1019
    get_logs_sync             status_info_integration.py:620  /  :791

``get_logs_sync`` ist die verschachtelte Funktion INNERHALB von
``_get_container_logs``. Sie stand nur deshalb zweimal da, weil ihre
Elternfunktion zweimal dastand.

Die naheliegende Reaktion waere gewesen, verschachtelte Funktionen
auszuschliessen, damit die Zahl stimmt. Das waere Gruenfaerben: Die Grenze "nur
Funktionen oberster Ebene" ist genauso gesetzt wie ``MINDESTZEILEN = 8``, und
eine Schwelle nachtraeglich passend zu machen ist das Gegenteil von Messen. Der
Melder blieb deshalb unveraendert, und die ehrlichere Probe lautete: Faellt er
nach dem Zusammenlegen von selbst auf null?

Er tut es. Nach der Korrektur: **0 Befunde**, Melder unangetastet,
``tests/unit/cogs`` unveraendert 267 gruen.

Die beiden Waechter waren von Anfang an gruen - das Vergleichsmass normalisiert
die Einrueckung (dieselbe Methode steht in zwei Klassen verschieden tief) und
haelt "gleicher Name bei anderem Inhalt" auseinander. Ohne diese Unterscheidung
haette der Test jede ``callback``-Methode des Projekts gemeldet.

WAS DIE KORREKTUR AENDERT:
``validate_custom_address`` liegt jetzt einmal in ``cogs/control_helpers.py``,
neben ``_channel_has_permission``; beide Aufrufer holen sie funktionsintern.
``container_logs_text`` ist eine Modulfunktion mit ``container_name`` als
Parameter; sechs Aufrufstellen ziehen mit. Beide Methoden benutzten von ``self``
nichts ausser dem Containernamen - die Kopie hatte keinen Grund ausser Bequemlichkeit.
"""

import ast
from collections import defaultdict
from pathlib import Path

import pytest

PROJEKT = Path(__file__).resolve().parents[2]
VERZEICHNIS = PROJEKT / "cogs"

# Zu kurze Rumpfe sind keine Doppelung, sondern Konvention: ein ``pass``, ein
# ``return None``, ein einzeiliger Weiterreicher. Erst ab dieser Laenge ist eine
# zeichengleiche Kopie ein Befund und keine Formalie.
MINDESTZEILEN = 8


def _funktionen():
    """Alle Funktionen in cogs/ mit ihrem normalisierten Rumpf."""
    gefunden = defaultdict(list)
    for pfad in sorted(VERZEICHNIS.rglob("*.py")):
        quelle = pfad.read_text(encoding="utf-8", errors="replace")
        try:
            baum = ast.parse(quelle)
        except SyntaxError:
            continue
        zeilen = quelle.splitlines()
        for knoten in ast.walk(baum):
            if not isinstance(knoten, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            rumpf = zeilen[knoten.lineno - 1:knoten.end_lineno]
            if len(rumpf) < MINDESTZEILEN:
                continue
            # Einrueckung normalisieren: dieselbe Funktion in zwei Klassen steht
            # gleich tief, aber darauf soll es nicht ankommen.
            text = "\n".join(z.strip() for z in rumpf)
            gefunden[knoten.name].append(
                (f"{pfad.relative_to(PROJEKT)}:{knoten.lineno}", text)
            )
    return gefunden


def test_es_gibt_ueberhaupt_funktionen_zu_pruefen():
    """Sicherung gegen ein stumpfes Werkzeug.

    Liest die Suche ins Leere - falscher Pfad, geaenderte Baumstruktur -, waere
    der Test unten gruen, ohne irgendetwas zu belegen.
    """
    alle = _funktionen()
    gesamt = sum(len(v) for v in alle.values())
    assert gesamt > 100, (
        f"Nur {gesamt} Funktionen in cogs/ gefunden - vermutlich stimmt der Pfad nicht"
    )


def test_das_werkzeug_erkennt_eine_zeichengleiche_kopie():
    """Wirkungsnachweis: Der Melder muss anschlagen, wenn es etwas zu melden gibt.

    Und er darf NICHT anschlagen, wenn nur der Name gleich ist. Zwei
    ``callback``-Methoden mit verschiedenem Inhalt sind keine Doppelung - ohne
    diese Unterscheidung waere der Test ein Fehlalarmwerkzeug.
    """
    gleich_a = "def f(self):\n    a = 1\n    b = 2\n    c = 3\n    d = 4\n    e = 5\n    g = 6\n    return a"
    gleich_b = "    def f(self):\n        a = 1\n        b = 2\n        c = 3\n        d = 4\n        e = 5\n        g = 6\n        return a"
    anders = "def f(self):\n    a = 9\n    b = 2\n    c = 3\n    d = 4\n    e = 5\n    g = 6\n    return a"

    norm = lambda t: "\n".join(z.strip() for z in t.splitlines())
    assert norm(gleich_a) == norm(gleich_b), (
        "Unterschiedliche Einrueckung darf zwei Kopien nicht auseinanderhalten - "
        "dieselbe Funktion steht in zwei Klassen verschieden tief."
    )
    assert norm(gleich_a) != norm(anders), (
        "Gleicher Name bei anderem Inhalt ist KEINE Doppelung - sonst meldet der "
        "Test jede callback-Methode des Projekts."
    )


def test_keine_funktion_steht_zweimal_zeichengleich_da():
    """Gleicher Name plus zeichengleicher Rumpf heisst: eine Kopie zu viel."""
    befunde = []
    for name, vorkommen in sorted(_funktionen().items()):
        if len(vorkommen) < 2:
            continue
        nach_text = defaultdict(list)
        for ort, text in vorkommen:
            nach_text[text].append(ort)
        for orte in nach_text.values():
            if len(orte) > 1:
                befunde.append(f"{name}  ->  " + "  /  ".join(orte))

    assert not befunde, (
        f"{len(befunde)} Funktionen stehen zeichengleich an mehreren Orten. Eine "
        "Korrektur an einer Kopie laesst die andere unveraendert - genau so "
        "entstand heute der Z5-Bruch am Aufgaben-Loeschknopf:\n  "
        + "\n  ".join(befunde)
    )
