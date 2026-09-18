# -*- coding: utf-8 -*-
"""Der Umschalt-Knopf muss eine Abklingzeit haben wie jeder andere Knopf.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND (SPEC.md B10, vom Betreiber zur Klaerung freigegeben).

``ToggleButton.callback`` (``cogs/control_ui.py:662``) traegt seit einer
Entfernung nur noch den Vermerk::

    # Note: Spam protection for toggle button was intentionally removed

Eine Begruendung steht nirgends - weder im Kommentar noch in der
Commit-Nachricht. Jeder andere Knopf derselben Datei prueft (``:265-282``,
``:981-990``, ``:1221-1228``). Der Umschalt-Knopf ist die einzige Ausnahme.

WAS DER BETREIBER DAVON SIEHT: Der Knopf klappt die Containeranzeige auf und
zu. Ohne Bremse laesst er sich beliebig schnell druecken; jeder Druck loest ein
``message.edit`` gegen die Discord-API aus. Das ist der Knopf mit der
niedrigsten Hemmschwelle - er tut scheinbar nichts Gefaehrliches - und
gleichzeitig der einzige ohne Schutz.

DIE ENTFERNUNG WAR KEIN UMBAU: Der alte Code (``0195074^``) war
funktionsfaehig, benutzte den Schluessel ``"refresh"`` und hatte einen
ordentlichen Fehlerfang. Er wurde ersatzlos gestrichen.

WIEDERHERSTELLEN HEISST NICHT ZURUECKKIPPEN. Der alte Code wich an zwei Stellen
vom heutigen Hausmuster ab, und beides waere ein Rueckschritt gewesen:

* Seine Meldung war eine **unuebersetzte** f-Zeichenkette; das Hausmuster bei
  ``:274`` uebersetzt.
* Er fing ``Exception``; das Hausmuster faengt
  ``(RuntimeError, AttributeError, KeyError)`` mit ``exc_info=True``.

BENUTZT WIRD DER VORHANDENE KATALOGEINTRAG ``"... more seconds before using
this button again."`` (``locales/*.json:1453``) - die einzige der drei
vorhandenen Abklingzeit-Meldungen **ohne** ``{action}``-Platzhalter. Die
Meldung bei ``:274`` fuellt ``{action}`` aus ``self.action``; ``ToggleButton``
hat kein solches Feld, und ``"refresh"`` dort einzusetzen hiesse, dem Nutzer an
einem Aufklapp-Knopf das Wort "refresh" zu zeigen.

ZUM SCHLUESSEL ``"refresh"`` - gemessen, nicht gewaehlt: Er kommt im gesamten
Anwendungscode genau einmal vor, naemlich als Eintrag im Vorgabe-Woerterbuch
(``spam_protection_service.py:301``). KEIN anderer Aufrufer uebergibt ihn, und
das Panel bietet kein Feld dafuer an (es kennt ``live_refresh``, ein anderer
Schluessel). Es teilt sich also niemand einen Eimer mit dem Umschalt-Knopf.

DARAUS FOLGT EINE BETREIBERFRAGE, die dieser Test NICHT entscheidet: Weil das
Panel kein ``refresh``-Feld hat, ist die wiederhergestellte Abklingzeit fest
bei 5 Sekunden und dort nicht aenderbar. Das ist genau das, was entfernt wurde
- aber es widerspricht dem Grundsatz "das Panel bestimmt". Ob ein Panel-Feld
dazukommen soll, ist eine Wertentscheidung und gehoert dem Betreiber.

WIE HIER GEPRUEFT WIRD: ueber den echten ``ToggleButton`` und seinen echten
Rueckruf. Der Spam-Dienst wird auf dem MODULPFAD ersetzt
(``services.infrastructure.spam_protection_service.get_spam_protection_service``)
und NICHT unter ``cogs.control_ui`` - der Import geschieht erst *in* der
Methode, ein Ersatz am Modul der Aufrufstelle ginge ins Leere. Dasselbe Muster
benutzt ``tests/unit/audit_2026_09/test_pkg_b_control_ui.py:49-53``.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.control_ui import ToggleButton

SPAM_PFAD = "services.infrastructure.spam_protection_service.get_spam_protection_service"


def _interaktion():
    """Eine Interaktion nach dem Muster der vorhandenen Oberflaechentests."""
    interaktion = MagicMock()
    interaktion.user.id = 4711
    interaktion.user.name = "pruefer"
    interaktion.channel.id = 99
    interaktion.response.defer = AsyncMock()
    interaktion.response.send_message = AsyncMock()
    interaktion.followup.send = AsyncMock()
    interaktion.message = MagicMock()
    interaktion.message.edit = AsyncMock()
    return interaktion


def _knopf():
    """Baut den echten Knopf. ``expanded_states`` ist ein ECHTES Woerterbuch.

    Mit einem MagicMock waere ``expanded_states.get(...)`` ein MagicMock und
    damit wahr - der Knopf startete "aufgeklappt", und die Zustandspruefung
    unten pruefte nichts.
    """
    cog = MagicMock()
    cog.expanded_states = {}
    cog.pending_actions = {}
    server_config = {"docker_name": "pruefcontainer", "name": "Pruefcontainer"}
    return cog, ToggleButton(cog, server_config, is_running=True, row=0)


def _dienst(auf_abklingzeit, *, aktiv=True, restzeit=4.2):
    dienst = MagicMock()
    dienst.is_enabled.return_value = aktiv
    dienst.is_on_cooldown.return_value = auf_abklingzeit
    dienst.get_remaining_cooldown.return_value = restzeit
    return dienst


def test_der_knopf_laesst_sich_ueberhaupt_bauen():
    """Sicherung gegen ein stumpfes Werkzeug.

    Muss VOR und NACH der Korrektur gruen sein. Scheiterte schon das Bauen,
    waeren die Tests unten rot, ohne etwas ueber die Abklingzeit zu sagen.
    """
    cog, knopf = _knopf()

    assert knopf.custom_id == "toggle_pruefcontainer"
    assert knopf.is_expanded is False
    assert cog.expanded_states == {}


@pytest.mark.asyncio
async def test_bei_abklingzeit_wird_der_druck_abgewiesen():
    """DER BEFUND: Der Umschalt-Knopf bremst nicht.

    Drei Behauptungen, jede fuer sich pruefbar: Es wird nicht bestaetigt
    (``defer``), der Zustand klappt nicht um, und der Nutzer bekommt eine
    Antwort nur fuer sich.
    """
    cog, knopf = _knopf()
    interaktion = _interaktion()

    with patch(SPAM_PFAD, return_value=_dienst(auf_abklingzeit=True)):
        await knopf.callback(interaktion)

    interaktion.response.defer.assert_not_awaited()
    assert cog.expanded_states == {}, (
        "Der Zustand ist trotz Abklingzeit umgeklappt. Dann bremst der Knopf "
        "die Anzeige nicht, sondern nur die Antwort - beim naechsten Aufbau "
        "stuende der Container falsch herum."
    )
    interaktion.response.send_message.assert_awaited_once()
    kwargs = interaktion.response.send_message.await_args.kwargs
    assert kwargs.get("ephemeral") is True, (
        "Die Abfuhr muss nur fuer den Druckenden sichtbar sein - sonst "
        "erzeugt die Bremse selbst Kanalrauschen."
    )
    text = interaktion.response.send_message.await_args.args[0]
    assert "4.2" in text, (
        f"Die Restzeit steht nicht in der Meldung: {text!r}. Ohne sie weiss "
        "der Nutzer nicht, wie lange er warten soll."
    )


@pytest.mark.asyncio
async def test_ohne_abklingzeit_wird_die_sperre_gesetzt():
    """DER BEFUND, zweite Haelfte: Ein Druck muss die Sperre setzen.

    Ohne diesen Teil koennte eine Korrektur nur abfragen und nie eintragen -
    die Bremse griffe dann nie.
    """
    cog, knopf = _knopf()
    interaktion = _interaktion()
    dienst = _dienst(auf_abklingzeit=False)

    with patch(SPAM_PFAD, return_value=dienst), \
            patch("cogs.control_ui.load_config", return_value={}):
        await knopf.callback(interaktion)

    dienst.add_user_cooldown.assert_called_once_with(4711, "refresh")
    dienst.is_on_cooldown.assert_called_once_with(4711, "refresh")
    interaktion.response.defer.assert_awaited_once()


@pytest.mark.asyncio
async def test_bei_abgeschaltetem_spamschutz_bremst_nichts():
    """Abgrenzung: Der Betreiber kann den Schutz abschalten.

    Greift die Pruefung auch dann, waere die Korrektur gruen aus dem falschen
    Grund - sie wuerde eine Einstellung ueberfahren.
    """
    cog, knopf = _knopf()
    interaktion = _interaktion()
    dienst = _dienst(auf_abklingzeit=True, aktiv=False)

    with patch(SPAM_PFAD, return_value=dienst), \
            patch("cogs.control_ui.load_config", return_value={}):
        await knopf.callback(interaktion)

    interaktion.response.defer.assert_awaited_once()
    dienst.is_on_cooldown.assert_not_called()


@pytest.mark.asyncio
async def test_ein_fehler_im_spamdienst_blockiert_den_knopf_nicht():
    """Abgrenzung: Die Bremse darf den Knopf nie unbrauchbar machen.

    Das Hausmuster faengt (RuntimeError, AttributeError, KeyError) und macht
    weiter. Ohne diese Abgrenzung koennte eine Korrektur den Knopf bei einer
    Stoerung des Dienstes komplett totlegen.
    """
    cog, knopf = _knopf()
    interaktion = _interaktion()
    dienst = _dienst(auf_abklingzeit=False)
    dienst.is_on_cooldown.side_effect = RuntimeError("Dienst gestoert")

    with patch(SPAM_PFAD, return_value=dienst), \
            patch("cogs.control_ui.load_config", return_value={}):
        await knopf.callback(interaktion)

    interaktion.response.defer.assert_awaited_once()
