# -*- coding: utf-8 -*-
"""Die Mech-Geschichten muessen auf jeder Installation da sein - in der
Sprache des Bots.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers. Entschieden ist die Arbeit: "Mitliefern".

DER BEFUND, ZWEITEILIG.

1. ``config/mech/stories/{de,en,fr}.txt`` lagen nur auf dem Server des
   Betreibers (nie im Repository, nicht im Image). Auf jeder Neuinstallation
   liefert ``MechStoryService`` ``{}``, und der Story-Knopf antwortet auf
   JEDER Stufe "No story chapter available for this mech yet."
2. Wo die Dateien existieren, bekam jeder Server die DEUTSCHE Fassung:
   ``get_all_chapters()`` hat die Vorgabe ``'de'``, und
   ``MechHistoryButton._load_epic_story_chapters`` (Story-Knopf UND
   Verlaufsansicht) gibt keine Sprache mit.

DIE KORREKTUR: Die drei Dateien liegen als Vorgabe in
``services/mech/defaults/stories/`` (byteweise vom Server des Betreibers,
Pruefsumme verglichen). Eine Datei unter ``<Konfigverzeichnis>/mech/stories/``
gewinnt. Der Rueckfall greift NUR ohne ausdruecklich uebergebenes Verzeichnis -
wer eines uebergibt (Tests), bekommt weiter genau dieses. Die Aufrufer geben die
Bot-Sprache mit; fuer andere Sprachen als de/en/fr faellt der Dienst wie bisher
auf Englisch zurueck.
"""

from unittest.mock import MagicMock, patch

import pytest

from cogs.control_ui import MechHistoryButton
from cogs.translation_manager import translation_manager
from services.mech.mech_story_service import MechStoryService, get_mech_story_service


@pytest.fixture
def neuinstallation(tmp_path, monkeypatch):
    ziel = tmp_path / "leere_konfig"
    ziel.mkdir()
    monkeypatch.setenv("DDC_CONFIG_DIR", str(ziel))
    get_mech_story_service().clear_cache()
    try:
        yield ziel
    finally:
        get_mech_story_service().clear_cache()


def test_eine_neuinstallation_hat_geschichten(neuinstallation):
    """DER BEFUND, erster Teil."""
    kapitel = MechStoryService().get_all_chapters("en")
    assert "prologue1" in kapitel and "chapter1" in kapitel and "epilogue" in kapitel, (
        f"Eine Neuinstallation hat keine Mech-Geschichten: {sorted(kapitel)}"
    )


def test_die_sprachen_unterscheiden_sich(neuinstallation):
    """Waechter: Sonst bewiese der Sprachtest unten nichts."""
    dienst = MechStoryService()
    assert dienst.get_all_chapters("de")["chapter1"] != dienst.get_all_chapters("en")["chapter1"]


def test_die_eigene_geschichte_gewinnt(neuinstallation):
    """Abgrenzung: Die Ueberschreibung des Betreibers bleibt wirksam."""
    (neuinstallation / "mech" / "stories").mkdir(parents=True)
    (neuinstallation / "mech" / "stories" / "en.txt").write_text(
        "Titel\n\nChapter I: Eigen\nEigener Text.", encoding="utf-8")

    assert "Eigener Text." in MechStoryService().get_all_chapters("en")["chapter1"]


def test_ein_uebergebenes_verzeichnis_faellt_nicht_zurueck(tmp_path):
    """Abgrenzung: Wer ein Verzeichnis uebergibt, bekommt genau dieses."""
    assert MechStoryService(story_dir=str(tmp_path)).get_all_chapters("en") == {}


def test_der_story_knopf_spricht_die_sprache_des_bots(neuinstallation):
    """DER BEFUND, zweiter Teil: bisher immer 'de'."""
    erwartet = MechStoryService().get_all_chapters("en")
    assert erwartet, "Ohne mitgelieferte Geschichten bewiese dieser Test nichts."

    with patch.object(translation_manager, "get_current_language", return_value="en"):
        geladen = MechHistoryButton(MagicMock(), 1)._load_epic_story_chapters()

    assert geladen == erwartet, (
        "Der Story-Knopf laedt nicht die Geschichte in der Sprache des Bots (en)."
    )
