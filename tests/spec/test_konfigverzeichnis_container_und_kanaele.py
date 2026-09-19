# -*- coding: utf-8 -*-
"""Container- und Kanalkonfiguration muessen ``DDC_CONFIG_DIR`` folgen.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers. Die Arbeit selbst ist entschieden
("Konfigurationspfad", 2026-09-19).

DER BEFUND. ``DDC_CONFIG_DIR`` ist fuer NUTZER dokumentiert (README.md:141,
docs/CONFIGURATION.md:148: "Override config directory"). Sechs Stellen folgen
ihr, rund dreissig leiten ``<projekt>/config`` selbst her. Wer die Variable
setzt, bekommt eine gespaltene Konfiguration - und hier ist der Spalt am
sichtbarsten: Das Web-Panel liest ueber ``config_service`` (folgt der
Variable), aber diese fuenf lesen und schreiben daneben::

    ServerConfigService._load_container_configs  <projekt>/config/containers
    ContainerConfigSaveService.__init__          <projekt>/config/containers
    ChannelConfigService.__init__                <projekt>/config/channels, config.json
    ContainerInfoService.__init__                <projekt>/config/containers
    ConfigurationPageService._process_docker_containers  (Reihenfolge)

Der Bot fuehrte damit Container, die das Panel nicht zeigt, und umgekehrt.

ZWEITE FOLGE, Z2: ChannelConfigService und ContainerConfigSaveService legen
schon im Konstruktor Verzeichnisse unter dem ECHTEN config/ an - auch im
Testlauf, in dem tests/conftest.py die Variable auf ein Temp-Verzeichnis setzt.
Davor schuetzt heute nur der leere Mount in scripts/ddc_test.sh.

WIE HIER GEPRUEFT WIRD: Die Variable zeigt auf ein frisches Verzeichnis, in das
der Test Dateien legt; geprueft wird, ob die Dienste GENAU DIESE finden (bzw.
dorthin zielen). Die Erwartung stammt aus dem Test, nicht aus dem Dienst.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from services.config.channel_config_service import ChannelConfigService
from services.config.container_config_save_service import ContainerConfigSaveService
from services.config.server_config_service import ServerConfigService
from services.infrastructure.container_info_service import ContainerInfoService
from services.web.configuration_page_service import ConfigurationPageService


@pytest.fixture
def verzeichnis(tmp_path, monkeypatch):
    ziel = tmp_path / "eigene_konfig"
    (ziel / "containers").mkdir(parents=True)
    monkeypatch.setenv("DDC_CONFIG_DIR", str(ziel))
    return ziel


def _container(verzeichnis, name, **felder):
    daten = {"container_name": name, "active": True, **felder}
    (verzeichnis / "containers" / f"{name}.json").write_text(json.dumps(daten), encoding="utf-8")


def test_der_bot_findet_die_container_aus_dem_verzeichnis(verzeichnis):
    """DER BEFUND, sichtbarste Form: Der Bot kennt die Container nicht, die im
    eingestellten Verzeichnis stehen."""
    _container(verzeichnis, "probe_behaelter")

    namen = [s.get("docker_name") for s in ServerConfigService().get_all_servers()]

    assert "probe_behaelter" in namen, (
        f"ServerConfigService liest nicht aus DDC_CONFIG_DIR ({verzeichnis}); "
        f"gefunden: {namen!r}"
    )


def test_gespeichert_wird_ins_verzeichnis(verzeichnis):
    assert ContainerConfigSaveService().containers_dir == verzeichnis / "containers"


def test_kanaele_liegen_im_verzeichnis(verzeichnis):
    dienst = ChannelConfigService()
    assert dienst.channels_dir == verzeichnis / "channels"
    assert dienst.config_file == verzeichnis / "config.json"


def test_container_infos_liegen_im_verzeichnis(verzeichnis):
    assert ContainerInfoService().containers_dir == verzeichnis / "containers"


def test_die_konfigurationsseite_sortiert_nach_dem_verzeichnis(verzeichnis):
    """Die Reihenfolge kommt aus den ``order``-Feldern der Container-Dateien."""
    _container(verzeichnis, "alpha", order=1)
    _container(verzeichnis, "beta", order=2)
    live = [{"name": "beta"}, {"name": "alpha"}]

    with patch("app.utils.web_helpers.get_docker_containers_live", return_value=(live, None)):
        ergebnis = ConfigurationPageService()._process_docker_containers({})

    assert [c["name"] for c in ergebnis["live_containers"]] == ["alpha", "beta"], (
        "Die Konfigurationsseite sortiert nicht nach den order-Werten aus "
        "DDC_CONFIG_DIR."
    )
