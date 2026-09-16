# -*- coding: utf-8 -*-
# @deckt Z3
# @deckt Z8
"""Z3/Z8 am Spenden-Broadcast: kein geratener Erfolg, kein stummer Fehlschlag.

Z3 - Kein Erfolg wird gemeldet, der nicht stattgefunden hat.
Z8 - Kein stummer Fehlschlag bei etwas Unwiderruflichem.

Eine Dankesmeldung an einen Discord-Kanal ist unwiderruflich. Sie darf nur
hinausgehen, wenn die Buchung bestaetigt ist - und nur an Kanaele, die
Broadcasts nicht abbestellt haben.

Ausgangslage (Stufe 0): Auf diesem gesamten Pfad gab es **null** Tests. Zwei
Wege senden dieselbe Meldung, und nur einer ist sorgfaeltig:

* ``check_donation_notifications`` (docker_control.py:5165-5180) liest
  ``donation_broadcasts`` und sendet nur an Kanaele, die es erlauben.
* ``DonationBroadcastModal.callback`` (:4919-4946) laeuft ueber dieselbe
  ``channel_permissions``-Liste und liest das Kennzeichen **nie**.

Zwei Wege fuehren hier zu einer Dankesmeldung ohne Buchung:

1. Wirft ``process_discord_donation``, faengt :4885-4887 die Ausnahme, setzt
   ``evolution_occurred = False`` - und die Ausfuehrung faellt in den
   Broadcast-Block bei :4889. (Ein zurueckgemeldetes ``success=False`` fuehrt
   dagegen bei :4831-4837 korrekt zu einem frueheren ``return``.)
2. Ist ``donation_manager_available`` falsch, wird bei :4789 gar nicht erst
   gebucht - der Broadcast laeuft trotzdem.

Zur Belastbarkeit, ehrlich: Das hier laeuft gegen nachgebildete Discord-Objekte.
Es beweist, welche Aufrufe der Code ausloest, nicht dass Discord sie so
ausfuehrt. Ein echter Beleg kaeme nur aus dem laufenden Bot.

Das Modal wird bewusst nicht ueber ``__init__`` gebaut: der Konstruktor zieht
py-cord-Maschinerie nach und ruft ueber ``_get_dynamic_amount_placeholder()``
den echten Fortschrittsdienst. Geprueft werden soll ``callback``, nicht das
Geruest.

GEGENPROBE (durchgefuehrt 2026-09-16) - der Weg dorthin gehoert dazu:

*Zwei Fehlstarts, beide meine Schuld.* Die ersten zwei Laeufe waren rot mit
``TypeError: 'MagicMock' object can't be awaited`` bei :4964 - die Attrappe
stubbte ``edit_original_response`` nicht. Rot aus dem falschen Grund beweist
nichts; korrigiert wurde die Attrappe, nicht der Code. Die Liste der zu
stubbenden ``await``-Aufrufe stammt seither aus einer vollstaendigen Suche
ueber :4731-4990 statt aus wiederholtem Probieren.

*Dann berechtigtes Rot*, alle drei an der eigenen Zusicherung:

* ``...buchung_wirft``        -> ``assert {100: 1, 200: 1} == {100: 0, 200: 0}``
* ``...ohne_buchungsdienst``  -> dieselbe Form
* ``...abbestellte_kanaele``  -> ``assert 1 == 0``

*Die erste Korrektur war unvollstaendig, und der Test hat es gezeigt:* danach
stand ``{100: 1, 200: 0}`` - das Opt-out griff, die Buchungssperre nicht. Sie
hing an ``donation_amount_euros``, das erst INNERHALB des uebersprungenen
Buchungsblocks (:4807) zugewiesen wird und daher ``None`` blieb. Umgestellt auf
``amount`` (die gepruefte Nutzereingabe, gesetzt bei :4753-4773). Danach 14 gruen.

Die erlaubte Seite der Sperre - ohne genannten Betrag soll die
"X supports DDC"-Meldung weiterhin hinausgehen - deckt
``test_ohne_betrag_geht_die_unterstuetzungsmeldung_hinaus`` ab. Ohne diesen Fall
koennte man die Sperre auf "immer blockieren" verschaerfen und alles bliebe
gruen.

Dieser Test stiess zugleich auf einen eigenen Fehler und hat ihn aufgedeckt:
``new_power = new_state.Power`` lief unbedingt, auch im ``else``-Zweig, in dem
``new_state`` nie zugewiesen wird. Die Zeile war zudem redundant - beide Zweige
setzen ``new_power`` bereits. Der entstehende ``UnboundLocalError`` (nicht
NameError, wie hier zuerst stand) fiel durch beide ``except``-Bloecke, die
Abschlussantwort wurde nie gesendet, und der Nutzer sah dauerhaft
"Processing...". Zwei weitere unbedingte Zugriffe auf ``new_state.level``
standen daneben; alle drei wurden auf ``new_evolution_level`` umgestellt, das
in beiden Zweigen gesetzt ist.

Gegenprobe dazu: vorher
``UnboundLocalError: cannot access local variable 'new_state'`` (1 rot, 14
gruen), danach 15 gruen. Die vollstaendige Liste der ``new_state``-Zugriffe
wurde vor der Korrektur erhoben, nicht durch wiederholte Laeufe entdeckt.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.docker_control import DonationBroadcastModal


def _interaction():
    """Nachgebildete Interaktion - Form wie in tests/unit/cogs/test_enhanced_info_modal.py:42.

    Jeder Stub deckt einen konkreten ``await`` im Callback ab; die Liste stammt
    aus einer vollstaendigen Suche ueber :4731-4990, nicht aus wiederholtem
    Probieren:

    * ``response.send_message``      -> :4738
    * ``followup.send``              -> :4776, :4814, :4836
    * ``edit_original_response``     -> :4964, :4984
    * ``<followup-Ergebnis>.delete`` -> :4969, :4979

    Der letzte Punkt waere verzichtbar, weil :4970 ein nacktes ``except: pass``
    ist - genau die Sorte Verschlucken, die Z8 verbietet. Sich im Test darauf zu
    stuetzen hiesse, einen Fehler als Stuetze zu benutzen.
    """
    inter = MagicMock()
    inter.response.send_message = AsyncMock()

    verarbeitungsmeldung = MagicMock()
    verarbeitungsmeldung.delete = AsyncMock()
    inter.followup.send = AsyncMock(return_value=verarbeitungsmeldung)

    inter.edit_original_response = AsyncMock()
    inter.user.name = "Spender"
    inter.user.id = 4711
    inter.guild.id = 1
    inter.channel.id = 2
    inter.id = 999
    return inter


def _modal(*, manager_available: bool = True, betrag: str = "5.00", teilen: str = "X"):
    """Modal ohne py-cord-Konstruktor, mit den drei Feldern, die callback liest."""
    m = DonationBroadcastModal.__new__(DonationBroadcastModal)
    m.donation_manager_available = manager_available
    m.bot = MagicMock()
    m.name_input = SimpleNamespace(value="Spender")
    m.amount_input = SimpleNamespace(value=betrag)
    m.share_input = SimpleNamespace(value=teilen)
    return m


def _kanaele(*konfigurationen):
    """(config-dict, {id: kanal}) fuer die angegebenen Kanaele."""
    config = {"channel_permissions": {}}
    kanaele = {}
    for kanal_id, broadcasts in konfigurationen:
        config["channel_permissions"][str(kanal_id)] = {"donation_broadcasts": broadcasts}
        kanal = MagicMock()
        kanal.send = AsyncMock()
        kanaele[kanal_id] = kanal
    return config, kanaele


def _mech_service_attrappe():
    """Liefert Zustaende, damit der Callback bis zum Broadcast kommt."""
    zustand = SimpleNamespace(success=True, level=1, power=10.0)
    service = MagicMock()
    service.get_mech_state_service = MagicMock(return_value=zustand)
    return service


@pytest.fixture
def umgebung():
    """Patcht genau die Abhaengigkeiten, die callback von aussen holt."""
    config, kanaele = _kanaele((100, True), (200, False))
    with patch("cogs.docker_control.load_config", return_value=config), \
         patch("services.mech.mech_service.get_mech_service",
               return_value=_mech_service_attrappe()):
        yield kanaele


def _gesendet(kanaele):
    return {kid: k.send.await_count for kid, k in kanaele.items()}


async def test_keine_dankesmeldung_wenn_die_buchung_wirft(umgebung):
    """Wirft der Buchungsdienst, darf nichts hinausgehen."""
    inter = _interaction()
    inter.client.get_channel = lambda kid: umgebung.get(int(kid))

    with patch("services.donation.unified_donation_service.process_discord_donation",
               AsyncMock(side_effect=RuntimeError("Spendenbuch nicht schreibbar"))):
        await _modal().callback(inter)

    assert _gesendet(umgebung) == {100: 0, 200: 0}, (
        "Die Buchung ist gescheitert, aber es ging eine Dankesmeldung hinaus - "
        "der Kanal meldet Geld, das nie im Buch gelandet ist"
    )


async def test_keine_dankesmeldung_ohne_buchungsdienst(umgebung):
    """Ist der Buchungsdienst nicht verfuegbar, wird nichts gebucht - und nichts gesendet."""
    inter = _interaction()
    inter.client.get_channel = lambda kid: umgebung.get(int(kid))

    await _modal(manager_available=False).callback(inter)

    assert _gesendet(umgebung) == {100: 0, 200: 0}, (
        "Ohne Buchungsdienst wurde nichts gebucht, aber trotzdem gedankt"
    )


async def test_broadcast_respektiert_abbestellte_kanaele(umgebung):
    """Ein Kanal mit donation_broadcasts=False bekommt nichts.

    Der Parallelpfad in check_donation_notifications (:5168) beachtet das
    Kennzeichen laengst; dieser Weg muss dieselbe Regel erfuellen, sonst ist es
    dieselbe Regel an zwei Stellen mit zwei Ergebnissen.
    """
    inter = _interaction()
    inter.client.get_channel = lambda kid: umgebung.get(int(kid))

    erfolg = SimpleNamespace(
        success=True,
        new_state=SimpleNamespace(level=1, Power=15.0),
        error_message=None,
    )
    with patch("services.donation.unified_donation_service.process_discord_donation",
               AsyncMock(return_value=erfolg)):
        await _modal().callback(inter)

    gesendet = _gesendet(umgebung)
    assert gesendet[200] == 0, (
        "Kanal 200 hat Spenden-Broadcasts abbestellt, bekam aber trotzdem eine "
        "Meldung"
    )
    assert gesendet[100] == 1, (
        "Kanal 100 erlaubt Broadcasts und haette die Meldung bekommen muessen"
    )


async def test_ohne_betrag_geht_die_unterstuetzungsmeldung_hinaus(umgebung):
    """Ohne genannten Betrag gibt es nichts zu buchen - die Meldung darf trotzdem raus.

    Das ist die ERLAUBTE Seite der Sperre aus den Tests oben. Ohne diesen Fall
    koennte man die Sperre auf "immer blockieren" verschaerfen und alles bliebe
    gruen - ein gewolltes Verhalten waere stillschweigend verschwunden.

    Deckt zugleich :4870 ab: ohne Betrag laeuft der Code in den ``else``-Zweig
    bei :4844, in dem ``new_state`` nie zugewiesen wird, und greift bei :4870
    trotzdem darauf zu. Der ``NameError`` faellt durch beide ``except``-Bloecke;
    der Nutzer bliebe auf "Processing..." sitzen, weil :4964 nie erreicht wird.
    """
    inter = _interaction()
    inter.client.get_channel = lambda kid: umgebung.get(int(kid))

    await _modal(betrag="").callback(inter)

    gesendet = _gesendet(umgebung)
    assert gesendet[100] == 1, (
        "Die Unterstuetzungsmeldung ohne Betrag ging nicht hinaus - die Sperre "
        "hat einen gewollten Fall mitgenommen"
    )
    assert gesendet[200] == 0, "Abbestellter Kanal bekam trotzdem eine Meldung"
    assert inter.edit_original_response.await_count == 1, (
        "Der Nutzer bekam keine abschliessende Antwort und saehe weiter 'Processing...'"
    )
