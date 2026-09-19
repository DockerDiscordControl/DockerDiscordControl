# -*- coding: utf-8 -*-
"""Die Token-Anzeige darf eine Klartext-Kopie auf der Platte nicht verschweigen.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers. Der Sache nach gehoert dieser Test zu Z9.

DER BEFUND (Stufe 4, Punkt 5 - Zweitdurchsicht, Abschnitt 37), vom Betreiber
ausdruecklich zur Korrektur freigegeben.

``utils/token_security.py:153-157`` kehrt sofort zurueck, sobald
``DISCORD_BOT_TOKEN`` gesetzt ist. ``token_exists`` und ``is_encrypted`` bleiben
auf ihren Vorgaben ``False`` - die Datei wird nie angesehen. Folge:

* ``services/web/security_service.py:265`` vergibt 40/40 und "Excellent"
* ``app/templates/_token_security_modal.html:74-79`` zeigt gruenes "Excellent"
* ``auto_encrypt_token_on_startup`` (verdrahtet in ``app/bootstrap/runtime.py:194``)
  verlangt ``token_exists`` und laeuft deshalb nie an

und das alles, waehrend in ``bot_config.json`` ein Klartext-Token liegen kann.

DAS SYSTEM SETZT "eine sichere Quelle wird benutzt" MIT "es existiert keine
unsichere Kopie" GLEICH. Dass die Umgebungsvariable gesetzt ist, sagt nichts
darueber, was in der Datei steht.

WAS DIESER TEST NICHT VERLANGT - und das ist die Entscheidung des Betreibers,
nicht meine: Die Punktzahl soll NICHT sinken. Die Umgebungsvariable ist richtig,
sie bleibt 40/40 und "Excellent". Verlangt wird nur, dass die Anzeige die
Klartext-Kopie zusaetzlich MELDET, statt sie zu verschweigen. Deshalb prueft
``test_die_gute_nachricht_bleibt`` ausdruecklich, dass der gute Teil erhalten
bleibt - eine Korrektur, die ihn mitreisst, hat das Falsche repariert.

DASS DIE WARNUNG SICHTBAR WIRD, ist geprueft und nicht angenommen:
``_token_security_modal.html:181-186`` rendert die ``recommendations``-Liste
unter eigener Ueberschrift. Ohne diese Pruefung haette der Test eine Warnung
belegt, die niemand je zu sehen bekommt.

WIE HIER UMGELENKT WIRD: ``token_security.py:162`` bildet
``Path(__file__).parents[1] / "config"`` INNERHALB der Funktion. Es genuegt
also, ``__file__`` des Moduls auf eine Scheindatei zu zeigen - dasselbe
Verfahren wie in ``tests/unit/services/configuration/test_config_full.py:964``.
Die vorhandene Vorrichtung ``fake_config_dir`` in
``tests/unit/utils/test_crypto_cache.py:59`` ersetzt stattdessen das
``Path``-Symbol durch eine Stub-Klasse; sie liegt in einer anderen Testgruppe
und laesst sich nicht herueberimportieren.

GEGENPROBE (durchgefuehrt 2026-09-18) - drei Messungen, weil vier Tests zu
belegen waren. Genannt werden TESTNAMEN statt Zeilennummern: Zweimal hat in
diesem Programm eine notierte Zeilenzahl denselben Schreibvorgang nicht
ueberlebt, der sie notierte.

*1. Zwei Tests waren VOR der Korrektur rot*, beide aus derselben Ursache::

    2 passed, 2 failed
    test_umgebungsvariable_verschweigt_die_klartextkopie_nicht
        -> assert False is True   (token_exists)
    test_verschluesselter_token_loest_keine_warnung_aus
        -> assert False is True   (is_encrypted)

Der frueh zurueckkehrende Code kann die Datei nicht ansehen - weder um eine
Klartext-Kopie zu finden noch um eine verschluesselte zu erkennen. Nach der
Korrektur: 4 gruen.

*2. Der Vorrichtungs-Waechter war von Anfang an gruen* und damit unbewiesen. Er
sichert, dass ueberhaupt im Wegwerf-Verzeichnis geprueft wird; griffe das
Umbiegen von ``__file__`` eines Tages nicht mehr, liefe der Befundtest gegen die
ECHTE Konfiguration. Mutation: die Pfadherleitung ignoriert ``__file__``::

    1 passed, 3 failed

Rot wurde er an SEINER eigenen ``token_exists``-Behauptung, mit seiner eigenen
Meldung. ``test_die_gute_nachricht_bleibt`` blieb gruen - die Mutation reicht
nicht in den Umgebungsvariablen-Zweig.

*3. ``test_die_gute_nachricht_bleibt`` war ebenfalls durchgehend gruen.* Er
schuetzt die ausdrueckliche Entscheidung des Betreibers: Die Umgebungsvariable
behaelt ihre 40/40, die Warnung kommt NEBEN das Gruen. Koennte er nicht
fehlschlagen, liesse sich die Wertung eines Tages zerstoeren, ohne dass etwas
rot wird. Mutation: die Flagge wird nicht gesetzt, die Empfehlungszeile bleibt
absichtlich stehen::

    2 passed, 2 failed

Rot wurde er an SEINER eigenen ``environment_token_used``-Behauptung. Der
Befundtest fiel als angekuendigte Mitwirkung (seine Warnung haengt an der
Flagge); Waechter und Abgrenzungstest blieben gruen.

*Vier Wege, auf denen diese Roten wertlos gewesen waeren*, standen vor jedem Lauf
fest und traten nie ein: der jeweilige Test bleibt gruen (waere hohl); er faellt
an einer anderen Behauptung als dem geprueften Zusammenhang; die Mutation macht
mehr rot als behauptet; Sammel- oder Importfehler.

EINE VORHERSAGE, DIE NICHT EINTRAT und die hierher gehoert: Ich hatte zwei
absichtlich geschriebene Tests als Opfer angekuendigt -
``test_crypto_cache.py:272-274`` ("should remain False defaults") und
``test_utils_completion.py:530-534``. Gemessen blieben BEIDE gruen: Ihre
Vorrichtungen legen ein leeres Konfigurationsverzeichnis an, dort aendert der
entfallene Ruecksprung nichts. Die Ankuendigung war falsch; gemerkt habe ich es
erst beim Lauf.

BETROFFENE GRUPPEN, alle gruen gemessen: spec 88, unit/utils 248 (+1
uebersprungen), security 16 (+1), services/web 358, audit_2026_09 564,
blueprints 276, extended 731.
"""

import json

import pytest

from utils.token_security import TokenSecurityManager

KLARTEXT_TOKEN = "MTIzNDU2Nzg5MDEyMzQ1Njc4.GaBcDe.ThisLooksLikeARealToken1234"
VERSCHLUESSELT = "gAAAAABmZ2VyeXRoaW5nSXNFbmNyeXB0ZWRIZXJlAAAA"


@pytest.fixture
def anlage(tmp_path, monkeypatch):
    """TokenSecurityManager auf ein Wegwerf-Verzeichnis zeigen lassen.

    Ueber ``DDC_CONFIG_DIR``. Bis 2026-09-19 wurde hier ``__file__`` des Moduls
    umgebogen, weil der Dienst das Verzeichnis selbst herleitete; seitdem liest
    er utils.config_paths.get_config_dir() (test_konfigverzeichnis_token.py).
    Als der Kniff nicht mehr griff, blieb test_die_gute_nachricht_bleibt
    GRUEN, ohne etwas zu pruefen - die Umgebungsvariable allein erfuellt ihn.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setenv("DDC_CONFIG_DIR", str(config_dir))

    def bot_config_schreiben(token):
        (config_dir / "bot_config.json").write_text(
            json.dumps({"bot_token": token}), encoding="utf-8")

    (config_dir / "web_config.json").write_text(
        json.dumps({"web_ui_password_hash": "pbkdf2:sha256:1$abc$def"}), encoding="utf-8")

    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)

    return type("Anlage", (), {
        "config_dir": config_dir,
        "bot_config_schreiben": staticmethod(bot_config_schreiben),
        "monkeypatch": monkeypatch,
    })


def test_die_vorrichtung_zeigt_auf_das_wegwerfverzeichnis(anlage):
    """Sicherung gegen ein stumpfes Werkzeug.

    Greift das Umbiegen von ``__file__`` nicht, sieht der Dienst in das ECHTE
    ``config/`` - dann waeren die Tests unten ohne Aussage, und im schlimmsten
    Fall haetten sie die Produktivkonfiguration gelesen. Genau diese Bauart hat
    in diesem Programm schon zweimal einen Melder wertlos gemacht.
    """
    anlage.bot_config_schreiben(KLARTEXT_TOKEN)

    status = TokenSecurityManager(config_service=object()).verify_token_encryption_status()

    assert status["token_exists"] is True, (
        "Der Dienst sieht die Wegwerf-bot_config.json nicht - das Umbiegen von "
        "__file__ greift nicht, und die Tests unten belegen nichts."
    )
    assert status["is_encrypted"] is False, (
        "Ein Klartext-Token darf nicht als verschluesselt gelten."
    )


def test_die_gute_nachricht_bleibt(anlage):
    """Der gewollte Teil. Muss vor UND nach der Korrektur gruen sein.

    Die Entscheidung des Betreibers lautet ausdruecklich: Die Punktzahl soll
    NICHT sinken. Ist die Umgebungsvariable gesetzt, bleibt sie gemeldet - davon
    haengt bei ``security_service.py:265`` die volle Wertung ab. Eine Korrektur,
    die diesen Test rot macht, hat das Falsche repariert.
    """
    anlage.monkeypatch.setenv("DISCORD_BOT_TOKEN", "env-token-xyz")
    anlage.bot_config_schreiben(KLARTEXT_TOKEN)

    status = TokenSecurityManager(config_service=object()).verify_token_encryption_status()

    assert status["environment_token_used"] is True, (
        "Die Umgebungsvariable muss weiterhin als benutzt gemeldet werden - "
        "sonst faellt die Wertung in security_service.py:265 von 40 auf 0."
    )
    assert any("environment variable" in r for r in status["recommendations"]), (
        "Die bestaetigende Empfehlung zur Umgebungsvariable darf nicht wegfallen."
    )


def test_umgebungsvariable_verschweigt_die_klartextkopie_nicht(anlage):
    """DER BEFUND: gesetzte Umgebungsvariable UND Klartext-Token in der Datei.

    Beides zugleich ist der Fall, den die Anzeige heute nicht sehen kann: Sie
    kehrt zurueck, bevor sie die Datei ansieht.
    """
    anlage.monkeypatch.setenv("DISCORD_BOT_TOKEN", "env-token-xyz")
    anlage.bot_config_schreiben(KLARTEXT_TOKEN)

    status = TokenSecurityManager(config_service=object()).verify_token_encryption_status()

    assert status["token_exists"] is True, (
        "Die Anzeige meldet, es gebe keinen Token in der Datei - obwohl dort ein "
        "KLARTEXT-Token liegt. Sie kehrt bei token_security.py:153-157 zurueck, "
        "bevor sie nachsieht. Folge: security_service.py:265 vergibt 40/40 und "
        "'Excellent', das Panel zeigt Gruen, und auto_encrypt_token_on_startup "
        "laeuft nie an."
    )
    assert status["is_encrypted"] is False, (
        "Der Token in der Datei ist Klartext und darf nicht als verschluesselt gelten."
    )
    assert any("bot_config" in r.lower() or "plaintext" in r.lower() or "klartext" in r.lower()
               for r in status["recommendations"]), (
        "Es gibt keine Empfehlung, die auf die Klartext-Kopie hinweist. Die "
        "Oberflaeche rendert die recommendations-Liste "
        "(_token_security_modal.html:181-186) - eine Warnung dort wird also "
        "gesehen. Ohne sie bleibt die gruene Anzeige das Einzige, was der "
        "Betreiber zu sehen bekommt."
    )


def test_verschluesselter_token_loest_keine_warnung_aus(anlage):
    """Abgrenzung: Nur eine KLARTEXT-Kopie ist der Befund.

    Liegt in der Datei ein verschluesselter Token, ist das der dokumentierte
    Normalfall und keine Warnung wert. Ohne diese Abgrenzung wuerde die neue
    Meldung bei jeder normalen Anlage erscheinen - und eine Warnung, die immer
    kommt, wird ignoriert.
    """
    anlage.monkeypatch.setenv("DISCORD_BOT_TOKEN", "env-token-xyz")
    anlage.bot_config_schreiben(VERSCHLUESSELT)

    status = TokenSecurityManager(config_service=object()).verify_token_encryption_status()

    assert status["is_encrypted"] is True
    assert not any("klartext" in r.lower() or "plaintext" in r.lower()
                   for r in status["recommendations"]), (
        "Ein verschluesselter Token darf keine Klartext-Warnung ausloesen."
    )
