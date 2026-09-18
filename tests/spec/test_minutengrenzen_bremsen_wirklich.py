# -*- coding: utf-8 -*-
"""Die Minutengrenzen im Panel muessen tatsaechlich bremsen.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND. Das Panel bietet zwei Felder an - "max. Befehle pro Minute" (20)
und "max. Knoepfe pro Minute" (30). Beide werden gespeichert, beide werden
ueber ``to_dict``/``from_dict`` sauber hin- und hergereicht - und **niemand
fragt sie je ab**.

Gemessen: Die beiden Namen kommen im gesamten Anwendungscode an genau acht
Stellen vor, alle in ``spam_protection_service.py`` - Feldbeschreibung
(:28-29), Einlesen (:40-41), Schreiben (:53-54), Vorgaben (:314, :325). Keine
einzige Stelle vergleicht einen Zaehler damit, und es gibt nirgends eine
Zaehlvorrichtung.

WAS DER BETREIBER DAVON SIEHT: Er stellt "max. 30 Knoepfe pro Minute" ein,
speichert, sieht den Wert beim naechsten Oeffnen wieder - und nichts bremst.
Genau die Gattung "unbemerkt", die sich nur zeigt, wenn jemand es darauf
anlegt.

WARUM ES BISHER NIE AUFFIEL: Es gibt keine Stelle, an der ein Druck GEZAEHLT
wird. Die Abklingzeit je Knopf merkt sich nur den LETZTEN Zeitpunkt
(``_user_cooldowns``), nicht die Anzahl.

GEZAEHLT WIRD DER ANGENOMMENE DRUCK, nicht die Nachfrage - also in
``add_user_cooldown``, nicht in ``is_on_cooldown``. Wuerde schon das Pruefen
zaehlen, verbrauchte eine abgewiesene Wiederholung weiteres Kontingent, und
rechtmaessige Nutzung waere gedrosselt. Der Test unten haelt beides fest.

DIE UHR: Das Fenster benutzt ``time.time()`` - dieselbe Uhr wie der Rest der
Datei. ``time.monotonic()`` waere fachlich sauberer und ist das, was
``SlidingWindowRateLimiter`` (translation_service.py:353) benutzt, ist hier
aber FALSCH: Die vorhandenen Tests frieren die Uhr ueber
``monkeypatch.setattr(time, "time", ...)`` ein
(test_infrastructure_services.py:822, test_docker_infra_gaps.py:1594). Mit
``monotonic`` liefen in EINEM Dienst zwei Uhren - ``_user_cooldowns``
eingefroren, das Fenster real. Ein Fehler, der nur unter Attrappen auftritt
und im Betrieb unsichtbar bleibt.

VERSCHIEDENE KNOPFNAMEN IM TEST, und das ist kein Zufall: Jeder ``probe_N``
faellt auf die 5-Sekunden-Ersatzregel (``get_button_cooldown:186``), und keiner
sperrt den naechsten. Was nach N Druecken noch bremst, kann deshalb NUR die
Minutengrenze sein - nicht die Abklingzeit je Knopf.

ABGRENZUNG: Dieser Test aendert nichts an der Frage, welche der 13 Stellen den
Dienst ueberhaupt fragen. Die meisten fuehren eigene Abklingzeit-Buchhaltung
und erreichen ``is_on_cooldown`` gar nicht - ein eigener Befund mit eigener
Entscheidung. Hier geht es nur darum, dass die Grenze im Dienst ueberhaupt
existiert und beisst.
"""

import time

import pytest

from services.infrastructure.spam_protection_service import SpamProtectionService

NUTZER = 5150
ANDERER = 6270


def _dienst(tmp_path):
    return SpamProtectionService(config_dir=str(tmp_path))


def _fuellen(dienst, nutzer, anzahl, praefix="probe"):
    """Traegt ``anzahl`` angenommene Druecke ein - jeder mit eigenem Namen."""
    for i in range(anzahl):
        dienst.add_user_cooldown(nutzer, f"{praefix}_{i}")


def test_die_beiden_grenzen_sind_ueberhaupt_verschieden(tmp_path):
    """Sicherung gegen ein stumpfes Werkzeug.

    Die Tests unten unterscheiden Knopf- und Befehlsgrenze. Staenden beide auf
    demselben Wert, koennte eine Verwechslung im Code unbemerkt bleiben.
    """
    vorgaben = _dienst(tmp_path)._get_default_config()

    assert vorgaben.max_commands_per_minute == 20
    assert vorgaben.max_buttons_per_minute == 30
    assert vorgaben.max_commands_per_minute != vorgaben.max_buttons_per_minute


def test_bis_zur_grenze_wird_nicht_gebremst(tmp_path):
    """Abgrenzung, und die wichtigere Haelfte des Befunds.

    Eine Bremse, die zu frueh greift, waere schlimmer als keine. Genau
    ``max_buttons_per_minute`` Druecke muessen durchgehen - der naechste nicht.

    DIE ZAEHLUNG, ausdruecklich, weil hier ein Abweichungsfehler um eins lauert:
    Bei "hoechstens 30 pro Minute" sind 30 Druecke erlaubt und der 31. wird
    abgewiesen. Dieser Test fuellt also ``grenze - 1`` und prueft, dass der
    ``grenze``-te noch durchgeht; der Test darunter fuellt ``grenze`` und prueft,
    dass der naechste faellt. Zusammen nageln sie die Kante fest - eine
    Korrektur, die einen Druck zu viel durchlaesst, wird rot.
    """
    dienst = _dienst(tmp_path)
    grenze = dienst._get_default_config().max_buttons_per_minute

    _fuellen(dienst, NUTZER, grenze - 1)

    assert dienst.is_on_cooldown(NUTZER, "probe_frisch") is False, (
        f"Nach {grenze - 1} Druecken wird bereits gebremst, obwohl erst der "
        f"{grenze + 1}. abgewiesen werden darf. Die Grenze greift zu frueh."
    )


def test_ueber_der_grenze_wird_gebremst(tmp_path):
    """DER BEFUND: Die Knopfgrenze aus dem Panel bremst nicht."""
    dienst = _dienst(tmp_path)
    grenze = dienst._get_default_config().max_buttons_per_minute

    _fuellen(dienst, NUTZER, grenze)

    assert dienst.is_on_cooldown(NUTZER, "probe_frisch") is True, (
        f"Nach {grenze} angenommenen Druecken in derselben Minute - dem "
        f"Kontingent aus max_buttons_per_minute - wird der naechste immer noch "
        "nicht abgewiesen. Das Panel bietet das Feld an, speichert es, zeigt es "
        "wieder an - und niemand fragt es ab."
    )


def test_die_abfuhr_nennt_eine_brauchbare_restzeit(tmp_path):
    """DER BEFUND, zweite Haelfte: 'warte 0.0 Sekunden' ist keine Auskunft.

    Alle Aufrufer fragen nach ``is_on_cooldown`` sofort
    ``get_remaining_cooldown``. Rechnet das weiterhin nur aus
    ``_user_cooldowns``, steht beim Nutzer 0.0 - denn der frische Knopfname hat
    dort gar keinen Eintrag. Die Restzeit muss aus dem FENSTER kommen.
    """
    dienst = _dienst(tmp_path)
    grenze = dienst._get_default_config().max_buttons_per_minute

    _fuellen(dienst, NUTZER, grenze)
    rest = dienst.get_remaining_cooldown(NUTZER, "probe_frisch")

    assert rest > 0.0, (
        "Der Knopf ist gesperrt, aber die gemeldete Restzeit ist 0.0 - der "
        "Nutzer liest 'bitte warte 0.0 Sekunden' und darf trotzdem nicht."
    )
    assert rest <= 60.0, (
        f"Die Restzeit betraegt {rest}s. Ein Minutenfenster kann hoechstens "
        "60 Sekunden Wartezeit erzeugen."
    )


def test_das_fenster_gleitet(tmp_path, monkeypatch):
    """Abgrenzung: Es ist ein Minutenfenster, keine Gesamtsumme.

    Ohne diesen Test koennte eine Korrektur schlicht alle Druecke zaehlen und
    den Nutzer nach der Grenze dauerhaft aussperren.
    """
    dienst = _dienst(tmp_path)
    grenze = dienst._get_default_config().max_buttons_per_minute

    monkeypatch.setattr(time, "time", lambda: 1000.0)
    _fuellen(dienst, NUTZER, grenze)
    assert dienst.is_on_cooldown(NUTZER, "probe_frisch") is True

    monkeypatch.setattr(time, "time", lambda: 1061.0)
    assert dienst.is_on_cooldown(NUTZER, "probe_frisch") is False, (
        "61 Sekunden spaeter bremst die Minutengrenze immer noch - dann ist es "
        "kein gleitendes Fenster, sondern eine Gesamtsumme, und der Nutzer "
        "bleibt dauerhaft ausgesperrt."
    )


def test_die_grenze_gilt_je_nutzer(tmp_path):
    """Abgrenzung: Ein Nutzer darf nicht alle anderen aussperren."""
    dienst = _dienst(tmp_path)
    grenze = dienst._get_default_config().max_buttons_per_minute

    _fuellen(dienst, NUTZER, grenze + 1)

    assert dienst.is_on_cooldown(ANDERER, "probe_frisch") is False, (
        "Der Druck EINES Nutzers bremst einen anderen - dann ist das Fenster "
        "global statt je Nutzer, und ein einzelner Nutzer legt den Kanal lahm."
    )


def test_abgeschaltet_wird_nichts_gezaehlt(tmp_path):
    """Abgrenzung: Der Betreiber kann den Schutz abschalten.

    Haelt das Fenster auch bei abgeschaltetem Schutz mit, sammelte sich dort
    Zustand an, der beim Wiedereinschalten sofort sperrt.
    """
    from unittest.mock import patch

    dienst = _dienst(tmp_path)
    grenze = dienst._get_default_config().max_buttons_per_minute

    with patch.object(dienst, "is_enabled", return_value=False):
        _fuellen(dienst, NUTZER, grenze + 5)

    assert dienst.is_on_cooldown(NUTZER, "probe_frisch") is False


def test_nachfragen_verbraucht_kein_kontingent(tmp_path):
    """Abgrenzung gegen die naheliegendste Fehlkorrektur.

    Gezaehlt wird der ANGENOMMENE Druck, nicht die Nachfrage. Zaehlte schon
    ``is_on_cooldown``, verbrauchte jede abgewiesene Wiederholung weiteres
    Kontingent - und wer einmal gebremst wurde, kaeme nie wieder heraus.
    """
    dienst = _dienst(tmp_path)
    grenze = dienst._get_default_config().max_buttons_per_minute

    for _ in range(grenze * 3):
        dienst.is_on_cooldown(NUTZER, "probe_frisch")

    assert dienst.is_on_cooldown(NUTZER, "probe_frisch") is False, (
        f"Nach {grenze * 3} reinen ABFRAGEN ohne einen einzigen angenommenen "
        "Druck wird gebremst. Dann zaehlt die Pruefung selbst mit."
    )
