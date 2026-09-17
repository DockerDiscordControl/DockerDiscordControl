# -*- coding: utf-8 -*-
"""Ein Container darf nicht auf einem Weg existieren und auf dem anderen fehlen.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND (Stufe 2, Punkt 2 - lautloses Wegraeumen). Dieselben Dateien unter
``config/containers/*.json`` werden von ZWEI Lesern ausgewertet, mit
entgegengesetzter Vorgabe fuer einen fehlenden ``active``-Schluessel::

    services/config/server_config_service.py:90   container_data.get('active', True)
    services/config/config_loader_service.py:274  container_config.get('active', False)

Dass es dieselben Dateien sind, ist belegt: ``server_config_service.py:46-47``
bildet ``Path(__file__).parents[2] / 'config' / 'containers'``, der Lader
bekommt ``containers_dir`` aus ``ConfigService:200`` - beide landen bei
``<projekt>/config/containers``.

DIE FOLGE: Eine Containerdatei ohne ``active`` ist fuer den einen Leser da und
fuer den anderen weg. ``config_loader_service.py:204`` fuellt damit
``config['servers']``, und ``cogs/docker_control.py:1046`` sucht die
Serverkonfiguration genau dort. ``get_all_servers()`` dagegen speist rund ein
Dutzend Aufrufstellen in ``docker_control.py``, ``status_info_integration.py``
und den Info-Dialogen. Angekuendigt wird der Verlust durch eine einzige
``logger.debug``-Zeile ("Skipping inactive container") - im Normalbetrieb
schreibt DDC auf INFO, die Zeile erscheint also nirgends.

WO DER SCHLUESSEL FEHLEN KANN - gemessen, nicht vermutet:
``config_migration_service.py:230`` schreibt ``save_json_func(container_file,
server)``, also den Alteintrag aus ``docker_config.json`` WORTWOERTLICH. Das
Wort ``active`` kommt in dieser Datei kein einziges Mal vor; ebensowenig in
``services/infrastructure/container_info_service.py``, das ebenfalls
Containerdateien schreibt. Und die Projektdaten selbst kennen die Gestalt ohne
den Schluessel: ``tests/unit/audit_2026_09/test_r2_g2_config_fold.py:205``
benutzt ``{"servers": [{"docker_name": "web"}], ...}`` als monolithische
v1.1.x-Konfiguration.

WAS DIESER TEST NICHT ENTSCHEIDET: welche der beiden Vorgaben richtig ist. Es
gibt gute Gruende fuer beide, und die Wahl ist eine Betreiberentscheidung, keine
meine. Geprueft wird ausschliesslich, dass die beiden Wege sich EINIG sind -
denn ein Container, der halb da ist, ist in jeder Lesart ein Fehler.

Die Konvention "fehlt heisst aktiv" ist allerdings die besser belegte Seite:
``server_config_service.py:89`` und ``cogs/admin_overview.py:463`` schreiben sie
als Kommentar aus, und zwei Tests nageln sie fest
(``tests/unit/audit_2026_09/test_pkg_b_admin_overview.py:74`` mit einem
Container namens ``no_active_field``, ``test_config_full.py:1027-1033``).
Fuer ``config_loader_service.py:274`` gibt es keinen solchen Test: Der
scheinbare Gegenbeleg ``test_config_service.py:378`` schreibt AUSSCHLIESSLICH
Dateien mit ausdruecklichem ``active`` (:361-373) und sagt ueber den fehlenden
Schluessel nichts.

EIN EIGENER FEHLER, hier festgehalten, weil er sich zweimal wiederholt hat: Ich
habe zunaechst behauptet, die Lader-Seite sei ungetestet (Suche nach dem
FUNKTIONSNAMEN, waehrend die Tests ueber ``get_config()`` laufen), dann das
Gegenteil (Lesen des DOCSTRINGS statt der Eingabe). Erst die Fixture-Zeilen
haben es entschieden. Beide Male derselbe Schnitt: etwas ueber einen Test
geglaubt, ohne anzusehen, womit er gefuettert wird.

GEGENPROBE (durchgefuehrt 2026-09-17) - zwei Messungen, weil zwei verschiedene
Dinge zu belegen waren:

*1. Der Befundtest war VOR der Korrektur rot*, mit genau der vorhergesagten
Aufteilung::

    nur ueber get_all_servers():   ['ohne_schluessel']
    nur ueber config['servers']:   []

Das Protokoll bestaetigt die Ursache statt sie zu behaupten: "Real modular
config loaded: 1 servers" - der Lader sah nur EINE der beiden Dateien, obwohl
beide im selben Verzeichnis lagen. Die Positivkontrolle war dabei gruen, der
Unterschied kam also nicht aus zwei verschiedenen Verzeichnissen. Nach der
Korrektur: 2 gruen.

*2. Die Positivkontrolle war von Anfang an gruen* - also bis zum Beweis des
Gegenteils ein Test, der nicht fehlschlagen kann. Sie ist aber diejenige, die
den Befundtest ueberhaupt aussagekraeftig macht: Zeigten die beiden Leser eines
Tages auf verschiedene Verzeichnisse, faende der Befundtest einen Unterschied,
der nichts bedeutet. Mutation: ``if False and container_config.get(...)``, der
Lader liefert also gar nichts mehr::

    mit Mutation -> 2 failed, 0 passed

Rot wurde die Kontrolle an IHRER eigenen Zeile (:218,
``assert MIT_SCHLUESSEL in ueber_lader`` -> ``assert 'mit_schluessel' in
set()``), mit "Loaded 0 active containers for Discord" im Protokoll. Das zweite
Rot ist die erklaerbare Mitwirkung: Ein blinder Lader kippt zwangslaeufig auch
den Mengenvergleich. Mutation zurueckgenommen, danach wieder 2 gruen.

*Vier Wege, auf denen dieses Rot wertlos gewesen waere*, standen VOR dem Lauf
fest und traten alle nicht ein: Kontrolle bleibt gruen (waere hohl); sie faellt
an der Verdrahtungs-Behauptung (die Mutation fasst keine Pfade an); sie faellt
auf der ServerConfigService-Seite (die Mutation reicht nicht dorthin); Sammel-
oder Importfehler (misst nichts).

BETROFFENE GRUPPEN, alle gruen gemessen: services/configuration 152,
audit_2026_09 564, cogs 267, services/web 358, services/scheduler 196,
test_container_info_service.py 14, extended 731, app_modules 73, spec 79.
"""

import json

import pytest

from services.config import server_config_service as scs_mod
from services.config.config_loader_service import LEGACY_FOLD_MARKER, ConfigLoaderService
from services.config.config_service import get_config_service
from services.config.server_config_service import ServerConfigService

MIT_SCHLUESSEL = "mit_schluessel"
OHNE_SCHLUESSEL = "ohne_schluessel"


@pytest.fixture
def beide_leser(tmp_path, monkeypatch):
    """Beide Container-Leser auf DASSELBE Wegwerf-Verzeichnis richten.

    ConfigService: Pfade umbiegen und ``_loader_service`` neu bauen - ohne den
    Neubau liest der Lader weiter an den Pfaden, mit denen er im Konstruktor
    gebaut wurde. Danach die Zwischenspeicher leeren, sonst faerbt ein Ergebnis
    aus einem frueheren Test diesen Lauf gruen. Uebernommen aus
    ``tests/unit/services/configuration/test_config_service.py:41``.

    ServerConfigService: Es leitet sein Verzeichnis aus ``Path(__file__)
    .parents[2]`` ab und beachtet ``DDC_CONFIG_DIR`` NICHT (:46-47). Deshalb
    wird ``__file__`` auf eine Scheindatei drei Ebenen tief unter ``tmp_path``
    gezeigt - so laeuft der ECHTE Rumpf, nicht ein Nachbau. Uebernommen aus
    ``test_config_full.py:964``.
    """
    config_dir = tmp_path / "config"
    containers_dir = config_dir / "containers"
    containers_dir.mkdir(parents=True)
    (config_dir / "channels").mkdir()
    (config_dir / "config.json").write_text(json.dumps({"language": "de"}), encoding="utf-8")
    # Faltungs-Marke: verhindert, dass der einmalige Umbau mitten im Test
    # Dateien neu schreibt.
    (config_dir / LEGACY_FOLD_MARKER).write_text("{}", encoding="utf-8")

    # Positivkontrolle: Diese Datei MUSS auf beiden Wegen auftauchen. Tut sie es
    # nicht, ist die Vorrichtung kaputt und nicht der Code.
    (containers_dir / f"{MIT_SCHLUESSEL}.json").write_text(json.dumps({
        "container_name": MIT_SCHLUESSEL, "active": True, "order": 1,
    }), encoding="utf-8")
    # Der strittige Fall: kein 'active'-Schluessel.
    (containers_dir / f"{OHNE_SCHLUESSEL}.json").write_text(json.dumps({
        "container_name": OHNE_SCHLUESSEL, "order": 2,
    }), encoding="utf-8")

    dienst = get_config_service()
    gesicherter_zustand = dict(dienst.__dict__)

    dienst.config_dir = config_dir
    dienst.channels_dir = config_dir / "channels"
    dienst.containers_dir = containers_dir
    dienst.main_config_file = config_dir / "config.json"
    dienst.auth_config_file = config_dir / "auth.json"
    dienst.heartbeat_config_file = config_dir / "heartbeat.json"
    dienst.web_ui_config_file = config_dir / "web_ui.json"
    dienst.docker_settings_file = config_dir / "docker_settings.json"
    dienst.bot_config_file = config_dir / "bot_config.json"
    dienst.docker_config_file = config_dir / "docker_config.json"
    dienst.web_config_file = config_dir / "web_config.json"
    dienst.channels_config_file = config_dir / "channels_config.json"
    dienst._loader_service = ConfigLoaderService(
        dienst.config_dir, dienst.channels_dir, dienst.containers_dir,
        dienst.main_config_file, dienst.auth_config_file, dienst.heartbeat_config_file,
        dienst.web_ui_config_file, dienst.docker_settings_file, dienst.bot_config_file,
        dienst.docker_config_file, dienst.web_config_file, dienst.channels_config_file,
        dienst._load_json_file, dienst._validation_service,
    )
    dienst._cache_service.invalidate_cache()
    dienst._cache_service.clear_token_cache()

    # ServerConfigService auf dasselbe tmp_path zeigen lassen.
    schein_verzeichnis = tmp_path / "services" / "config"
    schein_verzeichnis.mkdir(parents=True, exist_ok=True)
    schein_datei = schein_verzeichnis / "server_config_service.py"
    schein_datei.write_text("# Platzhalter fuer den Test\n", encoding="utf-8")
    monkeypatch.setattr(scs_mod, "__file__", str(schein_datei))

    try:
        yield type("Leser", (), {
            "config_dir": config_dir,
            "containers_dir": containers_dir,
            "dienst": dienst,
        })
    finally:
        dienst._cache_service.invalidate_cache()
        dienst.__dict__.clear()
        dienst.__dict__.update(gesicherter_zustand)


def _ueber_den_lader(dienst) -> set:
    """Namen aus config['servers'] - der Weg mit Vorgabe False."""
    konfiguration = dienst.get_config(force_reload=True)
    return {s.get("container_name") or s.get("docker_name")
            for s in konfiguration.get("servers", [])}


def _ueber_den_serverdienst() -> set:
    """Namen aus get_all_servers() - der Weg mit Vorgabe True."""
    return {s.get("docker_name") for s in ServerConfigService().get_all_servers()}


def test_beide_leser_sehen_dasselbe_verzeichnis(beide_leser):
    """Positivkontrolle gegen ein stumpfes Werkzeug.

    Zeigt einer der beiden Leser woanders hin, ist der Test unten ohne Aussage:
    Dann faende er einen Unterschied, der nur von zwei verschiedenen
    Verzeichnissen kommt. Genau so ist mir in diesem Programm schon ein Test
    gegen die echte Konfiguration gelaufen, statt gegen das Wegwerf-Verzeichnis.
    """
    assert beide_leser.dienst._loader_service.containers_dir == beide_leser.containers_dir

    ueber_lader = _ueber_den_lader(beide_leser.dienst)
    ueber_dienst = _ueber_den_serverdienst()

    assert MIT_SCHLUESSEL in ueber_lader, (
        f"Der Lader sieht die Positivkontrolle nicht: {sorted(ueber_lader)}. "
        "Dann zeigt er nicht auf das Wegwerf-Verzeichnis."
    )
    assert MIT_SCHLUESSEL in ueber_dienst, (
        f"Der ServerConfigService sieht die Positivkontrolle nicht: "
        f"{sorted(ueber_dienst)}. Vermutlich greift das Umbiegen von __file__ nicht."
    )


def test_container_ohne_active_verschwindet_nicht_auf_einem_weg(beide_leser):
    """DER BEFUND: dieselbe Datei, zwei Antworten.

    Nicht geprueft wird, WELCHE Vorgabe gilt - das ist die Entscheidung des
    Betreibers. Geprueft wird, dass beide Wege dieselbe Antwort geben. Ein
    Container, der halb da ist, ist in jeder Lesart ein Fehler.
    """
    ueber_lader = _ueber_den_lader(beide_leser.dienst)
    ueber_dienst = _ueber_den_serverdienst()

    nur_im_dienst = ueber_dienst - ueber_lader
    nur_im_lader = ueber_lader - ueber_dienst

    assert not (nur_im_dienst or nur_im_lader), (
        "Dieselben Dateien unter config/containers/ ergeben zwei verschiedene "
        "Containerlisten.\n"
        f"  nur ueber get_all_servers():   {sorted(nur_im_dienst)}\n"
        f"  nur ueber config['servers']:   {sorted(nur_im_lader)}\n"
        "Ursache: server_config_service.py:90 nimmt bei fehlendem 'active' True "
        "an, config_loader_service.py:274 nimmt False an. Der Container ist "
        "damit fuer die einen Aufrufer da und fuer die anderen weg - gemeldet "
        "nur durch eine logger.debug-Zeile, die im Normalbetrieb (INFO) nirgends "
        "erscheint."
    )
