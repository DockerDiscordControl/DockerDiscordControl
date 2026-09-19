# -*- coding: utf-8 -*-
"""Der Aktualisieren-Knopf der Live-Log-Ansicht muss ueber den Spam-Dienst bremsen.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND. ``LiveLogView.manual_refresh`` (``status_info_integration.py:494``)
holt vom Dienst nur die DAUER und fuehrt die Buchhaltung selbst: Zeitstempel
unter ``button_refresh_<nutzer>`` in ``self._button_cooldowns``, einem
Woerterbuch, das die Ansicht sich per ``hasattr`` selbst anlegt.
``is_on_cooldown`` und ``add_user_cooldown`` werden nie gerufen.

ZWEI FOLGEN:

1. Die MINUTENGRENZE aus dem Panel wirkt hier nicht - sie zaehlt in
   ``add_user_cooldown``, und dort kommt dieser Weg nie an.
2. Die Sperre haengt an der ANSICHT und stirbt mit ihr. Das wiegt hier
   besonders schwer: Die Live-Log-Ansicht **erneuert sich selbst** (siehe
   ``_start_auto_recreation``: 30 Sekunden vor dem Zeitablauf wird sie neu
   gebaut). Wer also wartet, bis die Ansicht sich erneuert hat, ist jede
   Abklingzeit los - ohne dass irgendetwas davon sichtbar waere.

MITGENOMMEN: Die Abfuhr ist heute eine UNUEBERSETZTE f-Zeichenkette
(``f"⏰ Please wait ... before refreshing again."``). Die Umstellung aufs
Hausmuster benutzt den vorhandenen Katalogeintrag.

KEIN NEUER SCHLUESSEL: ``live_refresh`` existiert in den Vorgaben (5).

WARUM HIER AUF DAS ARGUMENT GEPRUEFT WIRD UND NICHT AUF DEN WERT:
``live_refresh`` steht auf 5 - und 5 ist zugleich die Ersatzregel fuer
UNBEKANNTE Namen (``get_button_cooldown:186``). Ein falscher Schluessel
lieferte also dieselbe Zahl. Eine Wertpruefung waere hier stumpf; sie spaeter
zu ergaenzen, wuerde den Test scheinbar schaerfen und taete es nicht.

VIER FALLEN DER VORRICHTUNG, alle vor dem ersten Lauf abgedichtet - in dieser
Sitzung haben mich zwei davon je einen halben Umweg gekostet, weil ich sie
erst im Fehlertext gelesen habe:

1. ``__init__`` startet ueber ``_start_auto_recreation`` eine asyncio-Aufgabe.
   Ohne laufende Schleife gaebe das einen RuntimeError oder eine haengende
   Aufgabe - die Methode wird deshalb ersetzt, BEVOR die Ansicht gebaut wird.
2. ``response.send_message`` benutzen die Abfuhr (:507) UND der Erfolgsweg
   (:518, mit ``delete_after=1``). Ein ``assert_awaited_once`` waere also auch
   ohne Bremse erfuellt. Deshalb der WORTLAUT.
3. Der Tiefenweg erwartet ``container_logs_text`` - ohne Ersatz liefe der
   angenommene Druck in eine Attrappen-Sackgasse.
4. ``manual_refresh`` ist KEINE eigene Knopfklasse, sondern eine Methode, die
   in ``_create_all_buttons`` einem Knopf zugewiesen wird
   (``refresh_button.callback = self.manual_refresh``). Geprueft wird deshalb
   die Ansicht und ihre Methode, nicht eine Knopfklasse.
5. RAUSCHEN AUS DER VORRICHTUNG, damit es niemand fuer einen Defekt haelt:
   ``container_logs_text`` wird durch einen AsyncMock ersetzt, der einen
   LEEREN String liefert. Der Erfolgsweg wertet das als Fehlschlag und
   protokolliert "Manual refresh failed - no logs retrieved" - in jedem Lauf,
   mehrfach. Fuer die Behauptungen ist das folgenlos, weil sie saemtlich VOR
   dieser Stelle liegen. Wer die Laufausgabe spaeter liest, soll wissen, dass
   diese Warnung von diesem Test stammt und nicht vom Code.

``ephemeral`` und die GENAUE Kennung werden von Anfang an behauptet: Die
Mutationsprobe hat in dieser Sitzung zweimal gezeigt, dass genau diese beiden
Behauptungen fehlen, wenn man sie nicht ausdruecklich hinschreibt.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.status_info_integration import LiveLogView
from services.infrastructure.spam_protection_service import SpamProtectionService

SPAM_PFAD = "services.infrastructure.spam_protection_service.get_spam_protection_service"
NUTZER = 7788
BEHAELTER = "pruefcontainer"


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


def _ansicht():
    """Baut die ECHTE Ansicht - ohne die Selbsterneuerungs-Aufgabe zu starten."""
    with patch.object(LiveLogView, "_start_auto_recreation", lambda self: None):
        return LiveLogView(BEHAELTER, auto_refresh=False)


def _interaktion():
    interaktion = MagicMock()
    interaktion.user.id = NUTZER
    interaktion.user.name = "pruefer"
    interaktion.response.send_message = AsyncMock()
    interaktion.response.defer = AsyncMock()
    interaktion.followup.send = AsyncMock()
    return interaktion


async def _druecke(ansicht, dienst):
    interaktion = _interaktion()
    with patch(SPAM_PFAD, return_value=dienst), \
            patch("cogs.status_info_integration.container_logs_text",
                  new=AsyncMock(return_value="")):
        await ansicht.manual_refresh(interaktion)
    return interaktion


@pytest.mark.asyncio
async def test_die_ansicht_traegt_den_aktualisieren_knopf():
    """Sicherung gegen ein stumpfes Werkzeug - GENAUE Kennung, nicht blosse Existenz.

    MUSS asynchron sein: ``discord.ui.View.__init__`` ruft
    ``asyncio.get_running_loop()`` (py-cord view.py:186). Synchron gebaut wirft
    die Ansicht ``RuntimeError: no running event loop`` - das Ersetzen von
    ``_start_auto_recreation`` reicht nicht, denn die Loop-Anforderung kommt aus
    der Basisklasse, nicht aus DDC-Code.
    """
    ansicht = _ansicht()

    kennungen = [k.custom_id for k in ansicht.children]
    assert "manual_refresh" in kennungen, (
        f"Die Ansicht traegt keinen Knopf mit der Kennung 'manual_refresh': {kennungen}"
    )
    assert ansicht.container_name == BEHAELTER


def test_live_refresh_steht_auf_dem_ersatzwert(tmp_path):
    """Zweite Sicherung - sie haelt fest, was hier NICHT geprueft werden kann.

    ``live_refresh`` steht auf 5, und 5 ist zugleich die Ersatzregel fuer
    unbekannte Namen. Ueber den WERT ist deshalb nicht zu unterscheiden, ob der
    richtige Schluessel abgefragt wird - die Tests unten pruefen das ARGUMENT.
    Aendert sich das hier, darf nachgeschaerft werden.
    """
    dienst = SpamProtectionService(config_dir=str(tmp_path))

    assert dienst.get_button_cooldown("live_refresh") == 5
    assert dienst.get_button_cooldown("gibt_es_nicht") == 5, "Ersatzregel geaendert"


@pytest.mark.asyncio
async def test_der_dienst_wird_gefragt_und_vermerkt(tmp_path):
    """DER BEFUND: Die zustandsbehafteten Methoden werden nie gerufen."""
    dienst = _dienst(tmp_path)
    ansicht = _ansicht()

    await _druecke(ansicht, dienst)

    assert dienst.gefragt == [(NUTZER, "live_refresh")], (
        f"is_on_cooldown wurde nicht mit 'live_refresh' gerufen, sondern "
        f"{dienst.gefragt!r}. Der Knopf bremst am Dienst vorbei und zahlt nicht "
        "in die Minutengrenze ein."
    )
    assert dienst.vermerkt == [(NUTZER, "live_refresh")], (
        f"Der angenommene Druck wurde nicht vermerkt ({dienst.vermerkt!r})."
    )


@pytest.mark.asyncio
async def test_der_zweite_druck_wird_abgewiesen(tmp_path):
    """DER BEFUND, Wirkung - und die Meldung muss uebersetzt sein."""
    dienst = _dienst(tmp_path)
    ansicht = _ansicht()
    dienst.add_user_cooldown(NUTZER, "live_refresh")
    dienst.vermerkt.clear()

    interaktion = await _druecke(ansicht, dienst)

    interaktion.response.send_message.assert_awaited_once()
    args = interaktion.response.send_message.await_args.args
    kwargs = interaktion.response.send_message.await_args.kwargs
    assert args, "Die Abfuhr traegt keinen Text."
    assert "Refreshing logs" not in args[0], (
        f"Gesendet wurde die Erfolgsmeldung ({args[0]!r}) - der Knopf hat nicht "
        "gebremst, sondern aktualisiert."
    )
    assert "before using this button again" in args[0], (
        f"Gesendet wurde nicht der Katalogtext, sondern {args[0]!r}. Die "
        "unuebersetzte f-Zeichenkette erreicht jeden Nutzer auf Englisch."
    )
    assert kwargs.get("ephemeral") is True, (
        "Die Abfuhr ist nicht auf den Druckenden beschraenkt und erscheint "
        "damit fuer ALLE im Kanal."
    )


@pytest.mark.asyncio
async def test_die_ablage_an_der_ansicht_entfaellt(tmp_path):
    """DER BEFUND, dritter Teil: keine Sperre, die mit der Ansicht stirbt.

    Besonders folgenreich hier, weil die Ansicht sich selbst erneuert - eine
    Sperre an ihr ist nach der naechsten Erneuerung weg.
    """
    dienst = _dienst(tmp_path)
    ansicht = _ansicht()

    await _druecke(ansicht, dienst)

    assert not getattr(ansicht, "_button_cooldowns", None), (
        f"Die Ansicht fuehrt weiterhin {getattr(ansicht, '_button_cooldowns', None)!r} "
        "- diese Sperre ueberlebt die naechste Selbsterneuerung nicht."
    )
