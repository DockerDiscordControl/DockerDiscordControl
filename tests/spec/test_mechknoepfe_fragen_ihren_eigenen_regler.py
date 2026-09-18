# -*- coding: utf-8 -*-
"""Die Mech-Knoepfe muessen ihren EIGENEN Regler abfragen, nicht den des Info-Knopfes.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND. Das Panel bietet sieben Regler fuer Mech-Knoepfe an
(``_spam_protection_modal.html``: ``mech_expand`` 3, ``mech_collapse`` 2,
``mech_donate`` 10, ``mech_history`` 5, ``mech_display`` 3, ``mech_story`` 5,
``mech_music`` 8). Drei Mech-Knoepfe bremsen ueberhaupt - und alle drei fragen
den falschen Schluessel ab::

    MechExpandButton   (:2301)  custom_id mech_expand_…    -> get_button_cooldown("info")
    MechCollapseButton (:2399)  custom_id mech_collapse_…  -> get_button_cooldown("info")
    MechHistoryButton  (:2531)  custom_id mech_history_…   -> get_button_cooldown("info")

WAS DER BETREIBER DAVON SIEHT, und es sind zwei Dinge:

1. Er stellt ``mech_history`` auf einen Wert, speichert, und nichts aendert
   sich - gebremst wird weiter nach ``info``.
2. Alle Mech-Knoepfe teilen sich einen Eimer MIT dem Info-Knopf. Wer die
   Mech-Anzeige aufklappt, sperrt sich damit die Info-Anzeige, und umgekehrt.
   Das ist kein gedachter Fall: ``ProtectedInfoButton``, ``EditInfoButton`` und
   ``InfoDropdownButton`` benutzen denselben Schluessel.

WARUM ``self.custom_id`` UND KEIN LITERAL: ``get_button_cooldown:178-184`` hat
eine Praefix-Logik, die aus ``mech_expand_12345`` den Schluessel ``mech_expand``
ableitet - genau das Format der ``custom_id``. Sie ist vorhanden UND getestet
(``test_infrastructure_services.py:793-796`` prueft ``mech_donate_123456`` -> 10),
aber sie wird von niemandem benutzt: ein getesteter, toter Weg. Die
urspruengliche Absicht ist damit belegt, nicht geraten. Mit dieser Korrektur
wird sie zum ersten Mal begangen.

NICHT TEIL DIESES BEFUNDS, hier nur festgehalten, damit es niemand zweimal
untersucht:

* ZEHN weitere Mech-Klassen bremsen GAR NICHT (``MechDonateButton``,
  ``MechDisplayButton``, ``MechDetailsButton``, ``MechPrivateDonateButton``,
  ``MechPrivateHistoryButton`` und die Views). Das ist ein eigener Befund mit
  eigener Verhaltensaenderung - heute freie Knoepfe wuerden gebremst.
* Fuer ``mech_music`` gibt es ueberhaupt keine Klasse.
* Die privaten Knoepfe heissen ``mech_private_donate_…``; die Praefix-Logik
  leitete daraus ``mech_private`` ab - einen Schluessel, den es nicht gibt.
  Wer dort ``self.custom_id`` einsetzt, landet auf der 5-Sekunden-Ersatzregel.

WIE HIER GEPRUEFT WIRD: ueber die echten Knoepfe, den echten Rueckruf und einen
ECHTEN ``SpamProtectionService`` (auf ``tmp_path``, ohne Datei, also mit den
Vorgaben). Er wird nur durch eine kleine Mitschrift durchgereicht, die Aufruf
UND Antwort festhaelt - die Zahlen kommen vom echten Dienst. Ein reiner Mock
koennte jede Zahl liefern und wuerde nicht zeigen, ob der richtige Regler
greift.

Bewusst KEIN ``MagicMock(wraps=…)`` mit ``spy_return``: Das ist die
Schnittstelle von pytest-mock, nicht von unittest.mock. Ein solcher Zugriff
haette einen AttributeError geworfen - einen FEHLER statt eines Fehlschlags,
und damit ein wertloses Rot.

Der Rueckruf wird bewusst auf dem ABFUHRWEG gefahren (Zeitstempel vorher
gesetzt): Dann kehrt er unmittelbar nach der Schluesselabfrage zurueck. Das ist
kein Bequemlichkeitsentscheid - die ``except``-Zweige der drei Rueckrufe fangen
nur ``(RuntimeError, ValueError, KeyError)`` und Discord-Fehler, ein ``TypeError``
aus der Tiefe wuerde also als FEHLER statt als Fehlschlag erscheinen.

ZWEI ABFUHRWEGE, KEIN EINHEITLICHES MUSTER - gemessen, nicht angenommen:
``MechExpandButton`` und ``MechCollapseButton`` weisen mit
``response.send_message`` ab und rufen ``defer`` erst DANACH;
``MechHistoryButton`` ruft ``defer(ephemeral=True)`` MITTEN im Bremsblock
(``:2539``) und weist per ``followup.send`` ab. Ein Test, der fuer alle drei
denselben Weg annimmt, waere fuer einen davon rot aus dem falschen Grund.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.control_ui import MechCollapseButton, MechExpandButton, MechHistoryButton
from services.infrastructure.spam_protection_service import SpamProtectionService

KANAL = 77
NUTZER = 4242


class _Mitschrift:
    """Reicht an den ECHTEN Dienst durch und schreibt Aufruf samt Antwort mit.

    ``aufrufe`` wird damit zur vollstaendigen Behauptung: Sie nagelt Argument,
    zurueckgegebenen Wert und die Anzahl der Aufrufe in einem fest.
    """

    def __init__(self, echt):
        self._echt = echt
        self.aufrufe = []

    def get_button_cooldown(self, name):
        wert = self._echt.get_button_cooldown(name)
        self.aufrufe.append((name, wert))
        return wert

    def __getattr__(self, name):
        return getattr(self._echt, name)


def _dienst(tmp_path):
    """Echter Dienst mit den Vorgaben, nur zum Mitschreiben durchgereicht."""
    return _Mitschrift(SpamProtectionService(config_dir=str(tmp_path)))


def _interaktion():
    interaktion = MagicMock()
    interaktion.user.id = NUTZER
    interaktion.channel.id = KANAL
    interaktion.response.defer = AsyncMock()
    interaktion.response.send_message = AsyncMock()
    interaktion.followup.send = AsyncMock()
    return interaktion


def _auf_abfuhrweg(knopf):
    """Setzt den Zeitstempel, damit die Bremse greift und der Rueckruf umkehrt."""
    setattr(knopf, f"_last_click_{NUTZER}", time.time())


async def _druecke(knopf, dienst):
    interaktion = _interaktion()
    _auf_abfuhrweg(knopf)
    with patch(
        "services.infrastructure.spam_protection_service.get_spam_protection_service",
        return_value=dienst,
    ), patch("cogs.control_ui.is_donations_disabled", return_value=False):
        await knopf.callback(interaktion)
    return interaktion


def test_die_drei_knoepfe_lassen_sich_bauen(tmp_path):
    """Sicherung gegen ein stumpfes Werkzeug - muss VOR und NACH der Korrektur gruen sein."""
    cog = MagicMock()

    assert MechExpandButton(cog, KANAL).custom_id == f"mech_expand_{KANAL}"
    assert MechCollapseButton(cog, KANAL).custom_id == f"mech_collapse_{KANAL}"
    assert MechHistoryButton(cog, KANAL).custom_id == f"mech_history_{KANAL}"


def test_die_regler_unterscheiden_sich_ueberhaupt(tmp_path):
    """Zweite Sicherung gegen ein stumpfes Werkzeug, und die wichtigere.

    Die Wertpruefungen unten sind nur etwas wert, wenn die Regler
    VERSCHIEDEN stehen. Stuenden alle auf demselben Wert, waeren sie auch mit
    dem falschen Schluessel gruen.

    Genau das ist bei ``mech_expand`` der Fall: Vorgabe 3, und ``info`` ist
    ebenfalls 3. Deshalb hat der Expand-Test unten BEWUSST keine Wertpruefung,
    sondern nur die Argumentpruefung. Wer hier spaeter Werte angleicht, sieht
    an diesem Test, dass er den Tests darunter die Schaerfe nimmt.
    """
    dienst = SpamProtectionService(config_dir=str(tmp_path))

    assert dienst.get_button_cooldown("info") == 3
    assert dienst.get_button_cooldown(f"mech_expand_{KANAL}") == 3, (
        "mech_expand und info stehen NICHT mehr beide auf 3 - dann kann der "
        "Expand-Test unten zusaetzlich den Wert pruefen."
    )
    assert dienst.get_button_cooldown(f"mech_collapse_{KANAL}") == 2
    assert dienst.get_button_cooldown(f"mech_history_{KANAL}") == 5


@pytest.mark.asyncio
async def test_aufklappen_fragt_den_eigenen_regler(tmp_path):
    """DER BEFUND fuer MechExpandButton.

    Nur Argumentpruefung - die Begruendung steht im Waechter oben.
    """
    dienst = _dienst(tmp_path)
    knopf = MechExpandButton(MagicMock(), KANAL)

    await _druecke(knopf, dienst)

    assert [name for name, _ in dienst.aufrufe] == [f"mech_expand_{KANAL}"], (
        f"Der Knopf fragt {dienst.aufrufe!r} ab statt seinen eigenen Regler "
        f"mech_expand_{KANAL}. Der mech_expand-Regler im Panel bewegt damit "
        "nichts, und das Aufklappen sperrt zugleich den Info-Knopf."
    )


@pytest.mark.asyncio
async def test_zuklappen_fragt_den_eigenen_regler(tmp_path):
    """DER BEFUND fuer MechCollapseButton - Argument UND wirksamer Wert."""
    dienst = _dienst(tmp_path)
    knopf = MechCollapseButton(MagicMock(), KANAL)

    interaktion = await _druecke(knopf, dienst)

    assert dienst.aufrufe == [(f"mech_collapse_{KANAL}", 2)], (
        f"Erwartet war die Abfrage von mech_collapse_{KANAL} mit dem Wert 2 "
        f"(sein eigener Regler); mitgeschrieben wurde {dienst.aufrufe!r}. Steht "
        "dort 'info' mit 3, bremst der Knopf nach dem Regler des Info-Knopfes "
        "und der mech_collapse-Regler im Panel bewegt nichts."
    )
    interaktion.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_verlauf_fragt_den_eigenen_regler(tmp_path):
    """DER BEFUND fuer MechHistoryButton.

    Dieser Knopf weist ueber ``followup.send`` ab, nicht ueber
    ``send_message`` - er bestaetigt die Interaktion mitten im Bremsblock.
    """
    dienst = _dienst(tmp_path)
    knopf = MechHistoryButton(MagicMock(), KANAL)

    interaktion = await _druecke(knopf, dienst)

    assert dienst.aufrufe == [(f"mech_history_{KANAL}", 5)], (
        f"Erwartet war die Abfrage von mech_history_{KANAL} mit dem Wert 5 "
        f"(sein eigener Regler); mitgeschrieben wurde {dienst.aufrufe!r}."
    )
    interaktion.followup.send.assert_awaited_once()
