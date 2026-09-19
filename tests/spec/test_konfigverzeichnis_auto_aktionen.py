# -*- coding: utf-8 -*-
"""Regeln und Laufzeitzustand der Auto-Aktionen muessen in ``DDC_CONFIG_DIR``
liegen.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND. ``AutoActionConfigService`` (auto_actions.json) und
``AutoActionStateService`` (auto_actions_state.json) leiten ihre Dateien aus
``Path(__file__).parents[2] / "config"`` her und beachten die Variable nicht.
Beide sind die einzigen Leser und Schreiber ihrer Datei - einen Spalt zwischen
zwei Lesern gibt es nicht. Die Folgen sind dieselben wie bei der Admin-Liste
(8ac5427):

1. Wer ``DDC_CONFIG_DIR`` auf sein Volume zeigt, hat die Regeln und die
   Abklingzustaende ausserhalb davon - beim Neuanlegen des Containers weg.
2. Z2, hier schwerer: ``AutoActionConfigService`` SCHREIBT schon im
   Konstruktor eine Vorgabedatei, wenn keine existiert - im Testlauf also ins
   ECHTE config/.

WIE HIER GEPRUEFT WIRD: Der Konstruktor wird gegen ein leeres Verzeichnis
gebaut (die Vorgabedatei muss DORT entstehen); der Zustand wird aus einer
Datei gelesen, die der Test anlegt.
"""

import json

import pytest

from services.automation.auto_action_config_service import AutoActionConfigService
from services.automation.auto_action_state_service import AutoActionStateService


@pytest.fixture
def verzeichnis(tmp_path, monkeypatch):
    ziel = tmp_path / "eigene_konfig"
    ziel.mkdir()
    monkeypatch.setenv("DDC_CONFIG_DIR", str(ziel))
    return ziel


def test_die_vorgabedatei_entsteht_im_verzeichnis(verzeichnis):
    """DER BEFUND, Z2-Teil: Der Konstruktor schreibt."""
    dienst = AutoActionConfigService()

    assert dienst.config_file == verzeichnis / "auto_actions.json"
    assert (verzeichnis / "auto_actions.json").exists(), (
        "Die Vorgabe-auto_actions.json entstand nicht in DDC_CONFIG_DIR."
    )


def test_der_zustand_kommt_aus_dem_verzeichnis(verzeichnis):
    (verzeichnis / "auto_actions_state.json").write_text(json.dumps({
        "global_last_triggered": 1234.5,
        "rule_cooldowns": {"regel_probe": 99.0},
        "container_cooldowns": {},
        "trigger_history": {},
    }), encoding="utf-8")

    dienst = AutoActionStateService()

    assert dienst.state_file == verzeichnis / "auto_actions_state.json"
    assert dienst.rule_cooldowns == {"regel_probe": 99.0}, (
        "Der Abklingzustand der Auto-Aktionen kommt nicht aus DDC_CONFIG_DIR."
    )
