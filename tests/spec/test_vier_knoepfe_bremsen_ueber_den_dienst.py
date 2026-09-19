# -*- coding: utf-8 -*-
"""Vier weitere Knoepfe muessen ueber den Spam-Dienst bremsen, nicht am Objekt.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND. Vier Knoepfe holen vom Dienst nur die DAUER und legen ihren
Zeitstempel als ATTRIBUT AUF SICH SELBST ab
(``setattr(self, f'_last_click_{user_id}', ...)``)::

    InfoDropdownButton    control_ui.py:1425            "info"
    AdminButton           control_ui.py:1791            "admin"
    HelpButton            control_ui.py:2102            "help"
    TaskManagementButton  status_info_integration.py:1182  "tasks"

``is_on_cooldown`` und ``add_user_cooldown`` werden nie gerufen. Die
MINUTENGRENZE aus dem Panel wirkt fuer diese vier deshalb nicht - sie zaehlt in
``add_user_cooldown``, und dort kommen sie nie an.

DIE ABLAGE IST AUSSERDEM FLUECHTIG: Das Attribut haengt am Knopf-Objekt. Wird
die Ansicht neu gebaut - und das geschieht bei jeder Aktualisierung -, ist die
Sperre weg. Der Schutz haelt also nur, solange dasselbe Objekt lebt.

MITGENOMMEN, weil es dieselbe Zeile betrifft: Alle vier senden heute eine
UNUEBERSETZTE f-Zeichenkette (``f"⏰ Please wait ... seconds."``). Im Baum stehen
neun solcher Stellen gegen sieben uebersetzte - die unuebersetzte Form ist an
den Eigenbau-Stellen die Mehrheit. Die Umstellung aufs Hausmuster benutzt den
vorhandenen Katalogeintrag.

KEINE NEUEN SCHLUESSEL: "info", "admin", "help" und "tasks" existieren bereits
in den Vorgaben. Weder Panel noch Kataloge sind betroffen - anders als bei den
drei Info-Knoepfen zuvor.

WARUM HIER AUF DAS ARGUMENT GEPRUEFT WIRD UND NICHT AUF DEN WERT: "admin",
"help" und "tasks" stehen alle auf 5 - und 5 ist zugleich die Ersatzregel fuer
UNBEKANNTE Namen (``get_button_cooldown:186``). Ein falscher Schluessel lieferte
also dieselbe Zahl. Eine Wertpruefung waere hier stumpf; sie spaeter zu
ergaenzen, wuerde den Test scheinbar schaerfen und taete es nicht.

EINE LUECKE, DIE ERST DIE MUTATIONSPROBE ZEIGTE: Die erste Fassung dieses
Tests pruefte ``assert_awaited_once``, das Vorhandensein eines Textes und
seinen Wortlaut - aber NICHT ``ephemeral``. Die Mutation "ephemeral=True ->
False" blieb deshalb gruen. Eine Abfuhr ohne ``ephemeral`` erscheint fuer ALLE
im Kanal; die Bremse erzeugte dann selbst das Rauschen, das sie verhindern
soll. Nachgetragen, nachdem die Probe die Luecke aufgedeckt hatte - ein Test,
der nicht fehlschlagen kann, ist kein Test.

DIESELBE PROBE FAND EINE ZWEITE LUECKE: Der Bau-Waechter behauptete nur
``assert knopf.custom_id`` - also blosse Existenz. Eine verfaelschte Kennung
(``help_button_5`` -> ``helpbutton_5``) liess ihn unberuehrt. Beide Faelle
zeigen dasselbe: Was hier nicht AUSDRUECKLICH festgenagelt ist, wird nicht
geprueft, auch wenn der Testname es verspricht. Jetzt steht die genaue Kennung
im Test, und die Erwartungswerte stammen aus dem Quelltext
(``task_management_`` interpoliert ``docker_name``, nicht den Anzeigenamen -
gemessen, nicht geraten).

FALLEN DER VORRICHTUNG, vorab benannt:

1. ``followup.send`` benutzen die Abfuhr UND der Tiefenweg. Ein blosses
   ``assert_awaited_once`` waere also auch ohne Bremse erfuellt. Deshalb der
   WORTLAUT: heute "Please wait ... seconds.", nach der Korrektur der
   Katalogtext "... more seconds before using this button again."
2. Alle vier bestaetigen ZUERST (``defer``) und bremsen DANACH - gemessen.
   Ein Test, der die Bremse vor dem defer erwartet, liefe ins Leere.
3. Der Dienst ist ein ECHTER ``SpamProtectionService`` auf ``tmp_path``, nur
   zum Mitschreiben durchgereicht.

EINE VORHERSAGE VON MIR TRAF NICHT ZU, und sie gehoert hierher, weil der
Fehler lehrreicher ist als das Ergebnis.

Ich hatte angesagt, nach der Umstellung breche
``test_admin_button_unauthorized_uses_followup``
(``tests/unit/audit_2026_09/test_pkg_b_control_ui.py:113``): Es laeuft mit
LEBENDEM Dienst, der davor liegende ``..._not_found_on_followup_is_caught``
trage fuer dieselbe Nutzerkennung (42) einen Zeitstempel ein, und weil der
Dienst ein Modul-Singleton ist, ueberlebe dieser Zustand von Test zu Test.

Gemessen: **564 gruen, kein Bruch.** Die Kette stimmte in jedem Glied bis auf
die Voraussetzung. Beide Tests setzen ``is_user_admin.return_value = False``,
und ``AdminButton.callback`` prueft die BERECHTIGUNG (:1783) VOR dem
Bremsblock (:1790). Wer dort abgewiesen wird, erreicht die Bremse nie - es
wird nichts eingetragen, und der Folgetest kann in keine Sperre laufen.

Beides hatte ich vorher selbst gemessen und im Abschnitt "FALLEN DER
VORRICHTUNG" notiert; genau deshalb ersetzt ``_druecke`` den Admin-Dienst mit
``is_user_admin = True``. Meine Vorhersage widersprach also meiner eigenen
Messung. Ein Argument kann in jedem Schritt richtig sein und trotzdem falsch,
wenn seine Voraussetzung anderswo schon widerlegt wurde.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.control_ui import AdminButton, HelpButton, InfoDropdownButton
from cogs.status_info_integration import TaskManagementButton
from services.infrastructure.spam_protection_service import SpamProtectionService

SPAM_PFAD = "services.infrastructure.spam_protection_service.get_spam_protection_service"
NUTZER = 5521
KANAL = 5
BEHAELTER = {"docker_name": "pruef", "name": "Pruefcontainer"}

# Klasse -> (Bauweise, erwarteter Aktionsname)
KNOEPFE = [
    (InfoDropdownButton, "kanal", "info"),
    (AdminButton, "kanal", "admin"),
    (HelpButton, "kanal", "help"),
    (TaskManagementButton, "behaelter", "tasks"),
]


class _Mitschrift:
    """Reicht an den ECHTEN Dienst durch und haelt fest, was gefragt wurde."""

    def __init__(self, echt):
        self._echt = echt
        self.gefragt = []
        self.vermerkt = []

    def is_on_cooldown(self, user_id, action_type):
        self.gefragt.append((user_id, action_type))
        return self._echt.is_on_cooldown(user_id, action_type)

    def add_user_cooldown(self, user_id, action_type):
        self.vermerkt.append((user_id, action_type))
        return self._echt.add_user_cooldown(user_id, action_type)

    def __getattr__(self, name):
        return getattr(self._echt, name)


def _dienst(tmp_path):
    return _Mitschrift(SpamProtectionService(config_dir=str(tmp_path)))


def _baue(klasse, bauweise):
    cog = MagicMock()
    if bauweise == "kanal":
        return klasse(cog, KANAL)
    return klasse(cog, BEHAELTER)


def _interaktion():
    interaktion = MagicMock()
    interaktion.user.id = NUTZER
    interaktion.user.name = "pruefer"
    interaktion.channel.id = KANAL
    interaktion.response.defer = AsyncMock()
    interaktion.response.send_message = AsyncMock()
    interaktion.response.is_done.return_value = True
    interaktion.followup.send = AsyncMock()
    return interaktion


async def _druecke(knopf, dienst):
    """Drueckt den Knopf mit ersetztem Spam-Dienst UND erlaubtem Admin.

    Der Admin-Ersatz ist nicht Beiwerk: ``AdminButton.callback`` prueft bei
    :1783 die Berechtigung und kehrt bei :1785 zurueck - VOR dem Bremsblock.
    Ohne diesen Ersatz erreicht der Rueckruf die Bremse nie, und die Tests
    waeren rot, ohne etwas ueber die Bremse zu sagen; nach der Korrektur blieben
    sie es. Gemessen, nachdem genau das aufgefallen war.

    Das Muster ist aus tests/unit/audit_2026_09/test_pkg_b_control_ui.py
    uebernommen, nicht erfunden.
    """
    interaktion = _interaktion()
    admin_dienst = MagicMock()
    admin_dienst.is_user_admin.return_value = True
    with patch(SPAM_PFAD, return_value=dienst), \
            patch("services.admin.admin_service.get_admin_service",
                  return_value=admin_dienst):
        await knopf.callback(interaktion)
    return interaktion


def test_die_vier_knoepfe_lassen_sich_bauen():
    """Sicherung gegen ein stumpfes Werkzeug - vor und nach der Korrektur gruen.

    Geprueft wird die GENAUE Kennung, nicht blosse Existenz: Die erste Fassung
    behauptete nur ``assert knopf.custom_id`` und konnte deshalb gar nicht
    anschlagen - eine verfaelschte Kennung erfuellt das muehelos. Die
    Mutationsprobe hat das gezeigt.
    """
    erwartet = {
        InfoDropdownButton: f"info_button_{KANAL}",
        AdminButton: f"admin_button_{KANAL}",
        HelpButton: f"help_button_{KANAL}",
        TaskManagementButton: f"task_management_{BEHAELTER['docker_name']}",
    }
    for klasse, bauweise, _name in KNOEPFE:
        knopf = _baue(klasse, bauweise)
        assert knopf.custom_id == erwartet[klasse], (
            f"{klasse.__name__} traegt die Kennung {knopf.custom_id!r} statt "
            f"{erwartet[klasse]!r}."
        )


def test_drei_der_vier_schluessel_stehen_auf_dem_ersatzwert(tmp_path):
    """Zweite Sicherung - sie haelt fest, was hier NICHT geprueft werden kann.

    "admin", "help" und "tasks" stehen auf 5, und 5 ist zugleich die
    Ersatzregel fuer unbekannte Namen. Ueber den WERT ist deshalb nicht zu
    unterscheiden, ob der richtige Schluessel abgefragt wird - die Tests unten
    pruefen das ARGUMENT. Aendert sich das hier, darf nachgeschaerft werden.
    """
    dienst = SpamProtectionService(config_dir=str(tmp_path))

    assert dienst.get_button_cooldown("gibt_es_nicht") == 5
    assert dienst.get_button_cooldown("info") == 3
    for name in ("admin", "help", "tasks"):
        assert dienst.get_button_cooldown(name) == 5, (
            f"{name!r} steht nicht mehr auf 5 - dann ist eine Wertpruefung moeglich."
        )


@pytest.mark.parametrize("klasse,bauweise,name", KNOEPFE, ids=lambda x: str(x))
@pytest.mark.asyncio
async def test_der_dienst_wird_gefragt_und_vermerkt(tmp_path, klasse, bauweise, name):
    """DER BEFUND: Die zustandsbehafteten Methoden werden nie gerufen."""
    dienst = _dienst(tmp_path)
    knopf = _baue(klasse, bauweise)

    await _druecke(knopf, dienst)

    assert dienst.gefragt == [(NUTZER, name)], (
        f"{klasse.__name__}: is_on_cooldown wurde nicht mit {name!r} gerufen, "
        f"sondern {dienst.gefragt!r}. Der Knopf bremst am Dienst vorbei und "
        "zahlt nicht in die Minutengrenze ein."
    )
    assert dienst.vermerkt == [(NUTZER, name)], (
        f"{klasse.__name__}: Der angenommene Druck wurde nicht vermerkt "
        f"({dienst.vermerkt!r})."
    )


@pytest.mark.parametrize("klasse,bauweise,name", KNOEPFE, ids=lambda x: str(x))
@pytest.mark.asyncio
async def test_der_zweite_druck_wird_abgewiesen(tmp_path, klasse, bauweise, name):
    """DER BEFUND, Wirkung - und die Meldung muss uebersetzt sein."""
    dienst = _dienst(tmp_path)
    knopf = _baue(klasse, bauweise)
    dienst.add_user_cooldown(NUTZER, name)
    dienst.vermerkt.clear()

    interaktion = await _druecke(knopf, dienst)

    interaktion.followup.send.assert_awaited_once()
    args = interaktion.followup.send.await_args.args
    assert args, (
        f"{klasse.__name__}: Die Abfuhr traegt keinen Text - so ruft der "
        "Tiefenweg, nicht die Bremse."
    )
    assert "before using this button again" in args[0], (
        f"{klasse.__name__}: Gesendet wurde nicht der Katalogtext, sondern "
        f"{args[0]!r}. Die unuebersetzte f-Zeichenkette erreicht jeden Nutzer "
        "auf Englisch, gleich welche Sprache er eingestellt hat."
    )
    assert interaktion.followup.send.await_args.kwargs.get("ephemeral") is True, (
        f"{klasse.__name__}: Die Abfuhr ist nicht auf den Druckenden beschraenkt "
        "und erscheint damit fuer ALLE im Kanal. Eine Bremse, die selbst Rauschen "
        "erzeugt, ist schlimmer als keine."
    )


@pytest.mark.parametrize("klasse,bauweise,name", KNOEPFE, ids=lambda x: str(x))
@pytest.mark.asyncio
async def test_die_fluechtige_ablage_am_objekt_entfaellt(tmp_path, klasse, bauweise, name):
    """DER BEFUND, dritter Teil: keine Sperre, die mit dem Objekt stirbt."""
    dienst = _dienst(tmp_path)
    knopf = _baue(klasse, bauweise)

    await _druecke(knopf, dienst)

    reste = [a for a in dir(knopf) if a.startswith("_last_click_")]
    assert not reste, (
        f"{klasse.__name__} legt weiterhin {reste} am Objekt ab. Diese Sperre "
        "ist beim naechsten Neuaufbau der Ansicht verschwunden."
    )
