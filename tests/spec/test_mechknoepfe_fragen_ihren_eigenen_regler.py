# -*- coding: utf-8 -*-
"""Die Mech-Regler aus dem Panel muessen verschieden sein und die Knoepfe sie tragen.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER URSPRUENGLICHE BEFUND (behoben in Commit 2970119). Das Panel bietet sieben
Regler fuer Mech-Knoepfe an (``mech_expand`` 3, ``mech_collapse`` 2,
``mech_donate`` 10, ``mech_history`` 5, ``mech_display`` 3, ``mech_story`` 5,
``mech_music`` 8). Drei Mech-Knoepfe bremsen ueberhaupt - und alle drei fragten
den Regler des INFO-Knopfes ab::

    MechExpandButton    custom_id mech_expand_…    -> get_button_cooldown("info")
    MechCollapseButton  custom_id mech_collapse_…  -> get_button_cooldown("info")
    MechHistoryButton   custom_id mech_history_…   -> get_button_cooldown("info")

Zwei Folgen fuer den Betreiber: Die ``mech_*``-Regler bewegten nichts, und alle
Mech-Knoepfe teilten sich einen Eimer MIT dem Info-Knopf - wer die Mech-Anzeige
aufklappte, sperrte sich die Info-Anzeige.

Korrigiert auf ``self.custom_id``: ``get_button_cooldown`` hat eine
Praefix-Logik, die aus ``mech_expand_12345`` den Regler ``mech_expand``
ableitet. Sie war vorhanden UND getestet
(``test_infrastructure_services.py`` prueft ``mech_donate_123456`` -> 10), aber
von niemandem benutzt: ein getesteter, toter Weg.

WAS FRUEHER HIER STAND UND WARUM ES FORT IST. Diese Datei enthielt drei
weitere Tests (``test_aufklappen/zuklappen/verlauf_fragt_den_eigenen_regler``).
Sie nagelten den MECHANISMUS fest - den Aufruf ``get_button_cooldown`` - und
ihre Vorrichtung setzte dafuer ``_last_click_<nutzer>`` direkt am Knopf.

Beides gibt es nicht mehr: Die spaetere Umstellung auf den Spam-Dienst ersetzt
``get_button_cooldown`` durch ``is_on_cooldown``/``add_user_cooldown`` und die
Ablage am Objekt durch die des Dienstes. Die drei Tests liessen sich also nicht
umhaengen - Aufbau, Mitschrift und Behauptung kodierten saemtlich den alten
Entwurf.

Entfernt wurden sie NICHT, um gruen zu werden, sondern weil dieselbe Eigenschaft
- jeder Mech-Knopf wird von seinem EIGENEN Regler bestimmt - in
``test_mechknoepfe_bremsen_ueber_den_dienst.py`` vollstaendiger geprueft wird:
Argumentwert, wirksamer Reglerwert, Vermerken des Drucks, Abfuhrweg je Knopf,
``ephemeral`` und der Wegfall der fluechtigen Ablage. Jede dieser Behauptungen
ist dort per Mutation als beissend belegt. Es verschwindet eine schwaechere
Doppelung, keine Abdeckung.

WAS HIER BLEIBT, sind die beiden Waechter - und sie sind es wert: Der erste
haelt die Kennungen fest, aus denen die Praefix-Logik die Regler ableitet; der
zweite, dass die drei Regler UEBERHAUPT verschieden stehen. Ohne den zweiten
waere eine Wertpruefung anderswo stumpf, ohne den ersten liefe die Ableitung
ins Leere.

KEINE ZEILENNUMMERN MEHR in diesem Kopftext: Die frueheren Angaben (:2301,
:2399, :2531) waren nach zwei Aenderungen still falsch. Klassennamen veralten
nicht.

NICHT TEIL DIESES BEFUNDS, hier festgehalten, damit es niemand zweimal
untersucht:

* ZEHN weitere Mech-Klassen bremsen GAR NICHT (``MechDonateButton``,
  ``MechDisplayButton``, ``MechDetailsButton``, ``MechPrivateDonateButton``,
  ``MechPrivateHistoryButton`` und die Views). Eigener Befund mit eigener
  Verhaltensaenderung - vom Betreiber bereits genehmigt, noch nicht umgesetzt.
* Fuer ``mech_music`` gibt es ueberhaupt keine Klasse.
* Die privaten Knoepfe heissen ``mech_private_donate_…``; die Praefix-Logik
  leitet daraus ``mech_private`` ab - einen Schluessel, den es nicht gibt.
  Wer dort ``self.custom_id`` einsetzt, landet auf der 5-Sekunden-Ersatzregel.
"""

from unittest.mock import MagicMock

from cogs.control_ui import MechCollapseButton, MechExpandButton, MechHistoryButton
from services.infrastructure.spam_protection_service import SpamProtectionService

KANAL = 77


def test_die_drei_knoepfe_lassen_sich_bauen():
    """Die Kennungen sind die Grundlage der Praefix-Ableitung.

    Geprueft wird der GENAUE Wert: Eine verfaelschte Kennung liefe in der
    Ableitung auf einen anderen Regler, und eine blosse Existenzpruefung
    koennte das nicht bemerken.
    """
    cog = MagicMock()

    assert MechExpandButton(cog, KANAL).custom_id == f"mech_expand_{KANAL}"
    assert MechCollapseButton(cog, KANAL).custom_id == f"mech_collapse_{KANAL}"
    assert MechHistoryButton(cog, KANAL).custom_id == f"mech_history_{KANAL}"


def test_die_regler_unterscheiden_sich_ueberhaupt(tmp_path):
    """Sicherung gegen ein stumpfes Werkzeug - und sie wirkt ueber diese Datei hinaus.

    Wertpruefungen sind nur etwas wert, wenn die Regler VERSCHIEDEN stehen.
    Stuenden sie alle gleich, waeren sie auch mit dem falschen Schluessel gruen.

    Besonders eng ist es bei ``mech_expand``: Vorgabe 3, und ``info`` ist
    ebenfalls 3 - ueber den Wert allein ist dort nicht zu unterscheiden, ob der
    richtige Regler greift. Deshalb prueft
    ``test_mechknoepfe_bremsen_ueber_den_dienst.py`` bei Expand das ARGUMENT und
    erst bei Collapse und History zusaetzlich den Wert. Wer hier spaeter Werte
    angleicht, nimmt jenen Tests die Schaerfe - und sieht es an diesem.
    """
    dienst = SpamProtectionService(config_dir=str(tmp_path))

    assert dienst.get_button_cooldown("info") == 3
    assert dienst.get_button_cooldown(f"mech_expand_{KANAL}") == 3, (
        "mech_expand und info stehen NICHT mehr beide auf 3 - dann kann der "
        "Expand-Test in der Nachbardatei zusaetzlich den Wert pruefen."
    )
    assert dienst.get_button_cooldown(f"mech_collapse_{KANAL}") == 2
    assert dienst.get_button_cooldown(f"mech_history_{KANAL}") == 5
