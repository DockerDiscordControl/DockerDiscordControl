# -*- coding: utf-8 -*-
"""Der Umschalt-Knopf ("refresh") bekommt einen Regler im Panel; der tote
Schluessel ``auto_refresh`` verschwindet aus den Vorgaben.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers. Entschieden ist SPEC.md B10: "refresh ins Panel".

DER BEFUND. ToggleButton bremst unter ``refresh`` (Vorgabe 5). Das Panel kennt
nur ``live_refresh`` - einen anderen Schluessel. Die Abklingzeit lag damit fest
und war nicht einstellbar. ``auto_refresh`` stand in den Vorgaben, ohne dass
irgendein Code ihn abfragt (gemessen: einziger Treffer ist der Eintrag selbst;
LiveLogView hat einen gleichnamigen PARAMETER, der mit dem Spamschutz nichts zu
tun hat).

Panel-Feld und Speicherzeile prueft der allgemeine Vertrag
(test_angeforderte_abklingschluessel_existieren.py), seit dort die Ausnahme fuer
``refresh`` entfallen ist. Hier steht, was er nicht sieht: Startwert,
Beschriftung, und dass der tote Eintrag weg ist.

WARUM auto_refresh AUS DEN VORGABEN DARF: Seit Commit 1b77428 ergaenzt
get_config fehlende Schluessel aus den Vorgaben; ein toter Eintrag dort landet
damit in jeder Konfiguration und in jeder GET-Antwort. Gespeicherte
Konfigurationen, die ihn schon enthalten, behalten ihn (Gespeichertes gewinnt)
- harmlos, weil niemand ihn fragt.
"""

import json
from pathlib import Path

from services.infrastructure.spam_protection_service import SpamProtectionService

PROJEKT = Path(__file__).resolve().parents[2]
VORLAGE = PROJEKT / "app" / "templates" / "_spam_protection_modal.html"


def test_refresh_steht_weiter_in_den_vorgaben(tmp_path):
    """Sicherung: Der Knopf behaelt seine Vorgabe von 5 Sekunden."""
    vorgaben = SpamProtectionService(config_dir=str(tmp_path))._get_default_config()
    assert vorgaben.button_cooldowns.get("refresh") == 5


def test_das_panelfeld_startet_mit_der_vorgabe():
    assert 'id="button_refresh" value="5"' in VORLAGE.read_text(encoding="utf-8")


def test_das_panelfeld_hat_eine_beschriftung():
    """Die Katalog-Paritaet sieht Jinjas _t(...) nicht - siehe
    test_mechdetails_hat_einen_regler.py."""
    assert "_t('web.spam.button_refresh')" in VORLAGE.read_text(encoding="utf-8")
    katalog = json.loads((PROJEKT / "locales" / "en.json").read_text(encoding="utf-8"))
    assert katalog.get("web.spam.button_refresh") == "Overview Toggle Button"


def test_auto_refresh_ist_aus_den_vorgaben_verschwunden(tmp_path):
    vorgaben = SpamProtectionService(config_dir=str(tmp_path))._get_default_config()
    assert "auto_refresh" not in vorgaben.button_cooldowns, (
        "auto_refresh steht noch in den Vorgaben, obwohl kein Code ihn fragt - "
        "er landet ueber die Ergaenzung in jeder Konfiguration."
    )
