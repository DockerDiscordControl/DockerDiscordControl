# -*- coding: utf-8 -*-
"""Eine unlesbare Altkonfiguration darf nicht wie "keine" aussehen.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND (Stufe 2, Punkt 2 - "wo etwas lautlos verschwindet"):
``ConfigMigrationService.migrate_legacy_v1_config_if_needed`` prueft, ob eine
alte ``config.json`` vorliegt::

    try:
        with open(self.legacy_config_file, ...) as f:
            test_data = json.load(f)
            if 'servers' in test_data or 'docker_name' in test_data:
                legacy_file = self.legacy_config_file
    except Exception:
        pass

    if not legacy_file:
        return  # No migration needed

Ist die Datei **unlesbar** - abgeschnitten, kaputtes JSON, Rechte weg -, faellt
sie in das ``except`` und ist danach von "es gibt keine Altkonfiguration" nicht
mehr zu unterscheiden. Die Migration wird uebersprungen, der Nutzer startet mit
leerer Konfiguration, und im Protokoll steht **nichts**.

WARUM DAS TEUER IST: Der Aufruf haengt an ``config_service.py:322``, also an
jedem ``get_config()``. Wer von v1.1.x aufsteigt und dessen ``config.json`` beim
Kopieren beschaedigt wurde, verliert Container, Kanalrechte und Einstellungen -
und sieht eine frisch eingerichtete Instanz statt einer Fehlermeldung. Nach
"unbemerkt schlaegt selten" ist das die teure Sorte.

WAS HIER **NICHT** VERLANGT WIRD: dass die Migration gelingt. Eine kaputte
Datei laesst sich nicht migrieren. Verlangt wird, dass der Fehler **sichtbar**
wird - eine Protokollzeile, die den Unterschied macht zwischen "nichts zu tun"
und "hier lag etwas, das ich nicht lesen konnte".

ABGRENZUNG: Das ``except`` fing frueher JEDE ``BaseException`` (nacktes
``except:``); das wurde am selben Tag projektweit umgestellt. Geprueft wird hier
nicht die Breite, sondern das **Verschlucken**.

GEGENPROBE (durchgefuehrt 2026-09-17): 1 rot, 3 gruen - genau wie vorhergesagt.

Der Fehlschlag war ``assert ''``: bei einer abgeschnittenen ``config.json`` kam
**kein einziger** Protokollsatz. Die drei vorher benannten Fallen sind damit
zugleich widerlegt - ``caplog`` greift (sonst haetten die Gegenrichtungen nicht
sauber unterschieden), der Dienst laesst sich bauen, und die abgeschnittene
Zeichenkette ist wirklich unlesbar.

Die beiden Gegenrichtungen waren von Anfang an gruen. Sie sind noetig: Ohne sie
koennte man bedingungslos warnen, und der Test oben bliebe gruen, waehrend jeder
normale Start eine Warnung faende. Ein Test mit Fehlalarmen wird ignoriert und
ist damit so wertlos wie ein gruener.

Nach der Korrektur: 4 gruen, ``tests/unit/services/configuration`` unveraendert
152 gruen.

WAS DIE KORREKTUR AENDERT: ``except Exception: pass`` wurde zu
``except (OSError, ValueError)`` **mit einer Warnung**. Der Ablauf bleibt gleich -
eine kaputte Datei laesst sich nicht migrieren -, aber der Unterschied zwischen
"nichts zu tun" und "hier lag etwas Unlesbares" ist jetzt sichtbar.

ZU Z9 GEPRUEFT: Die Meldung nennt nur den Dateinamen, den Ausnahmetyp und den
Ausnahmetext - **nie** den Inhalt. Eine v1.1.x-``config.json`` traegt den
Bot-Token, und ein Protokoll ist Platte. Belegt per AST: kein Protokollaufruf in
dieser Datei reicht eine Inhaltsvariable weiter. Ein erster, handgeschriebener
Waechter hatte hier faelschlich Alarm geschlagen, weil er die Zeichenkette im
gesamten Ersatzblock suchte statt in den Argumenten des Aufrufs.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict

import pytest

from services.config.config_migration_service import ConfigMigrationService


def _dienst(tmp_path: Path) -> ConfigMigrationService:
    """Migrationsdienst mit echten Verzeichnissen unter ``tmp_path``.

    Gleiche Bauart wie ``TestConfigMigrationService._make`` in
    ``tests/unit/services/configuration/test_config_full.py:714``.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    return ConfigMigrationService(
        config_dir=config_dir,
        channels_dir=config_dir / "channels",
        containers_dir=config_dir / "containers",
    )


def _save_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _load_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(default)


def _nichts(_cfg):
    """Auszugsfunktion, die nichts liefert - sie darf hier nie gerufen werden."""
    return {}


def _migrieren(svc):
    svc.migrate_legacy_v1_config_if_needed(
        _load_json, _save_json, _nichts, _nichts, _nichts, _nichts
    )


def test_der_dienst_laesst_sich_ueberhaupt_bauen(tmp_path):
    """Sicherung gegen ein stumpfes Werkzeug.

    Scheitert der Aufbau, waeren die Tests unten rot oder gruen, ohne dass es
    etwas mit der Zusicherung zu tun haette.
    """
    svc = _dienst(tmp_path)
    assert svc.legacy_config_file.name == "config.json", (
        f"Die Altdatei heisst unerwartet {svc.legacy_config_file.name!r} - "
        "die Tests unten zielen dann auf die falsche Datei."
    )


def test_unlesbare_altkonfiguration_wird_gemeldet(tmp_path, caplog):
    """Eine kaputte config.json darf nicht wie "keine" behandelt werden."""
    svc = _dienst(tmp_path)
    svc.legacy_config_file.write_text(
        '{"servers": [{"docker_name": "nginx"}], "guild_id": ',  # abgeschnitten
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        _migrieren(svc)

    meldungen = " ".join(satz.getMessage() for satz in caplog.records)
    assert meldungen.strip(), (
        "Eine unlesbare config.json wurde stillschweigend uebersprungen. Sie ist "
        "damit von 'es gibt keine Altkonfiguration' nicht zu unterscheiden: Der "
        "Nutzer startet mit leerer Konfiguration und erfaehrt nie, warum. "
        "Verlangt ist keine gelungene Migration, nur eine sichtbare Meldung."
    )


def test_fehlende_altkonfiguration_meldet_nichts(tmp_path, caplog):
    """Die Gegenrichtung - sonst waere 'melde immer etwas' auch gruen.

    Ohne diesen Fall koennte man eine Warnung bedingungslos ausgeben und der
    Test oben bliebe gruen, waehrend jeder normale Start eine Warnung faende.
    """
    svc = _dienst(tmp_path)
    assert not svc.legacy_config_file.exists()

    with caplog.at_level(logging.WARNING):
        _migrieren(svc)

    meldungen = [satz.getMessage() for satz in caplog.records]
    assert not meldungen, (
        f"Ohne Altkonfiguration darf nichts gemeldet werden, es kam: {meldungen}"
    )


def test_lesbare_altkonfiguration_ohne_server_meldet_nichts(tmp_path, caplog):
    """Eine gueltige, aber unpassende Datei ist kein Fehlerfall.

    Eine v2.0-``config.json`` ohne ``servers``/``docker_name`` ist lesbar und
    schlicht nicht zu migrieren. Wuerde auch sie warnen, entstuende bei jedem
    Start eine Meldung - und ein Test, der Fehlalarme erzeugt, wird ignoriert.
    """
    svc = _dienst(tmp_path)
    _save_json(svc.legacy_config_file, {"language": "de", "timezone": "UTC"})

    with caplog.at_level(logging.WARNING):
        _migrieren(svc)

    meldungen = [satz.getMessage() for satz in caplog.records]
    assert not meldungen, (
        f"Eine lesbare Datei ohne Server ist kein Fehler, es kam: {meldungen}"
    )
