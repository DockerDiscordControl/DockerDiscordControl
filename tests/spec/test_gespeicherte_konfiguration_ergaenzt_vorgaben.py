# -*- coding: utf-8 -*-
"""Eine gespeicherte Spamschutz-Konfiguration muss fehlende Schluessel aus den
Vorgaben ergaenzen - nicht stumm auf 5 Sekunden fallen.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers. Die VERHALTENSAENDERUNG ist entschieden:
"Vorgaben ergaenzen".

DER BEFUND. Sobald ``config/channels_config.json`` existiert - in jeder echten
Installation -, liest ``get_config`` NUR die gespeicherten Schluessel
(``from_dict`` uebernimmt sie ohne Ergaenzung). Die Vorgabe-Woerterbuecher
(``_get_default_config``) werden dann nie gelesen. Jeder fehlende Schluessel
faellt in ``get_button_cooldown``/``get_command_cooldown`` auf die Ersatzregel
von 5 Sekunden. Fehlt der ganze Abschnitt, bremst ALLES mit 5.

DAS PANEL LUEGT DABEI: GET /api/spam-protection liefert nur die gespeicherten
Schluessel; fuer fehlende behalten die Felder ihre HTML-Startwerte. Der
Betreiber liest "Restart 15", "Logs 10" - der Bot bremst mit 5, bis er einmal
speichert.

MEIN EIGENER ANTEIL: Die drei Info-Knoepfe fragen seit Commit e87b170
``edit_info``/``protected_info``/``protected_info_edit`` statt ``info``. In einer
vorher gespeicherten Konfiguration fehlen diese Schluessel - dort bremsen sie
seitdem mit 5 statt 3. Der Commit-Text sagte "unveraendert"; das galt nur fuer
Neuinstallationen.

ZWEI STARTWERTE IM PANEL wichen ausserdem von den Vorgaben ab (restart 15 statt
20, live_refresh 3 statt 5). Mit der Ergaenzung zeigt das Panel fuer fehlende
Schluessel die Vorgabe; die Startwerte erscheinen nur noch, wenn das Laden
scheitert - sie sollen dann trotzdem dieselbe Zahl nennen.

ABGRENZUNG: Gespeicherte Werte gewinnen immer, auch unbekannte Schluessel
bleiben erhalten. ``from_dict`` bleibt unveraendert - es baut auch die
Nutzlast der POST-Route, und dort soll nichts hinzugedichtet werden.
"""

import json
import re
from pathlib import Path

import pytest

from services.infrastructure.spam_protection_service import SpamProtectionService

VORLAGE = Path(__file__).resolve().parents[2] / "app" / "templates" / "_spam_protection_modal.html"

GESPEICHERT = {
    "spam_protection": {
        "command_cooldowns": {"ping": 9},
        "button_cooldowns": {"restart": 7, "info": 3, "eigener_knopf": 12},
        "global_settings": {"enabled": True},
    }
}


def _dienst(tmp_path, inhalt=GESPEICHERT):
    dienst = SpamProtectionService(config_dir=str(tmp_path))
    dienst.config_file.write_text(json.dumps(inhalt), encoding="utf-8")
    return dienst


def _vorgaben(tmp_path):
    return SpamProtectionService(config_dir=str(tmp_path / "leer"))._get_default_config()


def test_die_vorgaben_unterscheiden_sich_von_der_ersatzregel(tmp_path):
    """Sicherung: Nur Schluessel, deren Vorgabe NICHT 5 ist, koennen den Befund
    zeigen. Aendert sich eine davon auf 5, waere der Test unten hohl."""
    vorgaben = _vorgaben(tmp_path)
    assert vorgaben.button_cooldowns["edit_info"] == 3
    assert vorgaben.button_cooldowns["logs"] == 10
    assert vorgaben.button_cooldowns["mech_donate"] == 10
    assert vorgaben.command_cooldowns["serverstatus"] == 30


def test_gespeicherte_werte_gewinnen(tmp_path):
    """Abgrenzung: Die Ergaenzung darf nichts Gespeichertes ueberschreiben -
    auch nicht, wenn die Vorgabe anders lautet (restart: 20)."""
    dienst = _dienst(tmp_path)
    assert dienst.get_button_cooldown("restart") == 7
    assert dienst.get_command_cooldown("ping") == 9
    assert dienst.get_config().data.button_cooldowns["eigener_knopf"] == 12


@pytest.mark.parametrize("name,erwartet", [
    ("edit_info", 3),            # meine Regression aus e87b170
    ("protected_info", 3),
    ("protected_info_edit", 3),
    ("logs", 10),
    ("mech_donate_4711", 10),    # ueber die Praefix-Logik
])
def test_fehlende_knopfschluessel_kommen_aus_den_vorgaben(tmp_path, name, erwartet):
    """DER BEFUND: fehlender Schluessel -> Ersatzregel 5 statt Vorgabe."""
    dienst = _dienst(tmp_path)
    assert dienst.get_button_cooldown(name) == erwartet, (
        f"{name!r} fehlt in der gespeicherten Konfiguration und bremst mit "
        f"{dienst.get_button_cooldown(name)} statt der Vorgabe {erwartet}."
    )


def test_fehlende_befehlsschluessel_kommen_aus_den_vorgaben(tmp_path):
    """DER BEFUND, Befehlsseite."""
    assert _dienst(tmp_path).get_command_cooldown("serverstatus") == 30


def test_ohne_abschnitt_gelten_die_vorgaben(tmp_path):
    """DER BEFUND, schaerfste Form: Datei vorhanden, Abschnitt fehlt - heute
    bremst dann jeder Knopf und jeder Befehl mit 5."""
    dienst = _dienst(tmp_path, {"channels": {}})
    assert dienst.get_button_cooldown("logs") == 10
    assert dienst.get_command_cooldown("serverstatus") == 30


def test_das_panel_bekommt_die_ergaenzten_werte(tmp_path):
    """DER BEFUND, Anzeige: get_config ist die Quelle der GET-Route. Fehlt der
    Schluessel dort, zeigt das Panel seinen HTML-Startwert statt der Zahl, nach
    der gebremst wird."""
    angezeigt = _dienst(tmp_path).get_config().data.to_dict()["button_cooldowns"]
    assert angezeigt.get("edit_info") == 3, sorted(angezeigt)


def test_die_ergaenzung_veraendert_die_vorgaben_nicht(tmp_path):
    """Abgrenzung: Gespeichertes darf nicht in die Vorgaben zuruecklaufen."""
    dienst = _dienst(tmp_path)
    dienst.get_config()
    assert dienst._get_default_config().button_cooldowns["restart"] == 20


def test_panel_startwerte_entsprechen_den_vorgaben(tmp_path):
    """Die Startwerte erscheinen nur, wenn das Laden scheitert - dann sollen sie
    dieselbe Zahl nennen, nach der ohne gespeicherten Wert gebremst wird."""
    felder = dict(re.findall(r'id="((?:button|cooldown)_[a-z_]+)" value="(\d+)"',
                             VORLAGE.read_text(encoding="utf-8")))
    assert len(felder) >= 25, f"Nur {len(felder)} Felder gefunden - Muster blind?"
    vorgaben = _vorgaben(tmp_path)
    abweichend = []
    for praefix, woerterbuch in (("button_", vorgaben.button_cooldowns),
                                 ("cooldown_", vorgaben.command_cooldowns)):
        for feld, wert in felder.items():
            if feld.startswith(praefix) and feld[len(praefix):] in woerterbuch:
                if int(wert) != woerterbuch[feld[len(praefix):]]:
                    abweichend.append(f"{feld}: Panel {wert}, Vorgabe {woerterbuch[feld[len(praefix):]]}")
    assert not abweichend, abweichend
