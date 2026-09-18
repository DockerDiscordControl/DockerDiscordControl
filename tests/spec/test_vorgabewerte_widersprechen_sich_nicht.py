# -*- coding: utf-8 -*-
"""Die Vorgabewerte der Spam-Bremse duerfen sich nicht widersprechen.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND (Stufe 4, Nachlese zur Spam-Bremse).

Fuer die Knopfgrenze je Minute gibt es DREI Stellen, die einen Vorgabewert
nennen, und sie sind sich nicht einig::

    SpamProtectionConfig.from_dict          :41   -> 30
    SpamProtectionService._get_default_config :315 -> 35
    app/templates/_spam_protection_modal.html :51  -> 30

Bei der BEFEHLSgrenze sagen dieselben drei Stellen uebereinstimmend 20
(:40, :314, Vorlage :46). Der Widerspruch betrifft also genau ein Feld -
gemessen, nicht vermutet.

WAS DER BETREIBER DAVON SIEHT: Welche Zahl gilt, haengt davon ab, ob
``config/channels_config.json`` existiert. Fehlt die Datei, nimmt
``get_config:103-106`` den Weg ueber ``_get_default_config`` -> 35. Ist sie da,
laeuft es ueber ``from_dict`` -> 30. Das Fenster im Panel zeigt unterdessen 30
(``:51``), bis die Werte per Abruf ueberschrieben werden (``:185-186``). Der
Betreiber liest im Panel eine Zahl, die nicht die ist, nach der gebremst wird.

ABGRENZUNG - was dieser Test AUSDRUECKLICH NICHT tut: Er hebt nichts an. Der
Betreiber hat festgelegt, dass das Panel bestimmt, was gilt; hier wird nur der
Widerspruch beseitigt. Die Mehrheit der Stellen (2 zu 1) und das Panel nennen
30, also gilt 30. Wer den Wert aendern will, tut das weiterhin im Panel.

NICHT TEIL DIESES BEFUNDS, aber bei der Messung geprueft und hier festgehalten,
damit niemand es zweimal untersuchen muss:

* ``from_dict({})`` liefert LEERE Abklingzeit-Woerterbuecher, waehrend
  ``_get_default_config`` 14 Befehls- und 15 Knopfeintraege liefert. Das ist
  KEIN Schutzausfall: ``get_button_cooldown:186`` und
  ``get_command_cooldown:166`` haben eine Ersatzregel von 5 Sekunden. Es
  entfaellt nur die Abstufung.
* Dieser Leer-Weg ist produktiv NICHT erreichbar. ``channels_config.json``
  existiert auf der Produktivinstanz nicht (gemessen 2026-09-18); einziger
  Schreiber ist ``save_config:139``, und der schreibt den Abschnitt immer mit.
  Die Migration legt die Datei bei ``config_migration_service.py:381`` zwar an,
  loescht sie aber bei ``:394`` ueber
  ``cleanup_legacy_files_after_migration:141-149`` wieder. Der Lader
  (``config_loader_service.py:419``) stellt ``config['spam_protection']``
  bereit, aber niemand baut daraus ein ``SpamProtectionConfig`` - die einzigen
  Leser sind ``config_validation_service.py:145,198``.

WIE HIER GEPRUEFT WIRD: ueber die drei Quellen selbst. Der Dienst wird mit
``tmp_path`` gebaut - ``__init__:87`` legt sein Verzeichnis an, und das darf
niemals das echte ``config/`` sein. ``_get_default_config`` liest keine Datei,
der Zugriff ist also rein.
"""

import re
from pathlib import Path

import pytest

from services.infrastructure.spam_protection_service import (
    SpamProtectionConfig,
    SpamProtectionService,
)

PROJEKTWURZEL = Path(__file__).resolve().parents[2]
VORLAGE = PROJEKTWURZEL / "app" / "templates" / "_spam_protection_modal.html"


def _wert_aus_vorlage(feld_id: str) -> int:
    """Liest das ``value``-Attribut des Eingabefeldes mit dieser Kennung.

    Bewusst eng: Gesucht wird die Zeile MIT der Kennung, und daraus das
    ``value``. Ein Ausdruck ueber die ganze Datei koennte das Nachbarfeld
    erwischen - genau der Weg, auf dem ein Rot aus dem falschen Grund
    entstuende.
    """
    text = VORLAGE.read_text(encoding="utf-8")
    for zeile in text.splitlines():
        if f'id="{feld_id}"' in zeile:
            treffer = re.search(r'value="(\d+)"', zeile)
            if treffer:
                return int(treffer.group(1))
            raise AssertionError(
                f"Feld {feld_id} gefunden, aber ohne numerisches value: {zeile.strip()!r}"
            )
    raise AssertionError(f"Feld {feld_id} in {VORLAGE.name} nicht gefunden.")


def test_die_vorlage_ist_lesbar_und_nennt_beide_felder():
    """Waechter gegen ein stumpfes Werkzeug.

    Muss VOR und NACH der Korrektur gruen sein. Waere er rot, pruefte der Test
    unten nicht den Widerspruch, sondern nur seine eigene Dateisuche - ein
    wertloses Rot.
    """
    assert VORLAGE.is_file(), (
        f"{VORLAGE} fehlt - dann misst der Test unten die Vorlage gar nicht."
    )
    assert _wert_aus_vorlage("maxCommandsPerMinute") > 0
    assert _wert_aus_vorlage("maxButtonsPerMinute") > 0


def test_befehlsgrenze_ist_an_allen_drei_stellen_gleich():
    """Abgrenzung: Hier stimmt es bereits, und das muss so bleiben.

    Ohne diesen Test koennte eine Korrektur der Knopfgrenze die Befehlsgrenze
    mitreissen, ohne dass etwas anschlaegt.
    """
    aus_dict = SpamProtectionConfig.from_dict({}).max_commands_per_minute
    aus_vorlage = _wert_aus_vorlage("maxCommandsPerMinute")

    assert aus_dict == 20
    assert aus_vorlage == 20


def test_befehlsgrenze_auch_im_dienst_gleich(tmp_path):
    """Dieselbe Abgrenzung fuer den dritten Weg, den Dienst."""
    dienst = SpamProtectionService(config_dir=str(tmp_path))

    assert dienst._get_default_config().max_commands_per_minute == 20


def test_knopfgrenze_ist_an_allen_drei_stellen_gleich(tmp_path):
    """DER BEFUND: Drei Vorgaben fuer ein Feld, und eine schert aus.

    Die Zahlen werden AUSDRUECKLICH festgenagelt, nicht nur auf Gleichheit
    geprueft. Sonst waere der Test auch dann gruen, wenn jemand alle drei
    Stellen auf 35 setzte - und das waere eine Werterhoehung, die der Betreiber
    ausdruecklich dem Panel vorbehalten hat.
    """
    dienst = SpamProtectionService(config_dir=str(tmp_path))

    aus_dict = SpamProtectionConfig.from_dict({}).max_buttons_per_minute
    aus_dienst = dienst._get_default_config().max_buttons_per_minute
    aus_vorlage = _wert_aus_vorlage("maxButtonsPerMinute")

    assert aus_dict == 30, "from_dict (:41) nennt nicht mehr 30."
    assert aus_vorlage == 30, "Die Vorlage (:51) nennt nicht mehr 30."
    assert aus_dienst == 30, (
        "_get_default_config (:315) nennt "
        f"{aus_dienst} statt 30. Damit haengt die geltende Knopfgrenze davon "
        "ab, ob config/channels_config.json existiert: fehlt sie, bremst der "
        "Dienst nach dieser Zahl (get_config:103-106); ist sie da, nach der "
        "aus from_dict. Das Panel zeigt unterdessen 30. Der Betreiber liest "
        "eine andere Zahl, als die, nach der gebremst wird."
    )
