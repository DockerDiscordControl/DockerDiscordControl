# -*- coding: utf-8 -*-
# @deckt Z2
"""Z2 - Ein Testlauf fasst niemals Produktivdaten an.

Kein Test schreibt in das echte ``config/``, gleich mit welchem Runner er
gestartet wird und gleich, ob ``DDC_CONFIG_DIR`` gesetzt ist.

Warum genau dieser Dienst: ``MechResetService`` loest sein Verzeichnis als
einziger im Projekt gegen die Projektwurzel auf und ignoriert ``DDC_CONFIG_DIR``.
``tests/unit/services/mech/test_mech_data_services.py`` ruft ``quick_mech_reset()``
scharf auf - der Reset ueberschreibt ``mech_state.json``/``evolution_mode.json``
und loescht ``achieved_levels.json``. Dass dabei bisher nichts kaputtging, lag
allein am leeren Mount ueber ``/app/config`` in ``scripts/ddc_test.sh``. Wer die
Suite anders startet (``scripts/run_tests_unraid.sh``, ``run_tests.sh``), hat
diesen Schutz nicht.

Diese Tests fuehren bewusst KEINE Reset-Operation aus. Geprueft wird die
Pfadaufloesung - denn genau sie entscheidet, wohin geschrieben wuerde. Einen
echten Reset auszuloesen, um zu sehen wohin er trifft, waere der Fehler selbst.

GEGENPROBE (durchgefuehrt 2026-09-16): Vor der Korrektur in
``services/mech/mech_reset_service.py`` schlugen ``test_default_service_honours_ddc_config_dir``
und ``test_no_write_target_inside_repository`` fehl - der Dienst zeigte auf
``<repo>/config``. Nach der Korrektur gruen. Der dritte Test
(``test_explicit_relative_path_still_resolves_against_project``) war vorher wie
nachher gruen und haelt fest, dass die Korrektur den ausdruecklich uebergebenen
Pfad NICHT veraendert.
"""

from pathlib import Path

import pytest

import services.mech.mech_reset_service as mrs_mod
from services.mech.mech_reset_service import MechResetService, get_mech_reset_service

# Projektwurzel: services/mech/mech_reset_service.py -> parents[2]
REPO_ROOT = Path(mrs_mod.__file__).resolve().parents[2]


@pytest.fixture
def isolated_singleton():
    """Singleton sichern und wiederherstellen.

    Ohne das wuerde dieser Test eine auf ein Temp-Verzeichnis zeigende Instanz
    fuer den Rest des Laufs hinterlassen - genau die Sorte Verschmutzung, die
    die Bestandsaufnahme in dieser Suite als Problem benannt hat.
    """
    vorher = mrs_mod._mech_reset_service
    mrs_mod._mech_reset_service = None
    try:
        yield
    finally:
        mrs_mod._mech_reset_service = vorher


def _write_targets(service: MechResetService):
    """Alle Dateien, die der Dienst anfassen wuerde."""
    return [
        service.mech_state_file,
        service.evolution_mode_file,
        service.achieved_levels_file,
    ]


def test_default_service_honours_ddc_config_dir(monkeypatch, tmp_path):
    """Ohne Argument konstruiert: DDC_CONFIG_DIR bestimmt das Verzeichnis."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))

    service = MechResetService()

    assert service.config_dir == tmp_path
    for ziel in _write_targets(service):
        assert ziel.parent == tmp_path, f"{ziel} liegt nicht unter DDC_CONFIG_DIR"


def test_no_write_target_inside_repository(monkeypatch, tmp_path, isolated_singleton):
    """Der Weg, den die Tests tatsaechlich nehmen: ueber den Singleton.

    ``quick_mech_reset()`` benutzt ``get_mech_reset_service()``. Zeigt der auf
    das Repository, zerstoert ein Testlauf echte Daten.
    """
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))

    service = get_mech_reset_service()

    for ziel in _write_targets(service):
        assert REPO_ROOT not in ziel.resolve().parents, (
            f"Schreibziel {ziel} liegt im Repository - ein Testlauf koennte "
            f"echte Konfiguration zerstoeren"
        )


def test_explicit_relative_path_still_resolves_against_project():
    """Ein ausdruecklich uebergebener relativer Pfad bleibt unveraendert.

    Haelt fest, dass die Korrektur fuer Z2 nur den Standardfall betrifft.
    Spiegelt ``test_mech_data_services.py:791`` - hier, weil es die Grenze der
    Zusicherung markiert.
    """
    service = MechResetService(config_dir="custom_cfg")

    assert service.config_dir.is_absolute()
    assert service.config_dir.name == "custom_cfg"
