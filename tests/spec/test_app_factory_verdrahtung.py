# -*- coding: utf-8 -*-
"""``create_app`` muss jeden Aufbauschritt wirklich ausfuehren.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND (Stufe 3, Pruefung 3 - Funktion gegen Aufrufstelle):
``app/web/app_factory.py:create_app`` setzt die Flask-Anwendung aus elf
Schritten zusammen. Jeder einzelne ist geprueft. Die **Verdrahtung** war es
nicht.

Belegt per Mutation, nicht erschlossen: Vier Schritte wurden einzeln aus
``create_app`` entfernt, und ``tests/test_web_factory.py`` blieb **jedes Mal
gruen**::

    ohne install_csrf_protection       -> 1 passed
    ohne register_i18n                 -> 1 passed
    ohne register_background_services  -> 1 passed
    ohne register_blueprints           -> 1 passed

Der CSRF-Schutz kann also aus dem Aufbau fallen, ohne dass irgendetwas rot wird.

WARUM DIE VORHANDENEN TESTS DAS NICHT FANGEN:
``test_web_factory.py`` prueft, dass eine Flask-Instanz zurueckkommt, ``/health``
antwortet und ``Content-Security-Policy`` gesetzt ist - damit ist
``install_security_handlers`` abgedeckt und sonst nichts.
``tests/unit/security/test_bundle3_security.py`` ersetzt ``register_blueprints``
und ``register_routes`` per ``monkeypatch`` durch eigene Fassungen, prueft also
ausdruecklich NICHT den echten Aufbau. ``tests/security/test_security_sast.py``
importiert aus ``app.web_ui`` und ueberspringt bei ``ImportError``.

EIN EIGENER FEHLER, der hierher gehoert: Die Erhebung, die auf diesen Befund
fuehrte, meldete zunaechst ACHT Funktionen als "Aufrufstelle nie getestet". Das
war falsch - sie suchte den Modulnamen ``app_factory`` im Testtext, aufgerufen
wird aber ueber ``from app.web import create_app``. Der Melder prueft den
falschen Namen. Uebrig bleibt ein Befund statt acht; der ist dafuer gemessen.

WIE HIER GEPRUEFT WIRD: nicht "ist die Funktion importierbar" (das waere wieder
die Funktion statt der Aufrufstelle), sondern: **Wird sie beim Bau tatsaechlich
gerufen?** Jeder Schritt wird durch eine Attrappe ersetzt, die ihren Aufruf
vermerkt; danach muss jede Attrappe genau einmal angesprungen sein.

GEGENPROBE (durchgefuehrt 2026-09-17) - und der lehrreichste Teil ist, dass die
ERSTE FASSUNG DIESES TESTS SELBST EIN SPIEGELTEST WAR:

Sie zog die Erwartungsliste aus den **Aufrufen innerhalb von create_app**.
Faellt ein Aufruf heraus, verschwindet er damit zugleich aus der Erwartung - der
Test verglich die Datei mit sich selbst und konnte nicht fehlschlagen. Die
Mutation hat es entlarvt::

    erste Fassung, ohne install_csrf_protection  -> 2 passed   (blind)
    erste Fassung, ohne register_i18n            -> 2 passed   (blind)

Der Waechter ``len(schritte) >= 8`` fing das nicht: Aus elf Schritten werden
zehn, die Schwelle haelt.

Ausgerechnet beim Einstieg in die Pruefung, die Spiegeltests finden soll.

*Zweite Fassung:* Die Erwartung kommt aus den **Importen** und wird ueber die
**Signatur des Herkunftsmoduls** abgegrenzt - wer ``app`` als ersten Parameter
nimmt, ist ein Aufbauschritt. Beides steht ausserhalb des Prueflings und bleibt
stehen, wenn ein Aufruf entfaellt.

*Ein Zwischenschritt scheiterte noch:* ``TypeError: 'NoneType' object is not
iterable``. ``build_config`` stand in der Importliste, wird aber als
``build_config(os.environ, test_config)`` gerufen und sein Rueckgabewert fliesst
in ``app.config.update``. Es ist ein Konfigurationslieferant, kein Schritt am
app-Objekt - die Signaturpruefung schliesst es korrekt aus.

*Dritte Fassung, gemessen:* 2 gruen im Normalzustand. Und sie beisst::

    ohne install_csrf_protection  -> 1 failed
    ohne register_i18n            -> 1 failed
    ohne register_blueprints      -> 1 failed

Damit ist belegt, was bei diesem Test nicht selbstverstaendlich ist: Sein Rot
kommt nicht aus dem Befund - die Zusicherung gilt heute ja -, sondern musste
kuenstlich erzeugt werden. Ohne diese Probe waere er ein Test, der nicht
fehlschlagen kann.
"""

import ast
from pathlib import Path

import pytest

PROJEKT = Path(__file__).resolve().parents[2]
FABRIK = PROJEKT / "app" / "web" / "app_factory.py"

def _erwartete_schritte() -> list:
    """Die Schritte, die create_app ausfuehren MUSS - aus den IMPORTEN gezogen.

    ERSTE FASSUNG WAR EIN SPIEGELTEST, und die Mutation hat es entlarvt: Sie
    las die Liste aus den AUFRUFEN innerhalb von ``create_app``. Faellt ein
    Aufruf heraus, verschwindet er zugleich aus der Erwartung - der Test
    verglich die Datei mit sich selbst und konnte nicht fehlschlagen. Entfernt
    man ``install_csrf_protection(app)``, blieb er gruen.

    Die Importe bleiben stehen, wenn ein Aufruf entfaellt. Sie sind damit eine
    Erwartung von AUSSEN statt ein Abbild des Prueflings. Kommt ein Schritt
    hinzu, wird er automatisch mitgeprueft; verschwindet sein Aufruf, wird der
    Test rot.

    Abgegrenzt: Nur Importe aus Geschwistermodulen (``from .x import y``), und
    nur solche, die ein Anwendungsobjekt entgegennehmen. ``initialize_gevent``
    nimmt einen Logger und steht deshalb in AUSNAHMEN.
    """
    import importlib
    import inspect

    baum = ast.parse(FABRIK.read_text(encoding="utf-8"))
    fabrik_modul = importlib.import_module("app.web.app_factory")

    namen = []
    for knoten in baum.body:
        if not (isinstance(knoten, ast.ImportFrom) and knoten.level == 1):
            continue
        for alias in knoten.names:
            name = alias.asname or alias.name
            ding = getattr(fabrik_modul, name, None)
            if not callable(ding):
                continue
            try:
                parameter = list(inspect.signature(ding).parameters)
            except (TypeError, ValueError):
                continue
            # Ein Aufbauschritt nimmt das Anwendungsobjekt als erstes Argument.
            # Das steht in der Signatur des HERKUNFTSMODULS, nicht im Pruefling -
            # deshalb bleibt es stehen, wenn ein Aufruf aus create_app faellt.
            # build_config(environ, test_config) liefert Konfiguration und ist
            # kein Schritt am app-Objekt; initialize_gevent nimmt einen Logger.
            if parameter and parameter[0] == "app":
                namen.append(name)
    return sorted(set(namen))


def _aufbauschritte() -> list:
    """Beibehalten fuer den Waechter unten - zeigt, was create_app HEUTE ruft."""
    baum = ast.parse(FABRIK.read_text(encoding="utf-8"))
    fabrik = next(k for k in ast.walk(baum)
                  if isinstance(k, ast.FunctionDef) and k.name == "create_app")
    schritte = []
    for knoten in ast.walk(fabrik):
        if (isinstance(knoten, ast.Call)
                and isinstance(knoten.func, ast.Name)
                and len(knoten.args) == 1
                and isinstance(knoten.args[0], ast.Name)
                and knoten.args[0].id == "app"):
            schritte.append(knoten.func.id)
    return sorted(set(schritte))


def test_die_schrittliste_ist_nicht_leer():
    """Sicherung gegen ein stumpfes Werkzeug.

    Liest die Schrittsuche ins Leere - weil sich der Aufbau von ``create_app``
    aendert -, waere der Test unten gruen, ohne einen einzigen Schritt zu
    pruefen. Genau diese Bauart hat heute schon zweimal einen Melder wertlos
    gemacht.
    """
    erwartet = _erwartete_schritte()
    assert len(erwartet) >= 8, (
        f"Nur {len(erwartet)} Aufbauschritte aus den Importen gelesen: {erwartet}. "
        "Vermutlich importiert app_factory sie nicht mehr als 'from .x import y'."
    )


def test_create_app_fuehrt_jeden_aufbauschritt_aus(monkeypatch):
    """Faellt ein Schritt aus dem Aufbau, muss das auffallen.

    Vier Schritte liessen sich am 2026-09-17 ersatzlos entfernen, ohne dass ein
    Test rot wurde - darunter der CSRF-Schutz.
    """
    monkeypatch.setenv("DDC_ENABLE_BACKGROUND_REFRESH", "false")
    monkeypatch.setenv("DDC_ENABLE_MECH_DECAY", "false")

    gerufen = []
    schritte = _erwartete_schritte()

    for name in schritte:
        def attrappe(app, _name=name):
            gerufen.append(_name)
        # Am Modul der FABRIK ersetzen, nicht am Herkunftsmodul: create_app hat
        # die Namen beim Import gebunden.
        monkeypatch.setattr(f"app.web.app_factory.{name}", attrappe, raising=True)

    from app.web.app_factory import create_app
    create_app({"TESTING": True})

    fehlend = [s for s in schritte if s not in gerufen]
    assert not fehlend, (
        "Diese Aufbauschritte stehen in create_app, wurden aber nicht "
        f"ausgefuehrt: {fehlend}. Gerufen wurden: {sorted(set(gerufen))}"
    )
    doppelt = [s for s in set(gerufen) if gerufen.count(s) > 1]
    assert not doppelt, f"Doppelt ausgefuehrte Aufbauschritte: {doppelt}"
