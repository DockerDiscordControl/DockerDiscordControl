# -*- coding: utf-8 -*-
"""Ein ``import`` darf keine Konfiguration von der Platte lesen.

KEIN ``@deckt``-Marker, und das mit Absicht: Das waere eine neue Zusicherung, und
die Zusicherungen sind die Entscheidung des Betreibers, nicht meine. Soll daraus
Z11 werden, kommt der Marker nach.

WOHER DER BEFUND KOMMT (Stufe 3, 2026-09-17): Beim Einzeldurchlauf aller 127
Testdateien scheiterten zwei Tests in ``test_r2_g5_mech.py``, sobald sie allein
liefen - nicht an ihrer eigenen Zusicherung, sondern schon am ``import`` in
Zeile 1. ``docker_utils.py:76-80`` ruft fuenfmal AUF MODULEBENE
``_load_timeout_from_config(...)`` auf, und jeder dieser Aufrufe ruft
``load_config()``. Ein sechster Fall steht bei ``:676`` (``_CACHE_TTL``).

Warum das mehr ist als eine Stilfrage:

1. Ein Import liest die Platte. Faellt das Lesen aus - Rechte, fehlendes
   Verzeichnis, kaputte Datei -, scheitert nicht eine Funktion, sondern der
   IMPORT, und zwar als ``ImportError`` tief in einer neunstufigen Kette statt
   als verstaendliche Meldung.
2. Das Sicherheitsnetz dort faengt ``(ConfigLoadError, KeyError, ValueError,
   TypeError)``. Ein ``AttributeError`` ist nachweislich durchgeschluepft.
3. Der Zeitpunkt des Ladens haengt davon ab, wer zufaellig zuerst importiert.
   Genau das machte die beiden Tests oben reihenfolgeabhaengig.

WARUM IN EINEM EIGENEN PROZESS: Der naheliegende Weg waere ``importlib.reload``.
Der wuerde die Modulwelt dieses Testlaufs umbauen und damit genau die
Reihenfolgeabhaengigkeit erzeugen, die hier beseitigt werden soll. Ein eigener
Prozess hat einen frischen ``sys.modules`` und laesst nichts zurueck.

GEGENPROBE (durchgefuehrt 2026-09-17), in drei Schritten - zwei davon Fehler von
mir, und beide gehoeren hierher:

*Erster Lauf, vor der Korrektur:* rot, mit genau der richtigen Begruendung im
Stapel - ``services/docker_service/__init__.py:10`` -> ``docker_utils.py:76``
-> ``:57 config = load_config()`` -> ``AssertionError: IMPORT HAT KONFIGURATION
GELESEN``. Der Waechter ``WAECHTER_SCHON_GELADEN`` schlug NICHT an, das Modul war
also wirklich noch ungeladen und der Test prueft etwas.

*Zweiter Lauf, nach der Korrektur am Produktivcode:* immer noch rot - aber der
Stapel zeigte ``File "<string>", line 27``, also die PRUEFSCHLEIFE dieses Tests.
Der Import lief laengst still durch; gescheitert ist der Zugriff auf die traegen
Werte, weil die Attrappe noch stand. Ein Zugriff SOLL Konfiguration lesen, das
ist der Sinn der Umstellung. Der Test mass sich selbst kaputt. Behoben, indem
``load_config`` vor der Pruefschleife wiederhergestellt wird.

*Gleichzeitig 23 rote Tests* in ``tests/unit/services/docker_service``:
``NameError`` auf ``CONTAINER_TYPE_PATTERNS`` und ``DEFAULT_TIMEOUT_CONFIG``. Ich
hatte die Falle benannt - modulweites ``__getattr__`` bedient keine freien Namen
im Funktionsrumpf - und dann nur die fuenf Zeitwerte umgestellt, die beiden
Woerterbuecher vergessen. Mein Waechter-Grep suchte ebenfalls nur nach den fuenf
Namen und meldete Vollzug. Die zweite Fassung zieht die traegen Namen per AST
aus ``_TIMEOUT_SPECS`` und ``_LAZY_BUILDERS`` - also aus dem Code statt aus
meiner Aufzaehlung - und fand prompt auch ``_CACHE_TTL``.

*Dritter Lauf:* Importtest gruen, ``tests/unit/services/docker_service`` wieder
86 gruen.

WIRKUNGSNACHWEIS, und er ist staerker als eine Mutation:
``tests/unit/audit_2026_09/test_r2_g5_mech.py`` scheiterte ALLEIN mit 2 von 41.
Nach der Korrektur: 41 gruen, **ohne dass ein einziger Test angefasst wurde**.
Die Reihenfolgeabhaengigkeit ist verschwunden, weil ihre Ursache weg ist.

WAS DAMIT NICHT BELEGT IST: Dieser Test prueft EIN Modul, nicht das Projekt.
``services/mech/progress_service.py:125`` liest weiterhin beim Import
(``CFG = load_config()``) - bewusst nicht angefasst, weil fuenf Testdateien
``progress_service.CFG`` von aussen zuweisen und es damit faktisch eine
Schnittstelle ist. Wer diese Zusicherung auf das ganze Projekt ausweiten will,
muss dort zuerst entscheiden, was mit dieser Schnittstelle geschieht.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PROJEKT = Path(__file__).resolve().parents[2]

# Rueckgabewerte des Unterprozesses
OK = 0
WAECHTER_SCHON_GELADEN = 3
WAECHTER_KEIN_FLOAT = 4


def _lauf(modul: str) -> subprocess.CompletedProcess:
    """Importiere ``modul`` in einem frischen Prozess, in dem load_config wirft.

    Der Wachhund ist die Sabotage selbst: ``load_config`` wirft einen
    ``AssertionError``. Der steht in KEINER der abgefangenen Ausnahmen von
    ``_load_timeout_from_config`` - der Test misst damit, ob der Aufruf
    STATTFINDET, nicht bloss, ob sein Ergebnis behandelt wird.
    """
    skript = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(PROJEKT)!r})

        import services.config.config_service as cs

        # Waechter gegen ein stumpfes Werkzeug: Ist das Zielmodul schon geladen,
        # bevor wir sabotieren, kann der Import unten nichts mehr ausloesen und
        # der Test waere gruen, ohne irgendetwas zu belegen.
        if {modul!r} in sys.modules:
            sys.exit({WAECHTER_SCHON_GELADEN})

        def _wirft(*_a, **_k):
            raise AssertionError("IMPORT HAT KONFIGURATION GELESEN")

        _echtes_load_config = cs.load_config
        cs.load_config = _wirft

        import importlib
        modul = importlib.import_module({modul!r})

        # Sabotage ZURUECKNEHMEN, bevor die Werte angefasst werden.
        # Ohne das misst der Test sich selbst kaputt: Ein Zugriff auf einen der
        # traegen Werte SOLL Konfiguration lesen - das ist ja der Sinn der
        # Umstellung. Die erste Fassung liess die Attrappe stehen und scheiterte
        # deshalb an ihrer eigenen Pruefschleife, obwohl der Import laengst still
        # durchlief. Geprueft wird der IMPORT, nicht der Zugriff.
        cs.load_config = _echtes_load_config

        # Die Werte muessen weiterhin da und float sein - sonst waere der Import
        # zwar still, aber das Modul unbrauchbar. Drei vorhandene Tests in
        # tests/unit/services/docker_service/ nageln genau das fest.
        for name in ("DEFAULT_FAST_STATS_TIMEOUT", "DEFAULT_SLOW_STATS_TIMEOUT",
                     "DEFAULT_FAST_INFO_TIMEOUT", "DEFAULT_SLOW_INFO_TIMEOUT",
                     "DEFAULT_CONTAINER_LIST_TIMEOUT"):
            if not isinstance(getattr(modul, name, None), float):
                sys.exit({WAECHTER_KEIN_FLOAT})

        sys.exit({OK})
        """
    )
    return subprocess.run(
        [sys.executable, "-c", skript],
        capture_output=True, text=True, timeout=120, cwd=str(PROJEKT),
    )


def test_docker_utils_liest_beim_import_keine_konfiguration():
    """``import services.docker_service.docker_utils`` fasst die Platte nicht an."""
    ergebnis = _lauf("services.docker_service.docker_utils")

    assert ergebnis.returncode != WAECHTER_SCHON_GELADEN, (
        "Das Modul war bereits geladen, bevor die Attrappe gesetzt wurde - dieser "
        "Test prueft dann nichts. Vermutlich zieht services/__init__.py es schon nach."
    )
    assert ergebnis.returncode != WAECHTER_KEIN_FLOAT, (
        "Der Import blieb zwar still, aber die Zeitwerte sind keine floats mehr - "
        "das Modul waere damit unbrauchbar."
    )
    assert ergebnis.returncode == OK, (
        "Der Import hat Konfiguration von der Platte gelesen.\n"
        "Ein Import soll nichts tun: Faellt das Lesen aus, scheitert nicht eine "
        "Funktion, sondern der Import - als ImportError tief in der Kette.\n"
        f"--- stderr ---\n{ergebnis.stderr[-2000:]}"
    )
