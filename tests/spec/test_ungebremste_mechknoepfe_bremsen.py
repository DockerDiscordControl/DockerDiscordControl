# -*- coding: utf-8 -*-
"""Mech-Knoepfe, deren Panel-Regler heute nichts bewegen, muessen bremsen.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers. Die VERHALTENSAENDERUNG selbst ist entschieden:
"Ja, auch die zehn bremsen lassen".

DER BEFUND. Das Panel zeigt Regler fuer ``mech_donate`` (10), ``mech_display``
(3), ``mech_story`` (5) und ``mech_music`` (8). Die zugehoerigen Knoepfe fragen
den Spam-Dienst ueberhaupt nicht::

    MechDonateButton    mech_donate_<kanal>     -> mech_donate
    MechDisplayButton   mech_display_<stufe>    -> mech_display
    ReadStoryButton     read_story_<stufe>      -> (erreicht keinen Regler)
    PlaySongButton      play_song_<stufe>       -> (erreicht keinen Regler)
    EpilogueButton      epilogue_button         -> (erreicht keinen Regler)

Der Betreiber stellt vier Regler ein, und keiner bremst etwas; die Knoepfe
laufen auch an der Minutengrenze vorbei.

AUS "ZEHN" WURDEN GEMESSEN FUENF. Die Frage an den Betreiber zaehlte dreizehn
Mech-Klassen minus drei bremsende. Darunter sind aber vier Views (bremsen
nicht selbst, ihre Knoepfe tun es), ein Beschriftungsfeld mit
``disabled=True`` und zwei private Knoepfe, die an MechDonateButton bzw.
MechHistoryButton WEITERLEITEN. Der private Verlaufsknopf bremst also schon
heute, der private Spendenknopf bremst mit dem oeffentlichen. Dafuer fehlten in
der Zaehlung ReadStory, PlaySong und Epilogue - sie heissen nicht "Mech...".
Mein frueherer Satz "fuer mech_music gibt es keine Klasse" war falsch:
PlaySongButton ist sie. MechDetailsButton bremst ebenfalls nicht, hat aber gar
keinen Regler - ein eigener Befund.

DIE NAMEN, und warum nicht ueberall ``self.custom_id``: Die Praefix-Logik in
``get_button_cooldown`` leitet den Regler nur aus Namen ab, die mit ``mech_``
beginnen. ``read_story_4`` erreichte ``mech_story`` nie. Story, Musik und
Epilog bekommen deshalb ausdruecklich ``mech_story_<stufe>``,
``mech_music_<stufe>`` und ``mech_story_epilogue`` - je Stufe ein Eimer, wie
MechDisplayButton ihn ueber seine Kennung heute schon hat.

EINE FALLE, offen benannt: ``mech_story`` steht auf 5, genau der Ersatzregel.
Fuer Story und Epilog beweist deshalb nur das ARGUMENT den richtigen Regler,
nicht der Wert. Die Wertpruefung bei der Abfuhr traegt bei donate (10),
display (3) und music (8).

WO DIE BREMSE SITZT: nach der Pruefung "Mech-System abgeschaltet" (das ist eine
Auskunft, kein Arbeitsaufruf) und vor dem ``defer`` - die Abfuhr geht deshalb
per ``response.send_message``.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.control_ui import (EpilogueButton, MechDisplayButton, MechDonateButton,
                             MechPrivateDonateButton, MechPrivateHistoryButton,
                             PlaySongButton, ReadStoryButton)
from services.infrastructure.spam_protection_service import SpamProtectionService

SPAM_PFAD = "services.infrastructure.spam_protection_service.get_spam_protection_service"
NUTZER = 5522
KANAL = 88
STUFE = 4
JETZT = 90_000.0

# Name -> (Bau, erwarteter Schluessel, Vorgabewert des Reglers)
KNOEPFE = {
    "donate": (lambda cog: MechDonateButton(cog, KANAL), f"mech_donate_{KANAL}", 10),
    "display": (lambda cog: MechDisplayButton(cog, STUFE, str(STUFE), True), f"mech_display_{STUFE}", 3),
    "story": (lambda cog: ReadStoryButton(cog, STUFE), f"mech_story_{STUFE}", 5),
    "song": (lambda cog: PlaySongButton(cog, STUFE), f"mech_music_{STUFE}", 8),
    "epilog": (lambda cog: EpilogueButton(cog), "mech_story_epilogue", 5),
}
# Diese vier fragen vorab "Mech-System abgeschaltet?" - MechDonateButton nicht.
MIT_ABSCHALTPRUEFUNG = ["display", "story", "song", "epilog"]


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


def _interaktion():
    interaktion = MagicMock()
    interaktion.user.id = NUTZER
    interaktion.user.name = "pruefer"
    interaktion.channel.id = KANAL
    interaktion.response.defer = AsyncMock()
    interaktion.response.send_message = AsyncMock()
    interaktion.response.is_done = MagicMock(return_value=False)
    interaktion.followup.send = AsyncMock()
    return interaktion


async def _druecke(knopf, dienst, abgeschaltet=False):
    interaktion = _interaktion()
    with patch(SPAM_PFAD, return_value=dienst), \
            patch("cogs.control_ui.is_donations_disabled", return_value=abgeschaltet):
        try:
            await knopf.callback(interaktion)
        except TypeError as e:
            # NUR "can't be awaited", aus der Tiefe NACH der Bremse (Cog-Methoden
            # an einer MagicMock) - Begruendung wie in
            # test_mechknoepfe_bremsen_ueber_den_dienst.py. Die Tests behaupten
            # danach POSITIV; ein Fehler in der Bremse zeigte sich als leere
            # Mitschrift.
            if "can't be awaited" not in str(e):
                raise
    return interaktion


def test_die_schluessel_erreichen_ihren_regler(tmp_path):
    """Sicherung: Die gewaehlten Namen muessen ueber die Praefix-Logik beim
    richtigen Regler ankommen - sonst bremste die Korrektur nach der
    Ersatzregel, und der Regler bliebe tot."""
    dienst = SpamProtectionService(config_dir=str(tmp_path))
    assert dienst.get_button_cooldown("gibt_es_nicht") == 5, "Ersatzregel geaendert"
    for name, (_bau, schluessel, wert) in KNOEPFE.items():
        assert dienst.get_button_cooldown(schluessel) == wert, (
            f"{name}: {schluessel!r} liefert {dienst.get_button_cooldown(schluessel)} "
            f"statt {wert}."
        )
    for name, (bau, _schluessel, _wert) in KNOEPFE.items():
        assert bau(MagicMock()).custom_id, f"{name}: Knopf ohne Kennung gebaut"


@pytest.mark.parametrize("name", list(KNOEPFE))
@pytest.mark.asyncio
async def test_der_dienst_wird_gefragt_und_vermerkt(tmp_path, name):
    """DER BEFUND: Der Knopf fragt den Dienst nicht."""
    bau, schluessel, _wert = KNOEPFE[name]
    dienst = _dienst(tmp_path)

    await _druecke(bau(MagicMock()), dienst)

    assert dienst.gefragt == [(NUTZER, schluessel)], (
        f"{name}: is_on_cooldown wurde nicht mit {schluessel!r} gerufen, sondern "
        f"{dienst.gefragt!r}. Der Regler im Panel bewegt nichts."
    )
    assert dienst.vermerkt == [(NUTZER, schluessel)]


@pytest.mark.parametrize("name", list(KNOEPFE))
@pytest.mark.asyncio
async def test_der_zweite_druck_wird_abgewiesen(tmp_path, monkeypatch, name):
    """DER BEFUND, Wirkung - mit eingefrorener Uhr, damit die genannte
    Restzeit exakt der Reglerwert ist."""
    monkeypatch.setattr(time, "time", lambda: JETZT)
    bau, schluessel, wert = KNOEPFE[name]
    dienst = _dienst(tmp_path)
    dienst._echt.add_user_cooldown(NUTZER, schluessel)
    cog = MagicMock()

    interaktion = await _druecke(bau(cog), dienst)

    sender = interaktion.response.send_message
    sender.assert_awaited_once()
    assert sender.await_args.args, f"{name}: Abfuhr ohne Text"
    meldung = sender.await_args.args[0]
    assert "before using this button again" in meldung, f"{name}: {meldung!r}"
    assert f"wait {wert:.1f} more" in meldung, (
        f"{name}: Die Abfuhr nennt nicht die Restzeit {wert:.1f} s: {meldung!r}"
    )
    assert sender.await_args.kwargs.get("ephemeral") is True, (
        f"{name}: Die Abfuhr erscheint fuer ALLE im Kanal."
    )
    # Nach der Abweisung darf nichts weiterlaufen. defer allein faengt das
    # nicht: MechDonateButton gibt ohne defer an den Cog weiter - die
    # Mutationsprobe liess genau diesen Durchlauf zuerst unbemerkt.
    interaktion.response.defer.assert_not_awaited()
    assert cog.mock_calls == [], f"{name}: nach der Abweisung weitergelaufen: {cog.mock_calls!r}"


@pytest.mark.asyncio
async def test_der_private_spendenknopf_bremst_mit_dem_oeffentlichen(tmp_path):
    """Er leitet an MechDonateButton weiter und teilt sich dessen Eimer."""
    dienst = _dienst(tmp_path)

    await _druecke(MechPrivateDonateButton(MagicMock(), KANAL), dienst)

    assert dienst.gefragt == [(NUTZER, f"mech_donate_{KANAL}")], dienst.gefragt


@pytest.mark.asyncio
async def test_der_private_verlaufsknopf_bremst_schon_heute(tmp_path):
    """Abgrenzung: Er war in den "zehn" mitgezaehlt, bremst aber ueber die
    Weiterleitung an MechHistoryButton. Faellt die Weiterleitung weg, wird er
    ungebremst - das soll auffallen."""
    dienst = _dienst(tmp_path)
    cog = MagicMock()
    cog._start_interaction = AsyncMock(return_value=True)

    await _druecke(MechPrivateHistoryButton(cog, KANAL), dienst)

    assert dienst.gefragt == [(NUTZER, f"mech_history_{KANAL}")], dienst.gefragt


@pytest.mark.parametrize("name", MIT_ABSCHALTPRUEFUNG)
@pytest.mark.asyncio
async def test_abgeschaltetes_mechsystem_verbraucht_kein_kontingent(tmp_path, name):
    """Abgrenzung: Die Auskunft "Mech-System abgeschaltet" kommt VOR der Bremse
    und zaehlt nicht ins Minutenfenster."""
    bau, _schluessel, _wert = KNOEPFE[name]
    dienst = _dienst(tmp_path)

    interaktion = await _druecke(bau(MagicMock()), dienst, abgeschaltet=True)

    assert dienst.vermerkt == []
    assert "disabled" in interaktion.response.send_message.await_args.args[0]


@pytest.mark.parametrize("name", list(KNOEPFE))
@pytest.mark.asyncio
async def test_abgeschalteter_spamschutz_bremst_nichts(tmp_path, name):
    """Abgrenzung: Der Betreiber kann den Schutz abschalten - dann wird weder
    gefragt noch vermerkt."""
    bau, _schluessel, _wert = KNOEPFE[name]
    dienst = _dienst(tmp_path)

    with patch.object(dienst._echt, "is_enabled", return_value=False):
        await _druecke(bau(MagicMock()), dienst)

    assert dienst.gefragt == [] and dienst.vermerkt == []
