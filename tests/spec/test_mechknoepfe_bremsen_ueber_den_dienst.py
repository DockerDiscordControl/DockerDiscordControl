# -*- coding: utf-8 -*-
"""Die drei bremsenden Mech-Knoepfe muessen ueber den Spam-Dienst bremsen.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND. Drei Mech-Knoepfe holen vom Dienst nur die DAUER und legen ihren
Zeitstempel als Attribut auf sich selbst ab (``_last_click_<nutzer>``)::

    MechExpandButton    control_ui.py:2327   self.custom_id -> mech_expand
    MechCollapseButton  control_ui.py:2428   self.custom_id -> mech_collapse
    MechHistoryButton   control_ui.py:2563   self.custom_id -> mech_history

``is_on_cooldown`` und ``add_user_cooldown`` werden nie gerufen. Die
MINUTENGRENZE aus dem Panel wirkt fuer sie deshalb nicht - sie zaehlt in
``add_user_cooldown``, und dort kommen sie nie an. Die Sperre stirbt ausserdem
mit dem Knopf-Objekt: Bei jedem Neuaufbau der Ansicht ist sie weg.

DER SCHLUESSEL BLEIBT ``self.custom_id``, und das ist wichtig: Diese drei
fragen ueber die Praefix-Logik (``get_button_cooldown:178-184``) ab, die aus
``mech_expand_<kanal>`` den Regler ``mech_expand`` ableitet. Der Dienst muss
mit DEMSELBEN Wert gefuettert werden - ein Literal ``"mech_expand"`` ergaebe
einen anderen Eimer als heute, und ``interaction.user.id`` mit einem
kanalspezifischen Namen einen Eimer je Kanal statt je Knopfart. Der Test nagelt
deshalb den GENAUEN Argumentwert fest.

HIER IST AUCH DER WERT PRUEFBAR, anders als bei admin/help/tasks: Die Vorgaben
stehen auf 3 (expand), 2 (collapse) und 5 (history) - drei verschiedene Zahlen,
keine davon gleich der 5-Sekunden-Ersatzregel bei collapse und expand. Ein
falscher Schluessel faellt damit doppelt auf.

ZWEI ABFUHRWEGE, GEMESSEN - kein einheitliches Muster::

    MechExpandButton    bremst VOR dem defer (:2338), weist per
                        response.send_message ab
    MechCollapseButton  ebenso (defer :2439)
    MechHistoryButton   bestaetigt INNERHALB des Bremsblocks (:2571) und
                        weist per followup.send ab

Ein Test, der fuer alle drei denselben Weg annimmt, waere fuer einen davon rot
aus dem falschen Grund.

DIE SPENDENPRUEFUNG LIEGT BEI EXPAND UND COLLAPSE VOR DER BREMSE (:2311/:2418).
Ohne Ersatz kehrt der Rueckruf zurueck, bevor ein Schluessel abgefragt wird -
und der Test waere gruen, ohne irgendetwas zu belegen. Bei History kommt sie
erst nach der Bremse (:2588).

ZWEI BEHAUPTUNGEN STEHEN HIER VON ANFANG AN, weil die Mutationsprobe sie in der
vorigen Runde als Luecke aufgedeckt hat: ``ephemeral`` wird ausdruecklich
geprueft (eine Abfuhr ohne das erscheint fuer ALLE im Kanal - die Bremse
erzeugte dann das Rauschen, das sie verhindern soll), und die Kennung wird auf
ihren GENAUEN Wert geprueft, nicht auf blosse Existenz.

ABGRENZUNG: Die ZEHN Mech-Klassen, die ueberhaupt nicht bremsen, sind nicht
Gegenstand dieses Tests - das ist ein eigener Befund mit eigener, vom Betreiber
bereits genehmigter Verhaltensaenderung.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.control_ui import MechCollapseButton, MechExpandButton, MechHistoryButton
from services.infrastructure.spam_protection_service import SpamProtectionService

SPAM_PFAD = "services.infrastructure.spam_protection_service.get_spam_protection_service"
NUTZER = 6644
KANAL = 77

# Klasse -> (Kennungspraefix, Reglername, Vorgabewert, Abfuhrweg)
KNOEPFE = [
    (MechExpandButton, "mech_expand", 3, "send_message"),
    (MechCollapseButton, "mech_collapse", 2, "send_message"),
    (MechHistoryButton, "mech_history", 5, "followup"),
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


def _interaktion():
    interaktion = MagicMock()
    interaktion.user.id = NUTZER
    interaktion.user.name = "pruefer"
    interaktion.channel.id = KANAL
    interaktion.response.defer = AsyncMock()
    interaktion.response.send_message = AsyncMock()
    interaktion.followup.send = AsyncMock()
    interaktion.message = MagicMock()
    interaktion.message.edit = AsyncMock()
    interaktion.edit_original_response = AsyncMock()
    return interaktion


async def _druecke(knopf, dienst):
    """Spenden AKTIV halten - sonst kehrt der Rueckruf vor der Bremse zurueck.

    ``_start_interaction`` muss ein ``AsyncMock`` sein: Expand und Collapse
    rufen es nach dem ``defer`` mit ``await``, und ein blankes ``MagicMock``
    ist nicht erwartbar ("'MagicMock' object can't be awaited"). Diese Gefahr
    war vor dem ersten Lauf notiert - ich hatte sie danach faelschlich fuer
    nicht eingetreten erklaert, weil pytest eine unbehandelte Ausnahme in einem
    asynchronen Test als FAILED meldet und nicht als ERROR. Das Etikett traegt
    diese Unterscheidung nicht.
    """
    interaktion = _interaktion()
    knopf.cog._start_interaction = AsyncMock(return_value=True)
    with patch(SPAM_PFAD, return_value=dienst), \
            patch("cogs.control_ui.is_donations_disabled", return_value=False):
        try:
            await knopf.callback(interaktion)
        except TypeError as e:
            # NUR TypeError, und nur aus der Tiefe: Nach der Bremse ruft der
            # Rueckruf eine Kette von Cog-Methoden mit await
            # (_create_overview_embed_expanded, _end_interaction im
            # Aufraeumpfad, ...). Jede ist an einer MagicMock nicht erwartbar,
            # und jede Reparatur der Vorrichtung legt die naechste frei - ein
            # Wettruesten, das nichts ueber die Bremse aussagt.
            #
            # Das Verschlucken ist eng begrenzt: Die Tests behaupten
            # anschliessend POSITIV (gefragt/vermerkt sind gefuellt, die Abfuhr
            # wurde gesendet). Ein TypeError aus der BREMSE wuerde also nicht
            # verborgen, sondern als leere Mitschrift sichtbar.
            if "can't be awaited" not in str(e):
                raise
    return interaktion


def _sender(interaktion, weg):
    return interaktion.followup.send if weg == "followup" else interaktion.response.send_message


def test_die_drei_knoepfe_tragen_die_erwartete_kennung():
    """Sicherung gegen ein stumpfes Werkzeug - GENAUER Wert, nicht blosse Existenz.

    Die vorige Runde hat gezeigt, dass ein ``assert knopf.custom_id`` gar nicht
    anschlagen kann; eine verfaelschte Kennung erfuellt es muehelos.
    """
    for klasse, praefix, _wert, _weg in KNOEPFE:
        knopf = klasse(MagicMock(), KANAL)
        assert knopf.custom_id == f"{praefix}_{KANAL}", (
            f"{klasse.__name__} traegt {knopf.custom_id!r} statt "
            f"{praefix}_{KANAL!r}."
        )


def test_die_drei_regler_stehen_auf_verschiedenen_werten(tmp_path):
    """Zweite Sicherung: Die Wertpruefungen unten sind nur etwas wert, wenn die
    Regler sich unterscheiden - und wenn sie von der Ersatzregel abweichen.
    """
    dienst = SpamProtectionService(config_dir=str(tmp_path))

    assert dienst.get_button_cooldown("gibt_es_nicht") == 5, "Ersatzregel geaendert"
    werte = {}
    for _klasse, praefix, wert, _weg in KNOEPFE:
        gemessen = dienst.get_button_cooldown(f"{praefix}_{KANAL}")
        assert gemessen == wert, (
            f"{praefix} liefert {gemessen} statt {wert} - die Praefix-Logik "
            "greift nicht mehr wie angenommen."
        )
        werte[praefix] = gemessen
    assert len(set(werte.values())) == 3, f"Regler nicht mehr verschieden: {werte}"


@pytest.mark.parametrize("klasse,praefix,wert,weg", KNOEPFE, ids=lambda x: str(x))
@pytest.mark.asyncio
async def test_der_dienst_wird_gefragt_und_vermerkt(tmp_path, klasse, praefix, wert, weg):
    """DER BEFUND: Die zustandsbehafteten Methoden werden nie gerufen."""
    dienst = _dienst(tmp_path)
    knopf = klasse(MagicMock(), KANAL)

    await _druecke(knopf, dienst)

    kennung = f"{praefix}_{KANAL}"
    assert dienst.gefragt == [(NUTZER, kennung)], (
        f"{klasse.__name__}: is_on_cooldown wurde nicht mit {kennung!r} gerufen, "
        f"sondern {dienst.gefragt!r}. Der Knopf bremst am Dienst vorbei und "
        "zahlt nicht in die Minutengrenze ein."
    )
    assert dienst.vermerkt == [(NUTZER, kennung)], (
        f"{klasse.__name__}: Der angenommene Druck wurde nicht vermerkt "
        f"({dienst.vermerkt!r})."
    )


@pytest.mark.parametrize("klasse,praefix,wert,weg", KNOEPFE, ids=lambda x: str(x))
@pytest.mark.asyncio
async def test_der_zweite_druck_wird_abgewiesen(tmp_path, klasse, praefix, wert, weg):
    """DER BEFUND, Wirkung - auf dem Abfuhrweg, den DIESER Knopf benutzt."""
    dienst = _dienst(tmp_path)
    knopf = klasse(MagicMock(), KANAL)
    kennung = f"{praefix}_{KANAL}"
    dienst.add_user_cooldown(NUTZER, kennung)
    dienst.vermerkt.clear()

    interaktion = await _druecke(knopf, dienst)
    sender = _sender(interaktion, weg)

    sender.assert_awaited_once()
    args = sender.await_args.args
    assert args, (
        f"{klasse.__name__}: Die Abfuhr traegt keinen Text - so ruft der "
        "Tiefenweg, nicht die Bremse."
    )
    assert "before using this button again" in args[0], (
        f"{klasse.__name__}: Gesendet wurde nicht der Katalogtext, sondern "
        f"{args[0]!r}."
    )
    assert sender.await_args.kwargs.get("ephemeral") is True, (
        f"{klasse.__name__}: Die Abfuhr ist nicht auf den Druckenden beschraenkt "
        "und erscheint damit fuer ALLE im Kanal."
    )


@pytest.mark.parametrize("klasse,praefix,wert,weg", KNOEPFE, ids=lambda x: str(x))
@pytest.mark.asyncio
async def test_die_fluechtige_ablage_am_objekt_entfaellt(tmp_path, klasse, praefix, wert, weg):
    """DER BEFUND, dritter Teil: keine Sperre, die mit dem Objekt stirbt."""
    dienst = _dienst(tmp_path)
    knopf = klasse(MagicMock(), KANAL)

    await _druecke(knopf, dienst)

    reste = [a for a in dir(knopf) if a.startswith("_last_click_")]
    assert not reste, (
        f"{klasse.__name__} legt weiterhin {reste} am Objekt ab. Diese Sperre "
        "ist beim naechsten Neuaufbau der Ansicht verschwunden."
    )
