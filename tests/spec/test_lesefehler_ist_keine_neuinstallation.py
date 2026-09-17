# -*- coding: utf-8 -*-
"""Ein Lesefehler an der Konfiguration darf nicht wie eine Neuinstallation aussehen.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND (Stufe 4, Punkt 5 - Durchsicht mit einem zweiten Modell, Abschnitt 13
``services/config/``). Das Zweitmodell meldete "verschluckter PermissionError
oeffnet die Erstanmeldung". Die Kette stimmt, aber nicht so, wie sie gemeldet
wurde - und die Unterschiede sind der halbe Befund.

DIE KETTE, Glied fuer Glied am Code belegt:

1. ``services/config/config_service.py:714-717`` - ``_load_json_file`` faengt
   ``(IOError, OSError, PermissionError)`` und gibt ``default.copy()`` zurueck.
   Es **verschluckt den Fehler nicht**, es protokolliert ihn mit
   ``exc_info=True``. Insoweit lag das Zweitmodell daneben. Nur: der
   Rueckgabewert ist derselbe, als waere die Datei leer. Dasselbe gilt bei
   ``json.JSONDecodeError`` (:710-713) - eine abgeschnittene config.json wirkt
   fuer die Anmeldung wie eine unlesbare.
2. ``config_loader_service.py:119`` - die Vorgabe fuer ``web_config.json``
   enthaelt ``'web_ui_password_hash': None``.
3. ``config_loader_service.py:331`` (``_overlay_main_config``, echter modularer
   Weg) bzw. ``:133-141`` (virtueller Weg) - beide setzen bei nicht lesbarer
   Datei die Vorgabe ein. Der Hash ist danach ``None``.
4. ``app/auth.py:176-183`` - ``if stored_hash is None`` oeffnet die
   Erstanmeldung mit ``admin`` / ``setup``.

WAS DER BEFUND NICHT IST: "admin/setup ist eine Hintertuer". Dieser Zweig ist
gewollt, dokumentiert und getestet -
``tests/unit/security/test_credential_cache.py:143`` sichert ihn ausdruecklich
zu. Ihn zu entfernen waere das Zerstoeren eines zugesicherten Verhaltens.

WAS DER BEFUND IST: Ein Lesefehler ist nicht von einer frischen Installation zu
unterscheiden. Ein Rechteproblem an ``config/`` oeffnet damit die 70 Routen
hinter ``@auth.login_required`` (``app/auth.py:27``) mit einem bekannten
Standardzugang - unbemerkt, weil die Anmeldung ja funktioniert.

DASS DIE GEFAHR BEKANNT WAR, steht im Code selbst. ``config_service.py:385-386``
begruendet den Schutz kritischer Felder beim SPEICHERN woertlich damit:
"losing it drops the panel back into first-run setup mode, where admin/setup is
accepted on every route (app/auth.py)". Der Schreibweg ist gegen genau diesen
Fall verteidigt. Der Leseweg ist es nicht. Der Befund lautet also nicht "das hat
niemand gesehen", sondern "das wurde auf einer Seite verteidigt und auf der
anderen offengelassen".

Dass der Fall alltaeglich ist, steht in den Projektregeln: "immer ``docker exec
-u ddc``" existiert, weil root-eigene Dateien die Anwendung schon einmal
gebrochen haben. Ich behaupte NICHT, dass es passiert ist - nur, dass dies der
Weg waere.

DREI EIGENE FEHLER AUF DEM WEG HIERHER. Sie stehen hier, weil sie die Bauart
dieses Tests erklaeren - jeder einzelne haette einen wertlosen Test in den
Commit getragen:

*Erstens* pruefte die erste Fassung der Korrektur, ob eine Konfigurationsdatei
auf der Platte LIEGT. Dafuer rief sie ``get_config_service()`` - und dessen
Konstruktor legt ueber ``ensure_modular_structure`` (:242) und
``_fold_legacy_settings_once`` (:248) selbst Dateien an. Gemessen, nicht
vermutet: In einem leer gestarteten Testverzeichnis lagen danach
``config.json``, ``docker_config.json``, ``servers_config.json`` und ein
Sicherungsordner mit dem Zeitstempel desselben Laufs. **Die Pruefung erzeugte
die Bedingung, die sie pruefte.** Gefunden hat das der vorhandene Test
``test_first_time_setup_still_works_without_a_hash``, der dabei rot wurde -
haette ich ihn "passend gemacht", waere der Fehler in den Commit gewandert.

*Zweitens* war "liegt eine Datei da" auch sachlich die falsche Frage. Die
richtige Frage ist, ob beim LESEN ein Fehler auftrat; bei einer Neuinstallation
tritt keiner auf.

*Drittens* bog die zweite Fassung dieser Vorrichtung nur die PFAD-ATTRIBUTE des
Dienstes um. ``_loader_service`` war aber im Konstruktor mit den alten Pfaden
gebaut worden und las unbeirrt weiter am echten ``config/`` - die Tests liefen
gegen die Produktionskonfiguration statt gegen das Wegwerf-Verzeichnis. Der
Waechter dagegen war selbst stumpf: Er prueft ``dienst.config_dir``, also den
Wert, den die Vorrichtung gerade selbst gesetzt hatte. Erwartung und Behauptung
aus derselben Quelle - derselbe Schnitt wie beim Spiegeltest in
``test_app_factory_verdrahtung.py``. Deshalb prueft der Waechter jetzt den Pfad,
den **der Lader** benutzt.

WIE HIER GEPRUEFT WIRD: Die Datei wird **wirklich** unlesbar gemacht bzw. echt
beschaedigt, nicht per Monkeypatch nachgestellt; ``load_config`` wird bewusst
NICHT umgebogen. Und vor jedem Schaden wird belegt, dass der Hash vorher
GELADEN WURDE - sonst waere "Hash ist None" schon der Ausgangszustand, und der
Test bekaeme das richtige Ergebnis aus dem falschen Grund.

GEGENPROBE (durchgefuehrt 2026-09-17) - drei Messungen, weil drei verschiedene
Dinge zu belegen waren:

*1. Die beiden Befundtests waren VOR der Korrektur rot* - und zwar aus dem
richtigen Grund, belegt durch echte Rueckverfolgungen aus der Kette selbst, nicht
durch eine passende Fehlermeldung::

    unlesbar -> config_service.py:715  PermissionError [Errno 13], Traceback aus
                open() in Zeile 703, danach auth.py:179 "FIRST TIME SETUP:
                Setup mode activated with temporary credentials"
    kaputt   -> config_service.py:711  JSONDecodeError ("Expecting ',' delimiter"),
                Traceback aus json.load in Zeile 704, danach dieselbe Zeile 179

Vorher 3 gruen / 2 rot, nachher 5 gruen.

*2. Vier vorab notierte Wege, auf denen dieses Rot wertlos gewesen waere*, sind
alle NICHT eingetreten: der Lader-Waechter hielt, der Hash war vor dem Schaden
nachweislich geladen ("Real modular config loaded: 1 servers"),
``pytest.raises(PermissionError)`` feuerte, und der Schaden pflanzte sich bis zum
fehlenden Hash fort. Die Liste stand VOR dem Lauf fest; sonst haette ich mir
hinterher ausgesucht, was als Beleg zaehlt.

*3. Der Waechter ``test_echte_erstinstallation_funktioniert_weiter`` war von
Anfang an gruen* - also bis zum Beweis des Gegenteils ein Test, der nicht
fehlschlagen kann. Er ist derjenige, der das GEWOLLTE Verhalten schuetzt; waere
er blind, liesse sich die Erstanmeldung zerstoeren, ohne dass etwas rot wird.
Mutation: ``get_config`` meldet immer einen Lesefehler::

    mit Mutation -> 1 failed, 4 passed

Rot wurde genau er, an der richtigen Zeile (:279, ``assert ... == "admin"``,
``assert None == 'admin'``), mit dem eingeschleusten Grund im Protokoll
("could not be read (MUTATION)"). Die beiden Befundtests blieben gruen - sie
wollen die Tuer ohnehin geschlossen. Mutation zurueckgenommen, danach wieder
5 gruen.
"""

import json
import os
import stat

import pytest
from flask import Flask
from werkzeug.security import generate_password_hash

from app import auth as auth_module
from services.config.config_cache_service import ConfigCacheService
from services.config.config_loader_service import LEGACY_FOLD_MARKER, ConfigLoaderService
from services.config.config_migration_service import ConfigMigrationService
from services.config.config_service import get_config_service

PASSWORT = "correct-horse-battery"


def _hash(passwort):
    # Billige Ableitung: Dieser Test interessiert sich fuer den Weg des Wertes,
    # nicht fuer die Kosten der Ableitung. Die Produktionszahl (600.000 Runden)
    # ist in tests/security/test_security_sast.py festgenagelt.
    return generate_password_hash(passwort, method="pbkdf2:sha256:1")


@pytest.fixture
def auth_umgebung(tmp_path):
    """Flask-Kontext + ConfigService-Singleton auf ein Wegwerf-Verzeichnis.

    Muster uebernommen aus ``tests/unit/audit_2026_09/test_pkg_c2_config.py:54``
    - EINSCHLIESSLICH des Neubaus der Teildienste (:77-85). Ohne den liest
    ``_loader_service`` weiter an den Pfaden, mit denen er im Konstruktor gebaut
    wurde; genau daran ist die zweite Fassung dieses Tests gescheitert.

    ``containers/`` und ``channels/`` werden angelegt, damit
    ``has_real_modular_structure()`` greift: In diesem Aufbau ist ``config.json``
    die massgebliche Datei, und nur dann belegt der Test ueberhaupt etwas ueber
    sie.

    Die Faltungs-Marke wird geschrieben, damit der einmalige Umbau
    (``_fold_legacy_settings_once``) nicht mitten im Test Dateien neu schreibt.
    """
    app = Flask(__name__)
    # Der Erstanmeldungs-Zweig schreibt session['setup_mode']; ohne Schluessel
    # weigert sich Flask ("The session is unavailable because no secret key was
    # set"). Nur die Testanwendung braucht ihn.
    app.secret_key = "test-secret-lesefehler"

    dienst = get_config_service()
    gesicherter_zustand = dict(dienst.__dict__)

    config_dir = tmp_path / "config"
    (config_dir / "containers").mkdir(parents=True)
    (config_dir / "channels").mkdir()
    (config_dir / "containers" / "web.json").write_text(
        json.dumps({"docker_name": "web", "active": True}), encoding="utf-8"
    )
    (config_dir / LEGACY_FOLD_MARKER).write_text("{}", encoding="utf-8")

    dienst.config_dir = config_dir
    dienst.channels_dir = config_dir / "channels"
    dienst.containers_dir = config_dir / "containers"
    dienst.main_config_file = config_dir / "config.json"
    dienst.auth_config_file = config_dir / "auth.json"
    dienst.heartbeat_config_file = config_dir / "heartbeat.json"
    dienst.web_ui_config_file = config_dir / "web_ui.json"
    dienst.docker_settings_file = config_dir / "docker_settings.json"
    dienst.bot_config_file = config_dir / "bot_config.json"
    dienst.docker_config_file = config_dir / "docker_config.json"
    dienst.web_config_file = config_dir / "web_config.json"
    dienst.channels_config_file = config_dir / "channels_config.json"
    dienst._migration_service = ConfigMigrationService(
        config_dir, dienst.channels_dir, dienst.containers_dir
    )
    dienst._cache_service = ConfigCacheService()
    dienst._loader_service = ConfigLoaderService(
        config_dir, dienst.channels_dir, dienst.containers_dir,
        dienst.main_config_file, dienst.auth_config_file, dienst.heartbeat_config_file,
        dienst.web_ui_config_file, dienst.docker_settings_file, dienst.bot_config_file,
        dienst.docker_config_file, dienst.web_config_file, dienst.channels_config_file,
        dienst._load_json_file, dienst._validation_service,
    )

    auth_module.clear_credential_cache()
    try:
        with app.app_context():
            yield type("Umgebung", (), {
                "app": app,
                "config_dir": config_dir,
                "dienst": dienst,
            })
    finally:
        auth_module.clear_credential_cache()
        # Rechte zuruecksetzen, sonst kann pytest tmp_path nicht aufraeumen.
        for pfad in config_dir.rglob("*"):
            try:
                pfad.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            except OSError:
                pass
        dienst.__dict__.clear()
        dienst.__dict__.update(gesicherter_zustand)


def test_der_test_laeuft_nicht_als_root():
    """Sicherung gegen ein stumpfes Werkzeug.

    root ignoriert Dateirechte. Liefe dieser Test als root, waere die "unlesbare"
    Datei munter lesbar, der Befundtest unten wuerde gruen - und wuerde nichts
    belegen. ``scripts/ddc_test.sh:81`` startet den Container mit ``-u ddc``;
    dieser Test stellt sicher, dass das so bleibt.
    """
    assert hasattr(os, "geteuid"), "Kein POSIX-System - der Rechtetest traegt hier nicht."
    assert os.geteuid() != 0, (
        "Dieser Test laeuft als root. root ignoriert Dateirechte, die 'unlesbare' "
        "Datei waere lesbar und der Befundtest wuerde gruen werden, ohne etwas zu "
        "belegen. Der Testlaeufer muss mit -u ddc starten."
    )


def test_der_lader_zeigt_wirklich_auf_das_wegwerfverzeichnis(auth_umgebung):
    """Sicherung gegen ein stumpfes Werkzeug - und zwar an der richtigen Stelle.

    Die Vorgaengerfassung prueste ``dienst.config_dir``: den Wert, den die
    Vorrichtung selbst gesetzt hatte. Der ist immer richtig und belegt nichts.
    Gelesen wird ueber ``_loader_service``, und dessen Pfade stammen aus SEINEM
    Konstruktor. Nur sie zu pruefen schliesst aus, dass die Tests unten gegen die
    echte Konfiguration laufen.
    """
    lader = auth_umgebung.dienst._loader_service
    assert lader.config_dir == auth_umgebung.config_dir, (
        "Der LADER zeigt nicht auf das Wegwerf-Verzeichnis - die Tests unten "
        "wuerden gegen die echte Konfiguration laufen."
    )
    assert lader.main_config_file == auth_umgebung.config_dir / "config.json"
    assert lader.has_real_modular_structure(), (
        "Ohne echten modularen Aufbau ist config.json nicht die massgebliche "
        "Datei - dann belegt ein Schaden an ihr nichts."
    )


def test_echte_erstinstallation_funktioniert_weiter(auth_umgebung):
    """Der gewollte Zweig. Muss vor UND nach der Korrektur gruen sein.

    Keine config.json, kein Lesefehler: Ein fehlender Hash ist dann genau das,
    wonach er aussieht - eine frische Installation. ``admin`` / ``setup`` ist der
    vorgesehene Weg, zugesichert in
    ``tests/unit/security/test_credential_cache.py:143``. Eine Korrektur, die
    diesen Test rot macht, hat das Falsche repariert.
    """
    assert not auth_umgebung.dienst.main_config_file.exists(), (
        "Der Ausgangszustand stimmt nicht - hier darf noch keine config.json liegen."
    )
    konfiguration = auth_umgebung.dienst.get_config(force_reload=True)
    assert konfiguration.get('web_ui_password_hash') is None

    with auth_umgebung.app.test_request_context():
        assert auth_module.verify_password("admin", "setup") == "admin", (
            "Die Erstanmeldung ohne Passwort und ohne Lesefehler ist gewolltes, "
            "zugesichertes Verhalten und darf nicht mitkorrigiert werden."
        )


def _hash_einpflanzen_und_belegen(umgebung):
    """Hash setzen UND belegen, dass er geladen wird.

    Ohne diesen Beleg waere "Hash ist None" schon der Ausgangszustand: Die Tests
    unten bekaemen das richtige Ergebnis, ohne dass der Schaden an der Datei
    irgendetwas damit zu tun haette.
    """
    hash_wert = _hash(PASSWORT)
    umgebung.dienst.main_config_file.write_text(
        json.dumps({"web_ui_user": "admin", "web_ui_password_hash": hash_wert}),
        encoding="utf-8",
    )
    geladen = umgebung.dienst.get_config(force_reload=True)
    assert geladen.get('web_ui_password_hash') == hash_wert, (
        "Der Hash aus config.json wird gar nicht geladen - dann belegt ein "
        "Schaden an dieser Datei nichts ueber die Anmeldung."
    )
    return hash_wert


def test_unlesbare_konfiguration_oeffnet_nicht_die_erstanmeldung(auth_umgebung):
    """DER BEFUND: Die Konfiguration ist nicht lesbar - das ist keine Neuinstallation.

    Die Datei wird echt unlesbar gemacht (``chmod 000``), nicht nachgestellt.
    Danach laeuft die Kette aus dem Modul-Docstring ab: ``_load_json_file``
    liefert die Vorgabe, der Hash ist ``None``, und ``verify_password`` haelt das
    fuer eine frische Anlage.
    """
    _hash_einpflanzen_und_belegen(auth_umgebung)

    auth_umgebung.dienst.main_config_file.chmod(0)
    with pytest.raises(PermissionError):
        auth_umgebung.dienst.main_config_file.read_text(encoding="utf-8")

    konfiguration = auth_umgebung.dienst.get_config(force_reload=True)
    assert konfiguration.get('web_ui_password_hash') is None, (
        "Erwartet war ein verschwundener Hash - sonst prueft der Test unten "
        "nicht den Befund."
    )

    with auth_umgebung.app.test_request_context():
        ergebnis = auth_module.verify_password("admin", "setup")

    assert ergebnis is None, (
        "config.json war NICHT LESBAR, der Hash kam deshalb als None zurueck - "
        "das ist ein Lesefehler, keine Neuinstallation. admin/setup darf hier "
        "nicht durchkommen: Dahinter haengen 70 Routen mit @auth.login_required, "
        "und niemand wuerde es bemerken, weil die Anmeldung ja funktioniert."
    )


def test_kaputte_konfiguration_oeffnet_nicht_die_erstanmeldung(auth_umgebung):
    """Derselbe Schaden aus der anderen Richtung: lesbar, aber kein gueltiges JSON.

    ``_load_json_file:710-713`` faengt ``JSONDecodeError`` und liefert ebenfalls
    die Vorgabe. Fuer die Anmeldung ist das Ergebnis identisch. Eine Korrektur,
    die nur auf Rechtefehler sieht, liesse diesen Weg offen - eine halbe
    Korrektur, die vollstaendig aussieht.
    """
    _hash_einpflanzen_und_belegen(auth_umgebung)

    auth_umgebung.dienst.main_config_file.write_text(
        '{"web_ui_password_hash": "abc"', encoding="utf-8"
    )

    konfiguration = auth_umgebung.dienst.get_config(force_reload=True)
    assert konfiguration.get('web_ui_password_hash') is None, (
        "Erwartet war ein verschwundener Hash - sonst prueft der Test unten "
        "nicht den Befund."
    )

    with auth_umgebung.app.test_request_context():
        ergebnis = auth_module.verify_password("admin", "setup")

    assert ergebnis is None, (
        "config.json ist abgeschnitten und damit nicht auswertbar. Der fehlende "
        "Hash ist die Folge eines Lesefehlers, keine Neuinstallation - "
        "admin/setup darf nicht durchkommen."
    )
