# -*- coding: utf-8 -*-
"""Ein Knopf muss nach dem KNOPF-Regler bremsen, auch wenn er wie ein Befehl heisst.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND. ``is_on_cooldown``, ``get_remaining_cooldown`` und
``add_user_cooldown`` entscheiden "Befehl oder Knopf?" ueber eine fest
verdrahtete NAMENSLISTE (``_BEFEHLSNAMEN``: serverstatus, ss, control, info,
help, ping, donate, command, language, forceupdate, start, stop, restart).
Heisst ein KNOPF wie ein Befehl, bekommt er die Befehls-Dauer und zaehlt ins
Befehls-Minutenfenster::

    Knopf "info"     -> Befehl /info   5 s   statt Knopf-Regler info     3 s
    Knopf "help"     -> Befehl /help   3 s   statt Knopf-Regler help     5 s
    Knopf "restart"  -> Befehl         15 s  statt Knopf-Regler restart 20 s

Betroffen sind der Info-Knopf der Steuerung, InfoDropdownButton, HelpButton
und die Start/Stop/Restart-Knoepfe. Der Betreiber stellt im Panel den Regler
"Info-Knopf" ein - und es bremst der Regler des /info-BEFEHLS. Dieselbe Gattung
wie bei den Mech-Knoepfen (falscher Regler gilt), nur ueber einen anderen Weg.

EIN TEIL DAVON IST MEIN EIGENER FEHLER: InfoDropdownButton und HelpButton
fragten vor der Umstellung auf den Dienst ausdruecklich ``get_button_cooldown``.
Die Umstellung (Commit 3785fc0) schickt sie durch die Namensliste. Die Tests
jenes Commits prueften das ARGUMENT ("info", "help"), nicht die wirksame Dauer
- und haben es deshalb nicht bemerkt.

DIE KORREKTUR: Alle heutigen Aufrufer der drei Methoden sind KNOEPFE (gemessen;
Befehle bremsen ueber einen eigenen Weg in docker_control.py). Knopf wird
deshalb die Vorgabe; wer einen Befehl bremsen will, sagt es ausdruecklich mit
``art="befehl"``. Die Namensliste entfaellt - samt ihren bekannten Macken
("ss" steht in keinem Woerterbuch, "donatebroadcast" und "info_edit" fehlen).

WIE HIER GEPRUEFT WIRD: auf Dienstebene, weil der Fehler dort sitzt, mit einem
echten Dienst und eingefrorener Uhr. Das ist dieselbe Uhr-Ersetzung, die die
vorhandenen Tests benutzen (``time.time`` im Modul), damit Dienst und Test
dieselbe Zeit sehen.

ZWEI FALLEN, vorab abgedichtet:

1. Stuenden Knopf- und Befehlswert gleich, waere jede Dauer-Pruefung hohl. Der
   erste Waechter haelt fest, dass sie sich fuer info, help und restart
   UNTERSCHEIDEN.
2. ``art=`` gibt es vor der Korrektur nicht. Ein Aufruf damit waere ein FEHLER
   (TypeError) statt eines Fehlschlags. Der Abgrenzungstest prueft deshalb
   zuerst die Signatur und scheitert sauber an einer Behauptung.
"""

import inspect
import time

import pytest

from services.infrastructure.spam_protection_service import SpamProtectionService

NUTZER = 4411
JETZT = 50_000.0


def _dienst(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: JETZT)
    return SpamProtectionService(config_dir=str(tmp_path))


def test_knopf_und_befehlsregler_unterscheiden_sich(tmp_path):
    """Waechter: Ohne verschiedene Werte bewiese keine Dauer-Pruefung etwas."""
    dienst = SpamProtectionService(config_dir=str(tmp_path))

    for name in ("info", "help", "restart"):
        knopf = dienst.get_button_cooldown(name)
        befehl = dienst.get_command_cooldown(name)
        assert knopf != befehl, (
            f"{name!r}: Knopf-Regler ({knopf}) und Befehls-Regler ({befehl}) "
            "stehen gleich - die Tests unten koennten den Unterschied nicht sehen."
        )


@pytest.mark.parametrize("name", ["info", "help", "restart"])
def test_ein_knopf_bremst_nach_seinem_knopfregler(tmp_path, monkeypatch, name):
    """DER BEFUND: Gebremst wird nach dem Befehls-Regler gleichen Namens."""
    dienst = _dienst(tmp_path, monkeypatch)
    erwartet = dienst.get_button_cooldown(name)
    befehl = dienst.get_command_cooldown(name)

    dienst.add_user_cooldown(NUTZER, name)
    rest = dienst.get_remaining_cooldown(NUTZER, name)

    assert rest == pytest.approx(erwartet), (
        f"Der Knopf {name!r} wird {rest:.1f} s gesperrt - das ist der Regler des "
        f"BEFEHLS ({befehl} s), nicht der des Knopfes ({erwartet} s). Der "
        "Betreiber stellt im Panel den Knopf-Regler ein, und er bewegt nichts."
    )


@pytest.mark.parametrize("name", ["info", "help", "restart"])
def test_ein_knopf_ist_nach_seinem_knopfregler_wieder_frei(tmp_path, monkeypatch, name):
    """DER BEFUND, Wirkung: Nach Ablauf der Knopf-Dauer muss er wieder gehen -
    und nicht vorher."""
    dienst = _dienst(tmp_path, monkeypatch)
    dauer = dienst.get_button_cooldown(name)

    dienst.add_user_cooldown(NUTZER, name)

    monkeypatch.setattr(time, "time", lambda: JETZT + dauer - 0.5)
    assert dienst.is_on_cooldown(NUTZER, name) is True, (
        f"{name!r} ist {dauer - 0.5} s nach dem Druck schon wieder frei, obwohl "
        f"der Knopf-Regler {dauer} s verlangt."
    )
    monkeypatch.setattr(time, "time", lambda: JETZT + dauer + 0.5)
    assert dienst.is_on_cooldown(NUTZER, name) is False, (
        f"{name!r} ist {dauer + 0.5} s nach dem Druck noch gesperrt, obwohl der "
        f"Knopf-Regler nur {dauer} s verlangt."
    )


def test_ein_knopf_zaehlt_ins_knopf_minutenfenster(tmp_path, monkeypatch):
    """DER BEFUND, zweite Folge: "info" zaehlt heute ins BEFEHLS-Fenster.

    29 Knopf-Druecke unter neutralen Namen plus ein Druck auf "info" machen
    das Knopf-Kontingent (30) voll - der naechste Knopf muss abgewiesen werden.
    Zaehlt "info" ins Befehls-Fenster, bleibt das Knopf-Fenster bei 29.
    """
    dienst = _dienst(tmp_path, monkeypatch)
    grenze = dienst._get_default_config().max_buttons_per_minute

    for i in range(grenze - 1):
        dienst.add_user_cooldown(NUTZER, f"probe_{i}")
    dienst.add_user_cooldown(NUTZER, "info")

    assert dienst.is_on_cooldown(NUTZER, "probe_frisch") is True, (
        f"Nach {grenze - 1} neutralen Knopf-Druecken und einem 'info'-Druck ist "
        "das Knopf-Kontingent nicht voll - 'info' wurde ins Befehls-Fenster "
        "gezaehlt."
    )


def test_befehle_behalten_ihren_regler_wenn_sie_es_sagen(tmp_path, monkeypatch):
    """Abgrenzung: Ein BEFEHL, der sich als solcher ausweist, bremst nach dem
    Befehls-Regler. Sonst waere die Korrektur nur eine Umkehrung des Fehlers.

    Zuerst die Signatur - ohne ``art`` waere der Aufruf ein TypeError, also ein
    Fehler statt eines Fehlschlags.
    """
    for methode in ("is_on_cooldown", "get_remaining_cooldown", "add_user_cooldown"):
        parameter = inspect.signature(getattr(SpamProtectionService, methode)).parameters
        assert "kind" in parameter, (
            f"{methode} kennt keinen Parameter 'art' - ein Befehl kann sich nicht "
            "als solcher ausweisen."
        )

    dienst = _dienst(tmp_path, monkeypatch)
    dienst.add_user_cooldown(NUTZER, "info", kind="command")

    assert dienst.get_remaining_cooldown(NUTZER, "info", kind="command") == pytest.approx(
        dienst.get_command_cooldown("info")
    )


def test_befehl_und_knopf_gleichen_namens_teilen_keinen_eimer(tmp_path, monkeypatch):
    """Abgrenzung: /info und der Info-KNOPF duerfen einander nicht sperren.

    Sobald Befehle sich als solche ausweisen, laege es nahe, beide unter
    "<nutzer>:info" abzulegen - dann sperrte ein Klick auf den Info-Knopf den
    /info-Befehl und umgekehrt. Der Schluesselraum der Befehle ist deshalb ein
    eigener.
    """
    dienst = _dienst(tmp_path, monkeypatch)

    dienst.add_user_cooldown(NUTZER, "info")
    assert dienst.is_on_cooldown(NUTZER, "info", kind="command") is False, (
        "Ein Druck auf den Info-KNOPF sperrt den /info-BEFEHL - beide teilen "
        "sich einen Eimer."
    )

    dienst.add_user_cooldown(NUTZER, "help", kind="command")
    assert dienst.is_on_cooldown(NUTZER, "help") is False, (
        "Der /help-BEFEHL sperrt den Hilfe-KNOPF - beide teilen sich einen Eimer."
    )


def test_ein_tippfehler_bei_der_art_scheitert_laut(tmp_path, monkeypatch):
    """Abgrenzung: "befhel" darf nicht still als Knopf gelten.

    Die Aufrufer fangen nur (RuntimeError, AttributeError, KeyError); ein
    ValueError dringt also durch und faellt auf, statt einen Befehl
    unbemerkt nach dem Knopf-Regler zu bremsen.
    """
    dienst = _dienst(tmp_path, monkeypatch)

    for methode in (dienst.is_on_cooldown, dienst.get_remaining_cooldown,
                    dienst.add_user_cooldown):
        with pytest.raises(ValueError):
            methode(NUTZER, "info", kind="befhel")
