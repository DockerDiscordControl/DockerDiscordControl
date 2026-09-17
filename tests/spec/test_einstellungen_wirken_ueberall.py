# -*- coding: utf-8 -*-
"""Eine Einstellung aus dem Panel wirkt auf JEDEM Pfad - oder nirgends.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND (Stufe 2, Punkt 3 - dieselbe Regel an zwei Stellen):
Das Panel bietet unter "Advanced Settings" 23 Schluessel an und schreibt sie
nach ``config['advanced_settings']`` (``config_form_parser_service.py:415-425``).
Gelesen werden sie ueber ``_get_advanced_setting``, das ZUERST die Konfiguration
fragt und erst dann auf ``os.environ`` zurueckfaellt.

Drei dieser Schluessel werden im Discord-Teil aber **direkt aus der Umgebung**
gelesen, an neun Stellen::

    DDC_DOCKER_CACHE_DURATION   docker_control.py:182, :3643,
                                container_status_service.py:108,
                                status_cache_service.py:40
    DDC_DOCKER_MAX_CACHE_AGE    docker_control.py:2476, :2865, :3057
    DDC_DOCKER_QUERY_COOLDOWN   docker_control.py:225,
                                docker_status/fetch_service.py:40

Diese neun sehen ``advanced_settings`` nie. Wer den Wert im Panel aendert,
aendert ihn fuer den Web-Teil - und fuer den Discord-Teil **nicht**. Keine
Fehlermeldung, kein Hinweis: die Einstellung ist dort still wirkungslos.

Dass es anders geht, steht im selben Haus: ``cogs/status_handlers.py:341`` und
``:446`` benutzen ``_get_advanced_setting`` bereits. Es ist kein
Architekturproblem, sondern Inkonsequenz.

ABGRENZUNG - bewusst NICHT geprueft wird ``DDC_CONFIG_DIR``: Das ist eine
Startvariable, die es geben muss, BEVOR es eine Konfiguration zu lesen gibt. Sie
gehoert zu ``os.environ``. Wuerde dieser Test sie melden, erzeugte er einen
Fehlalarm - und ein Test mit Fehlalarmen wird ignoriert, ist also so wertlos wie
ein gruener.

GEPRUEFT PER AST, nicht per Textsuche: ``os.environ.get('DDC_...')`` kann in
einem Kommentar oder String stehen. Genau dieser Fehlalarm hat den Z10-Melder
einmal wertlos gemacht.

GEGENPROBE (durchgefuehrt 2026-09-17): 1 rot mit **genau neun** Fundstellen,
2 gruen - exakt wie vorhergesagt, und die Neun deckt sich auf den Punkt mit der
Auszaehlung von Hand.

Die drei vorher benannten Fallen sind keine geworden: Die Panel-Schluessel wurden
gefunden (sonst haette der erste Waechter angeschlagen), die Umgebungssuche
greift (der zweite Waechter belegt es ueber ``DDC_CONFIG_DIR``, von dem bekannt
ist, dass es direkt gelesen wird), und die Zahl stimmte.

Nach der Umstellung: 3 gruen. Betroffene Gruppen unveraendert - ``cogs`` 267,
``services/infrastructure`` 197, ``services/docker_service`` 86,
``services/web`` 358, ``services/mech`` 433.

WAS DIE KORREKTUR AENDERT: Die neun Stellen lesen ueber ``utils/settings.py``,
also Konfiguration zuerst, Umgebung danach. Eine im Panel gesetzte
Cache-Dauer wirkt jetzt auch im Discord-Teil.

MITGEZOGEN, damit nicht die zehnte Kopie entsteht:
``web_helpers._get_advanced_setting`` reicht an denselben Helfer weiter, statt
die Regel ein zweites Mal zu halten.

EIN BEINAHE-SCHADEN, der hierher gehoert, weil er die Grenze eines Waechters
zeigt: Beim Umbau von ``web_helpers._get_advanced_setting`` schnitt mein
Ersetzungsskript mit ``s.index("\\ndef ", start+1)`` bis zum naechsten ``def`` auf
Modulebene - und loeschte dabei **79 statt 19 Zeilen**, darunter die Modulwerte
``docker_cache``, ``CACHE_CLEANUP_INTERVAL`` und ``cache_lock``. Die
ast.parse-Pruefung lief **durch**, weil das Ergebnis syntaktisch einwandfrei war.
Aufgefallen ist es erst am Gesamtlauf: **37 rote Tests** in vier Gruppen.

Die Lehre ist nicht "vorsichtiger schneiden", sondern: Eine Syntaxpruefung sagt
nichts darueber, ob der Inhalt stimmt. Die zweite Fassung nimmt die Grenzen der
Funktion aus dem AST (``lineno``/``end_lineno``) statt aus einer Textsuche und
prueft danach ausdruecklich, dass die drei Modulwerte noch da sind.

ZWEI EIGENE FEHLALARME, die ebenfalls hierher gehoeren: Mein Umbau hinterliess fuenf
``get_setting``-Importe in ``docker_control.py``, und ich hielt das fuer
Doppelung. Die Zuordnung per AST zeigte: Jeder sitzt in einer ANDEREN Funktion -
genau die Bauart, die ``utils/`` durchgehend benutzt. Ich hatte eine Zahl gegen
eine geschaetzte Funktionsanzahl gehalten, statt zu zaehlen. Vier tote ``import
os`` waren dagegen echt und sind entfernt, mit einem Waechter gegen zu eifriges
Loeschen (benutzt die Datei ``os`` noch, muss der Import bleiben).
"""

import ast
from pathlib import Path

import pytest

PROJEKT = Path(__file__).resolve().parents[2]

# Anwendungscode. scripts/ ist ausgenommen - Einmalwerkzeuge, gleiche
# Abgrenzung wie bei Z7.
VERZEICHNISSE = ("cogs", "services", "app", "utils")

# Startvariablen: muessen vor der Konfiguration da sein, gehoeren zu os.environ.
STARTVARIABLEN = {"DDC_CONFIG_DIR"}


def _panel_schluessel() -> set:
    """Die Schluessel, die das Panel unter Advanced Settings anbietet.

    Aus dem Quelltext gezogen statt hier aufgelistet: Eine Aufzaehlung im Test
    waere die naechste Kopie derselben Regel - und wuerde veralten, sobald das
    Panel einen Schluessel dazubekommt.
    """
    quelle = (PROJEKT / "services" / "web" / "configuration_page_service.py")
    baum = ast.parse(quelle.read_text(encoding="utf-8"))
    schluessel = set()
    for knoten in ast.walk(baum):
        if (isinstance(knoten, ast.Call)
                and isinstance(knoten.func, ast.Name)
                and knoten.func.id == "get_setting_value"
                and knoten.args
                and isinstance(knoten.args[0], ast.Constant)
                and isinstance(knoten.args[0].value, str)
                and knoten.args[0].value.startswith("DDC_")):
            schluessel.add(knoten.args[0].value)
    return schluessel - STARTVARIABLEN


def _direkte_umgebungslesungen():
    """Stellen, die einen DDC_-Schluessel direkt aus os.environ lesen."""
    treffer = []
    for verzeichnis in VERZEICHNISSE:
        for pfad in sorted((PROJEKT / verzeichnis).rglob("*.py")):
            try:
                baum = ast.parse(pfad.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for knoten in ast.walk(baum):
                if not (isinstance(knoten, ast.Call)
                        and isinstance(knoten.func, ast.Attribute)
                        and knoten.func.attr == "get"):
                    continue
                ziel = knoten.func.value
                # os.environ.get(...) bzw. environ.get(...)
                istumgebung = (
                    (isinstance(ziel, ast.Attribute) and ziel.attr == "environ")
                    or (isinstance(ziel, ast.Name) and ziel.id == "environ")
                )
                if not istumgebung or not knoten.args:
                    continue
                erstes = knoten.args[0]
                if isinstance(erstes, ast.Constant) and isinstance(erstes.value, str):
                    treffer.append((pfad.relative_to(PROJEKT), knoten.lineno, erstes.value))
    return treffer


def test_das_panel_bietet_ueberhaupt_schluessel_an():
    """Sicherung gegen ein stumpfes Werkzeug.

    Liest die Schluesselsuche ins Leere - weil sich der Aufbau von
    ``configuration_page_service`` aendert -, waere der Test unten gruen, ohne
    irgendetwas zu belegen.
    """
    schluessel = _panel_schluessel()
    assert len(schluessel) > 15, (
        f"Nur {len(schluessel)} Panel-Schluessel gefunden: {sorted(schluessel)}. "
        "Vermutlich wird get_setting_value nicht mehr so aufgerufen."
    )


def test_das_werkzeug_findet_umgebungslesungen():
    """Wirkungsnachweis: Der Melder muss finden, was es zu finden gibt.

    Ohne diesen Fall koennte die Suche stillschweigend nichts liefern und der
    Test unten waere gruen, weil er nichts sieht - nicht, weil nichts da ist.
    """
    treffer = _direkte_umgebungslesungen()
    assert treffer, "Keine einzige os.environ.get-Stelle gefunden - das Werkzeug greift nicht"
    schluessel = {k for _, _, k in treffer}
    assert "DDC_CONFIG_DIR" in schluessel, (
        "DDC_CONFIG_DIR wird nachweislich direkt gelesen und muesste auftauchen - "
        "tut es das nicht, sucht das Werkzeug an der falschen Stelle."
    )


def test_panel_einstellungen_werden_nicht_an_der_konfiguration_vorbei_gelesen():
    """Was das Panel anbietet, muss ueber die Konfiguration gelesen werden."""
    panel = _panel_schluessel()
    befunde = [
        f"{pfad}:{zeile}  {schluessel}"
        for pfad, zeile, schluessel in _direkte_umgebungslesungen()
        if schluessel in panel
    ]

    assert not befunde, (
        f"{len(befunde)} Stellen lesen eine Panel-Einstellung direkt aus der "
        "Umgebung und sehen damit nie, was der Nutzer im Panel eingestellt hat. "
        "Die Einstellung wirkt im Web-Teil und ist hier still wirkungslos:\n  "
        + "\n  ".join(befunde)
    )
