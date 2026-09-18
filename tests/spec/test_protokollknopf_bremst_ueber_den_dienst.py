# -*- coding: utf-8 -*-
"""Der Protokoll-Knopf muss ueber den Spam-Dienst bremsen, nicht am Cog vorbei.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND. ``DebugLogsButton.callback`` (``status_info_integration.py:684-705``)
holt vom Dienst nur die DAUER (``get_button_cooldown("logs")``) und fuehrt die
Buchhaltung dann selbst: Zeitstempel unter ``button_logs_<nutzer>`` in
``self.cog._button_cooldowns``. Die zustandsbehafteten Methoden des Dienstes -
``is_on_cooldown`` und ``add_user_cooldown`` - werden nie gerufen.

WAS DER BETREIBER DAVON SIEHT: Die **Minutengrenze** aus dem Panel wirkt fuer
diesen Knopf nicht. Sie zaehlt in ``add_user_cooldown``, und da dieser Weg dort
nie ankommt, zaehlt er nicht mit. Der Betreiber stellt "hoechstens 30 Knoepfe je
Minute" ein, und dieser Knopf ignoriert es - waehrend die Abklingzeit daneben
brav funktioniert. Genau die Mischung, die niemandem auffaellt.

DAS IST EINE VON DREIZEHN STELLEN, und bewusst die erste: Sie ist die einzige
der vier Cog-Buchhaltungen, die KEINEN neuen Schluessel braucht - ``logs``
existiert bereits mit 10 Sekunden. Damit laesst sich das Umstellungsmuster hier
vollstaendig beweisen, bevor es auf Stellen angewandt wird, die zusaetzlich
Panel-Felder und 40 Kataloge beruehren.

WAS SICH FUER DEN NUTZER NICHT AENDERT: Der Schluessel bleibt ``logs``, die
Dauer bleibt 10 Sekunden, der Eimer bleibt fuer diesen Knopf allein (der
Aktionsname ``logs`` wird von keiner anderen Stelle als Sperre benutzt -
gemessen). Neu ist ausschliesslich, dass der Druck im Dienst VERMERKT wird und
damit in die Minutengrenze einzahlt.

DREI FALLEN IN DER VORRICHTUNG, vorab benannt:

1. Der Cog darf im Test KEIN ``MagicMock`` mit selbsterzeugten Attributen sein.
   Der heutige Code fragt ``hasattr(self.cog, '_button_cooldowns')``, und ein
   MagicMock beantwortet das immer mit wahr - der Knopf wuerde nie abweisen, und
   der Test pruefte die Attrappe statt den Code. Deshalb ein ECHTES Woerterbuch.
2. ``callback`` umschliesst seinen ganzen Rumpf mit ``except Exception``
   (``:782``). Ein Fehler in der Tiefe wird also VERSCHLUCKT. Ein Test, der nur
   das Ausbleiben von Fehlern prueft, waere hohl gruen. Hier wird deshalb
   ausschliesslich POSITIV behauptet: Die Abfuhr muss gesendet worden sein.
3. Der Dienst ist ein ECHTER ``SpamProtectionService`` auf ``tmp_path``, nur zum
   Mitschreiben durchgereicht. Eine reine Attrappe koennte jede Zahl liefern und
   wuerde nicht zeigen, ob der richtige Weg genommen wird.

ABGRENZUNG: Ersetzt wird auf dem MODULPFAD
(``services.infrastructure.spam_protection_service.get_spam_protection_service``),
weil der Import erst IN der Methode geschieht - ein Ersatz am Modul der
Aufrufstelle ginge ins Leere.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.status_info_integration import DebugLogsButton
from services.infrastructure.spam_protection_service import SpamProtectionService

SPAM_PFAD = "services.infrastructure.spam_protection_service.get_spam_protection_service"
NUTZER = 8123
BEHAELTER = {"docker_name": "pruef"}


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


def _cog():
    """Cog mit ECHTEM Woerterbuch - siehe Falle 1 im Kopftext."""
    cog = MagicMock()
    cog._button_cooldowns = {}
    return cog


def _interaktion():
    interaktion = MagicMock()
    interaktion.user.id = NUTZER
    interaktion.channel.id = 7
    interaktion.response.defer = AsyncMock()
    interaktion.response.send_message = AsyncMock()
    interaktion.followup.send = AsyncMock()
    return interaktion


async def _druecke(knopf, dienst):
    interaktion = _interaktion()
    with patch(SPAM_PFAD, return_value=dienst):
        await knopf.callback(interaktion)
    return interaktion


def test_der_knopf_laesst_sich_bauen():
    """Sicherung gegen ein stumpfes Werkzeug - vor und nach der Korrektur gruen."""
    knopf = DebugLogsButton(_cog(), BEHAELTER)

    assert knopf.custom_id == "debug_logs_pruef"
    assert knopf.container_name == "pruef"


def test_die_abklingzeit_fuer_logs_ist_ueberhaupt_gesetzt(tmp_path):
    """Zweite Sicherung: Die Behauptungen unten sind nur etwas wert, wenn
    ``logs`` einen eigenen, von der Ersatzregel verschiedenen Wert hat.

    Ersatzregel ist 5 (get_button_cooldown:186). Staende logs auch auf 5, waere
    nicht zu unterscheiden, ob der Schluessel ueberhaupt gefunden wird.
    """
    dienst = SpamProtectionService(config_dir=str(tmp_path))

    assert dienst.get_button_cooldown("logs") == 10
    assert dienst.get_button_cooldown("gibt_es_nicht") == 5


@pytest.mark.asyncio
async def test_der_dienst_wird_ueberhaupt_gefragt(tmp_path):
    """DER BEFUND: Die zustandsbehafteten Methoden werden nie gerufen."""
    dienst = _dienst(tmp_path)
    knopf = DebugLogsButton(_cog(), BEHAELTER)

    await _druecke(knopf, dienst)

    assert dienst.gefragt == [(NUTZER, "logs")], (
        f"is_on_cooldown wurde nicht mit (NUTZER, 'logs') gerufen, sondern "
        f"{dienst.gefragt!r}. Der Knopf fuehrt seine Abklingzeit am Dienst "
        "vorbei - und zahlt damit nicht in die Minutengrenze ein."
    )
    assert dienst.vermerkt == [(NUTZER, "logs")], (
        f"Der angenommene Druck wurde nicht im Dienst vermerkt ({dienst.vermerkt!r}). "
        "Ohne add_user_cooldown zaehlt er nicht in die Minutengrenze."
    )


@pytest.mark.asyncio
async def test_der_zweite_druck_wird_abgewiesen(tmp_path):
    """DER BEFUND, Wirkung: Was im Dienst steht, muss den Knopf bremsen."""
    dienst = _dienst(tmp_path)
    knopf = DebugLogsButton(_cog(), BEHAELTER)
    dienst.add_user_cooldown(NUTZER, "logs")
    dienst.vermerkt.clear()

    interaktion = await _druecke(knopf, dienst)

    interaktion.followup.send.assert_awaited_once()
    args = interaktion.followup.send.await_args.args
    kwargs = interaktion.followup.send.await_args.kwargs

    # DREI Behauptungen, und jede einzeln noetig - gemessen, nicht geraten:
    # Der Erfolgsweg ruft followup.send(embed=…, view=…, ephemeral=True), also
    # OHNE Stellungsargument; ein blosses assert_awaited_once waere deshalb auch
    # dann erfuellt, wenn gar nicht abgewiesen, sondern das Protokoll
    # ausgeliefert wurde. Im Tiefenweg gibt es ausserdem zwei followup.send MIT
    # positionellem Text ("Could not retrieve debug logs"), darum zusaetzlich
    # der Wortlaut.
    assert kwargs.get("embed") is None, (
        "Es wurde eine Einbettung gesendet - das ist der Erfolgsweg mit den "
        "Protokollen, nicht die Abfuhr. Der Knopf hat also nicht gebremst."
    )
    assert args, (
        f"Die Abfuhr traegt keinen Text als Stellungsargument: {kwargs!r}. "
        "So ruft der Erfolgsweg, nicht die Bremse."
    )
    assert "before using this button again" in args[0], (
        f"Die gesendete Meldung ist nicht die Abklingzeit-Abfuhr: {args[0]!r}"
    )
    assert kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_die_eigene_buchhaltung_am_cog_entfaellt(tmp_path):
    """DER BEFUND, dritte Haelfte: eine Ablage statt zweier.

    Bleibt die Cog-Ablage bestehen, gaebe es den Zustand doppelt - und die
    naechste Korrektur pflegte wieder nur eine der beiden Stellen.
    """
    dienst = _dienst(tmp_path)
    cog = _cog()
    knopf = DebugLogsButton(cog, BEHAELTER)

    await _druecke(knopf, dienst)

    assert cog._button_cooldowns == {}, (
        f"Der Knopf schreibt weiterhin in cog._button_cooldowns "
        f"({cog._button_cooldowns!r}) - dieselbe Information an zwei Orten."
    )


@pytest.mark.asyncio
async def test_bei_abgeschaltetem_schutz_bremst_nichts(tmp_path):
    """Abgrenzung: Der Betreiber kann den Schutz abschalten."""
    dienst = _dienst(tmp_path)
    knopf = DebugLogsButton(_cog(), BEHAELTER)

    with patch.object(dienst._echt, "is_enabled", return_value=False):
        interaktion = await _druecke(knopf, dienst)

    assert dienst.gefragt == []
    interaktion.response.defer.assert_awaited_once()
