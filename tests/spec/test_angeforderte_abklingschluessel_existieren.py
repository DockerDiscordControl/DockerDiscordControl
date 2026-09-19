# -*- coding: utf-8 -*-
"""Jeder Abklingschluessel, den lebender Code anfordert, muss auch existieren.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND. Drei Schluessel werden von lebendem Code angefordert, stehen aber in
KEINEM Vorgabe-Woerterbuch und haben KEIN Feld im Panel::

    "admin"        cogs/control_ui.py            AdminButton
    "tasks"        cogs/status_info_integration.py  TaskManagementButton
    "task_delete"  cogs/control_ui.py            TaskDeleteButton

``get_button_cooldown:186`` liefert fuer unbekannte Namen die Ersatzregel von
5 Sekunden. Die drei Knoepfe bremsen also - aber mit einem Wert, den der
Betreiber nirgends sehen und nirgends aendern kann.

ZWEI STUFEN, DIE BEIDE NOETIG SIND - gemessen, nicht angenommen: Ein Schluessel
allein in den Vorgaben genuegt NICHT. Der Speicherblock des Panels
(``_spam_protection_modal.html:229-243``) schreibt ein vollstaendiges
Ersatz-Objekt aus einer FESTEN Aufzaehlung, und ``save_config:139`` legt es
unveraendert ab. Ein Schluessel ohne Feld verschwaende also beim ersten
Speichern wieder und fiele zurueck auf die 5 Sekunden. Deshalb pruefen die
Tests unten Vorgaben UND Panel UND Speicherblock getrennt.

KEINE WERTANHEBUNG: Die drei bekommen die Vorgabe **5** - genau das, was heute
ueber die Ersatzregel gilt. Der Schluessel wird damit sichtbar und einstellbar,
das Verhalten bleibt unveraendert. Erhoehen entscheidet der Betreiber im Panel.

DIE GRENZE DIESES TESTS, ausdruecklich, damit er nicht mehr verspricht als er
haelt: Der Scanner findet nur ZEICHENKETTEN-Argumente. Aufrufe mit
``self.custom_id`` (die Mech-Knoepfe), ``self.action`` (Start/Stop/Restart),
``action_type`` (dienstintern) und ``command_name`` (Schraegstrich-Befehle)
sieht er nicht. Er prueft also die woertlichen Aufrufe - nicht alle.

DER VERTRAG GILT NUR IN EINE RICHTUNG. Schluessel, die in den Vorgaben stehen,
ohne dass jemand sie anfordert (``auto_refresh``, ``mech_music`` und weitere),
machen hier NICHT rot. Das sind eigene Befunde mit eigener Entscheidung des
Betreibers - dieser Test nimmt sie nicht vorweg.

``refresh`` WAR AUSGENOMMEN von den beiden Panel-Behauptungen, solange die
Betreiberfrage aus SPEC.md B10 offen war. Sie ist am 2026-09-19 entschieden
("refresh ins Panel"); die Ausnahme ist damit entfallen.

WIE HIER GEPRUEFT WIRD: Erwartung und Behauptung kommen aus verschiedenen
Quellen. Die **Erwartung** ist der Quelltext unter cogs/, services/, app/. Die
**Behauptung** sind das Vorgabe-Woerterbuch und die Panel-Vorlage. Zoege man
beides aus derselben Datei, waere es ein Spiegeltest.
"""

import re
from pathlib import Path

import pytest

from services.infrastructure.spam_protection_service import SpamProtectionService

PROJEKT = Path(__file__).resolve().parents[2]
VORLAGE = PROJEKT / "app" / "templates" / "_spam_protection_modal.html"
VERZEICHNISSE = ("cogs", "services", "app")

# Die vier Aufruf-Familien, die einen KNOPF-Schluessel entgegennehmen.
# get_command_cooldown fehlt bewusst: Es wird ausschliesslich mit einer
# Variablen gerufen (docker_control.py), hat also kein Literal zu bieten.
MUSTER = (
    re.compile(r'get_button_cooldown\(\s*"([a-z_]+)"\s*\)'),
    re.compile(r'is_on_cooldown\([^,]+,\s*"([a-z_]+)"\s*\)'),
    re.compile(r'add_user_cooldown\([^,]+,\s*"([a-z_]+)"\s*\)'),
)

# Siehe Kopftext: SPEC.md B10, entschieden 2026-09-19 - keine Ausnahme mehr.
OHNE_PANELFELD_ENTSCHIEDEN = set()


def _angeforderte_schluessel() -> dict:
    """Was der Quelltext woertlich anfordert: {schluessel: [fundstelle, ...]}."""
    gefunden = {}
    for verzeichnis in VERZEICHNISSE:
        for pfad in sorted((PROJEKT / verzeichnis).rglob("*.py")):
            text = pfad.read_text(encoding="utf-8", errors="replace")
            for nummer, zeile in enumerate(text.splitlines(), 1):
                for muster in MUSTER:
                    for schluessel in muster.findall(zeile):
                        ort = f"{pfad.relative_to(PROJEKT)}:{nummer}"
                        gefunden.setdefault(schluessel, []).append(ort)
    return gefunden


def _vorgaben(tmp_path) -> dict:
    return SpamProtectionService(config_dir=str(tmp_path))._get_default_config().button_cooldowns


def _vorlagentext() -> str:
    return VORLAGE.read_text(encoding="utf-8")


def _speicherblock() -> str:
    """Nur der button_cooldowns-Abschnitt des Speicherblocks.

    Eng abgegrenzt: Ein Name kann anderswo in der Datei stehen (als Feld, als
    Beschriftung) und trotzdem beim Speichern fehlen - genau der gemessene
    Fehlerfall. Die Suche muss deshalb auf diesen Abschnitt zielen.
    """
    text = _vorlagentext()
    anfang = text.index("button_cooldowns: {")
    return text[anfang:text.index("}", anfang)]


def test_der_scanner_findet_ueberhaupt_etwas():
    """Sicherung gegen ein stumpfes Werkzeug - muss VOR und NACH gruen sein.

    Greift der Scanner ins Leere - Muster geaendert, Pfad falsch -, waeren die
    Tests unten gruen, ohne irgendetwas zu belegen.
    """
    gefunden = _angeforderte_schluessel()

    assert len(gefunden) >= 6, (
        f"Nur {len(gefunden)} woertliche Schluessel gefunden: {sorted(gefunden)}. "
        "Das Aufrufmuster hat sich geaendert - dann pruefen die Tests unten nichts."
    )
    for bekannt in ("info", "logs"):
        assert bekannt in gefunden, (
            f"Der bekannte Schluessel {bekannt!r} fehlt im Scan - der Scanner ist blind."
        )


def test_die_vorgaben_sind_ueberhaupt_gefuellt(tmp_path):
    """Zweite Sicherung: Lese ich wirklich das Knopf-Woerterbuch?"""
    vorgaben = _vorgaben(tmp_path)

    assert len(vorgaben) >= 10, (
        f"Nur {len(vorgaben)} Knopf-Vorgaben gelesen: {sorted(vorgaben)}. "
        "Dann zeigt die Behauptung unten auf das falsche Woerterbuch."
    )
    assert vorgaben.get("info") == 3


def test_jeder_angeforderte_schluessel_steht_in_den_vorgaben(tmp_path):
    """DER BEFUND, erste Stufe: angefordert, aber nicht vorhanden."""
    gefunden = _angeforderte_schluessel()
    vorgaben = _vorgaben(tmp_path)

    fehlend = {k: v for k, v in gefunden.items() if k not in vorgaben}

    assert not fehlend, (
        "Diese Schluessel werden von lebendem Code angefordert, stehen aber in "
        "keinem Vorgabe-Woerterbuch. get_button_cooldown:186 liefert dafuer "
        "stumm 5 Sekunden, und der Betreiber kann den Wert nirgends sehen oder "
        "aendern:\n  "
        + "\n  ".join(f"{k!r} -> {', '.join(v)}" for k, v in sorted(fehlend.items()))
    )


def test_jeder_angeforderte_schluessel_hat_ein_panelfeld(tmp_path):
    """DER BEFUND, zweite Stufe: vorhanden, aber im Panel nicht einstellbar."""
    gefunden = set(_angeforderte_schluessel()) - OHNE_PANELFELD_ENTSCHIEDEN
    text = _vorlagentext()

    ohne_feld = sorted(k for k in gefunden if f'id="button_{k}"' not in text)

    assert not ohne_feld, (
        "Diese angeforderten Schluessel haben kein Eingabefeld im Panel und "
        f"sind damit nicht einstellbar: {ohne_feld}"
    )


def test_jeder_angeforderte_schluessel_ueberlebt_das_speichern(tmp_path):
    """DER BEFUND, dritte Stufe - und die, die ohne Messung niemand sieht.

    Der Speicherblock ist eine FESTE Aufzaehlung. Was dort fehlt, faellt beim
    ersten Speichern aus der Konfiguration, auch wenn Vorgabe und Feld
    existieren. Ohne diese Behauptung waere eine Korrektur gruen und trotzdem
    nach dem ersten Klick auf "Speichern" wirkungslos.
    """
    gefunden = set(_angeforderte_schluessel()) - OHNE_PANELFELD_ENTSCHIEDEN
    block = _speicherblock()

    verloren = sorted(k for k in gefunden if f"button_{k}" not in block)

    assert not verloren, (
        "Diese Schluessel fehlen im Speicherblock des Panels "
        "(_spam_protection_modal.html). Ein im Panel eingestellter Wert wird "
        "nie gespeichert; seit 1b77428 greift danach die Vorgabe (vorher die "
        f"5-Sekunden-Ersatzregel): {verloren}"
    )
