# -*- coding: utf-8 -*-
"""Kein nacktes ``except:`` im Anwendungscode.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers. Soll daraus Z12 werden, kommt der Marker nach.

WORUM ES GEHT - und ausdruecklich NICHT um Stil: ``except:`` faengt jede
``BaseException``, also auch ``KeyboardInterrupt`` und ``SystemExit``. Beim
Herunterfahren des Containers heisst das:

* Aufraeumcode wird uebersprungen, weil das Abbruchsignal im ``except`` haengen
  bleibt statt durchzulaufen.
* Schlimmer: Faengt ein ``except:`` rund um einen Discord-Versand das
  Abbruchsignal, laeuft der Ersatzpfad an und schickt eine Nachricht, die
  niemand angefordert hat - beim Herunterfahren.

Der zweite Fall ist in ``docker_control.py`` real: Dort umschliesst ein nacktes
``except:`` einen ``followup.send``-Aufruf samt Ersatzversand.

ABGRENZUNG: ``except Exception:`` ist erlaubt. Diese Zusicherung verlangt nicht,
dass jede Stelle ihre Ausnahmen einzeln aufzaehlt - das waere eine Stilregel und
wuerde Fehlalarme erzeugen, die den Test wertlos machen. Sie verlangt nur, dass
die beiden Signale zum Programmabbruch nicht mitgefangen werden.

PRUEFT DEN QUELLTEXT PER AST, nicht per Textsuche: ``except:`` kann in einem
Kommentar oder einer Zeichenkette stehen, und genau dieser Fehlalarm hat beim
Z10-Melder vier falsche Treffer erzeugt (siehe test_z10_ci_test_gate.py). Der
AST kennt den Unterschied.

GEGENPROBE (durchgefuehrt 2026-09-17):

*Vor der Korrektur:* rot mit **33** Befunden - exakt der Inventur aus der
Bestandsaufnahme (25 in ``cogs/``, 7 in ``services/``, 1 in ``utils/``, 0 in
``app/``). Die beiden Waechter oben waren dabei gruen: Der Baum war gefuellt,
und das Werkzeug unterschied ein echtes ``except:`` korrekt von ``except
Exception:``, von einem Kommentar, von einer Zeichenkette und von einem
Ausnahmetupel. Ohne diesen zweiten Waechter waere der Melder so wertlos gewesen
wie die erste Fassung des Z10-Melders, die auf Kommentare ansprang.

*Nach der Umstellung von 32 Stellen:* noch **ein** Befund - ``mech_images.py:25``,
bewusst ausgenommen. Diese Datei war totes Modul (siehe unten) und wurde
entfernt statt repariert; eine Ausnahmeregel im Test haette den Befund
versteckt statt beseitigt.

*Danach:* 0 Befunde, ohne dass der Test eine Ausnahme kennt.

WIRKUNGSNACHWEIS: Die fuenf betroffenen Testgruppen blieben unveraendert
(``cogs`` 267, ``services/web`` 358, ``services/automation`` 104,
``services/configuration`` 152, ``utils`` 248) - die Umstellung aendert kein
Verhalten ausser dem, um das es geht.

WAS DIE UMSTELLUNG KONKRET BEWIRKT, und das ist mehr als Kosmetik:
``docker_control.py:2198`` und ``:2252`` umschliessen einen Discord-Versand samt
Ersatzversand. Ein nacktes ``except:`` faengt dort ``CancelledError`` - beim
Herunterfahren waere also eine Spendennachricht hinausgegangen, die niemand
angefordert hat. ``except Exception:`` faengt sie nicht, weil ``CancelledError``
seit Python 3.8 von ``BaseException`` erbt.

BEFUND NEBENBEI, als eigener Commit behandelt: ``services/mech/mech_images.py``
importierte in Zeile 19 ``services.mech.mech_evolution_loader`` - eine Datei, die
es im ganzen Baum NICHT gibt. Das Modul war also nicht importierbar, und kein
Produktivmodul importierte es. Vierzehn Tests pruefen es ueber eine gepatchte
Kopie des Quelltexts; ihr eigener Kommentar sagte das. Modul und Tests sind
entfernt.
"""

import ast
from pathlib import Path

import pytest

PROJEKT = Path(__file__).resolve().parents[2]

# Der Anwendungscode. scripts/ ist bewusst NICHT dabei: Einmalwerkzeuge, vom
# Betreiber angestossen, der dabei zusieht - dieselbe Abgrenzung wie bei Z7.
VERZEICHNISSE = ("cogs", "services", "app", "utils")


def _dateien():
    for verzeichnis in VERZEICHNISSE:
        yield from sorted((PROJEKT / verzeichnis).rglob("*.py"))


def _nackte_excepts(pfad: Path):
    """Zeilennummern der ``except:``-Bloecke ohne Typ."""
    try:
        baum = ast.parse(pfad.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    return [
        knoten.lineno
        for knoten in ast.walk(baum)
        if isinstance(knoten, ast.ExceptHandler) and knoten.type is None
    ]


def test_der_baum_ist_nicht_leer():
    """Sicherung gegen ein stumpfes Werkzeug.

    Findet die Dateisuche nichts - weil ein Verzeichnis umbenannt wurde oder der
    Pfad falsch ist -, waere der Test unten gruen, ohne etwas zu belegen.
    """
    dateien = list(_dateien())
    assert len(dateien) > 100, (
        f"Nur {len(dateien)} Python-Dateien gefunden - vermutlich stimmt der Pfad nicht"
    )


def test_das_werkzeug_erkennt_ein_nacktes_except():
    """Wirkungsnachweis: Der Melder muss anschlagen, wenn es etwas zu melden gibt.

    Und er darf NICHT anschlagen bei ``except Exception:`` oder wenn die
    Zeichenfolge nur in einem Kommentar oder String steht - genau diese
    Fehlalarme haben den Z10-Melder einmal wertlos gemacht.
    """
    import tempfile

    faelle = [
        ("try:\n    pass\nexcept:\n    pass\n", 1, "echtes nacktes except nicht erkannt"),
        ("try:\n    pass\nexcept Exception:\n    pass\n", 0, "except Exception faelschlich gemeldet"),
        ("# except:\nx = 1\n", 0, "Kommentar faelschlich gemeldet"),
        ("s = 'except:'\n", 0, "Zeichenkette faelschlich gemeldet"),
        ("try:\n    pass\nexcept (ValueError, KeyError):\n    pass\n", 0, "Tupel faelschlich gemeldet"),
    ]
    for quelle, erwartet, meldung in faelle:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(quelle)
            pfad = Path(f.name)
        try:
            assert len(_nackte_excepts(pfad)) == erwartet, f"{meldung}: {quelle!r}"
        finally:
            pfad.unlink()


def test_kein_nacktes_except_im_anwendungscode():
    """``except:`` faengt KeyboardInterrupt und SystemExit mit."""
    befunde = []
    for pfad in _dateien():
        for zeile in _nackte_excepts(pfad):
            befunde.append(f"{pfad.relative_to(PROJEKT)}:{zeile}")

    assert not befunde, (
        f"{len(befunde)} nackte 'except:' - sie fangen KeyboardInterrupt und "
        "SystemExit mit, unterdruecken damit das Herunterfahren und koennen im "
        "Discord-Pfad sogar einen Ersatzversand ausloesen:\n  "
        + "\n  ".join(befunde)
    )
