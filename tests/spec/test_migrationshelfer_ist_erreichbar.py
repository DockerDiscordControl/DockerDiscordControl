# -*- coding: utf-8 -*-
"""Der Migrations-Helfer muss auf dem Weg funktionieren, den die Produktion nimmt.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND (Stufe 4, Punkt 5 - Zweitdurchsicht, Abschnitt 37), vom Betreiber
ausdruecklich zur Reparatur freigegeben.

``TokenSecurityManager.__init__`` setzt ``self.config_service`` (:51-59) - und
NUR das. ``migrate_to_environment_variable`` liest aber ``self.config_manager``.
Das Attribut existiert nirgends; der ``AttributeError`` wird bei :247 gefangen
und als ``error`` durchgereicht.

WAS DER BETREIBER DAVON SIEHT: Der Knopf im Token-Fenster ruft
``/api/migration-help`` (``_token_security_modal.html:272``), und weil
``result.success`` falsch ist, landet die Antwort im ``alert``-Zweig (:279).
Auf dem Bildschirm steht dann der rohe Python-Text
``'TokenSecurityManager' object has no attribute 'config_manager'``. Kein
vergrabener Logeintrag - ein Dialog.

Es ist GENAU EIN Bruch, nicht zwei: Ein Verdacht, die Oberflaeche pruefe
ausserdem das falsche Feld (``result.token`` gegen ``plaintext_token``), hat sich
nicht bestaetigt - ``security_service.py:174-175`` benennt sauber um.

WARUM DIE VORHANDENEN TESTS DAS NICHT FANGEN - und das ist der lehrreiche Teil:

* ``test_crypto_cache.py:332-340`` ruft die Methode auf und prueft, dass sie ein
  Fehler-Woerterbuch zurueckgibt. Der Kommentar dort sagt ausdruecklich
  "config_manager attribute is never set, so the AttributeError path is
  exercised". Der Defekt ist also **als erwartetes Verhalten festgeschrieben**.
* ``test_utils_completion.py:1125-1138`` setzt ``mgr.config_manager`` VON AUSSEN
  und prueft damit einen Erfolgspfad, den es produktiv nicht gibt. Ein
  Spiegeltest: Er kann fuer den echten Code nicht fehlschlagen.

Jemand hat den Defekt gesehen und Tests **darum herum** gebaut, statt ihn zu
beheben. Beide werden mit dieser Korrektur zu echten Tests - ein Wort je Zeile.

WIE HIER GEPRUEFT WIRD: ausschliesslich ueber das, was die Produktion liefert.
``TokenSecurityManager(config_service=...)`` - so und nur so entsteht der
Manager im Betrieb (``security_service.py:75,112,155,208``,
``token_security.py:259,288,292``). Kein Attribut wird von aussen nachgereicht;
genau das unterscheidet diesen Test vom Spiegeltest oben.

ABGRENZUNG: Was die Methode inhaltlich ausgibt (der entschluesselte Token ueber
HTTP) ist eine dokumentierte Entscheidung des Betreibers - siehe SPEC.md B5.
Dieser Test stellt sie nicht in Frage, er prueft nur, dass der Weg ueberhaupt
erreichbar ist.

GEGENPROBE (durchgefuehrt 2026-09-18) - zwei Messungen, weil drei Tests zu
belegen waren. Genannt werden TESTNAMEN statt Zeilennummern: Die Zeilen in
``test_utils_completion.py`` haben sich beim Aufraeumen um eins verschoben, eine
notierte Zahl waere schon jetzt falsch.

*1. Zwei Tests waren VOR der Korrektur rot*, beide an ihren eigenen
Behauptungen::

    1 passed, 2 failed
    test_migrationshelfer_liefert_den_token_auf_dem_produktionsweg
        -> assert False is True   (success)
    test_ohne_entschluesselten_token_bleibt_es_ein_misserfolg
        -> 'decrypt' in "'tokensecuritymanager' object has no attribute
           'config_manager'"

Der zweite Fehlertext ist der Befund selbst: Wo eine Entschluesselungsmeldung
stehen sollte, stand der rohe Attributfehler. Nach der Korrektur: 3 gruen.

*2. Der Waechter ``test_die_produktion_reicht_nur_config_service`` war von
Anfang an gruen* und damit unbewiesen. Er sichert zu, dass die Produktion
``config_service`` liefert und KEIN ``config_manager`` nachreicht - waere er
blind, koennte das alte Attribut zurueckkehren, ohne dass etwas anschlaegt.
Mutation: ``__init__`` setzt zusaetzlich ``config_manager``::

    1 failed, 2 passed

Rot wurde er an SEINER eigenen ``hasattr``-Behauptung; die beiden anderen
blieben gruen.

*Vier Wege, auf denen diese Roten wertlos gewesen waeren*, standen vor jedem Lauf
fest und traten nie ein: der Test bleibt gruen (waere hohl); er faellt an einer
anderen Behauptung als dem geprueften Zusammenhang; die Mutation macht mehr rot
als behauptet; Fehler statt Fehlschlag oder Sammelfehler.

EINE VORHERSAGE VON MIR TRAF NICHT ZU, und sie gehoert hierher: Ich hatte ZWEI
vorhandene Tests als Opfer der Korrektur angekuendigt. Gemessen brachen VIER -
``test_migrate_to_environment_variable_no_manager`` (test_crypto_cache.py) sowie
``..._success_with_decrypted_token``, ``..._no_decrypted_token`` und
``..._propagates_attr_error`` (test_utils_completion.py). Alle vier sprachen
``config_manager`` an; der vierte war mir bis zur Messung unbekannt. Fuer diese
Gruppe hatte ich bewusst KEINE Zahl vorhergesagt - das war die richtige
Entscheidung.

Alle vier wurden angepasst, nicht entfernt: Drei benutzen jetzt
``config_service`` statt ``config_manager`` (ein Wort je Stelle) und sind damit
vom Spiegeltest zum echten Test geworden; der vierte stellt den Zweig "kein
Konfigurationsdienst" ausdruecklich her, statt sich auf einen Defekt zu
verlassen. Danach: ``tests/unit/utils`` wieder 248 gruen (+1 uebersprungen) -
derselbe Stand wie vor der Korrektur, KEIN fuenfter Test gefallen.

BETROFFENE GRUPPEN, alle gruen gemessen: spec 91, unit/utils 248 (+1
uebersprungen), services/web 358.
"""

import pytest

from utils.token_security import TokenSecurityManager

ENTSCHLUESSELT = "ENTSCHLUESSELTER-TOKEN-4711"


class _KonfigurationsDienstAttrappe:
    """Verhaelt sich wie ConfigService, soweit die Methode ihn benutzt.

    Bewusst KEIN MagicMock: Ein MagicMock liefert auf jedes Attribut etwas
    zurueck - auch auf ``config_manager``. Damit waere nicht zu unterscheiden,
    ob der Code das richtige Attribut benutzt. Diese Attrappe hat genau das,
    was ConfigService auch hat.
    """

    def __init__(self, konfiguration):
        self._konfiguration = konfiguration
        self.gerufen = 0

    def get_config(self):
        self.gerufen += 1
        return self._konfiguration


def test_die_produktion_reicht_nur_config_service():
    """Sicherung gegen ein stumpfes Werkzeug.

    Gaebe es ``config_manager`` doch irgendwo, pruefte der Test unten etwas
    anderes als behauptet. Der Manager wird im Betrieb ausschliesslich als
    ``TokenSecurityManager()`` oder mit ``config_service=`` gebaut - ein
    ``config_manager`` wird nirgends nachgereicht.
    """
    manager = TokenSecurityManager(config_service=_KonfigurationsDienstAttrappe({}))

    assert hasattr(manager, "config_service"), (
        "Der Manager hat kein config_service - dann stimmt die Annahme dieses "
        "Tests ueber den Produktionsweg nicht."
    )
    assert not hasattr(manager, "config_manager"), (
        "Der Manager hat doch ein config_manager - dann ist der Befund ein "
        "anderer als beschrieben."
    )


def test_migrationshelfer_liefert_den_token_auf_dem_produktionsweg():
    """DER BEFUND: Auf dem Weg, den die Produktion nimmt, kommt nichts zurueck.

    Gebaut wird ausschliesslich mit ``config_service`` - so wie es
    security_service.py und die Modulfunktionen in token_security.py tun. Kein
    Attribut wird nachgereicht.
    """
    dienst = _KonfigurationsDienstAttrappe(
        {"bot_token_decrypted_for_usage": ENTSCHLUESSELT}
    )
    manager = TokenSecurityManager(config_service=dienst)

    ergebnis = manager.migrate_to_environment_variable()

    assert ergebnis["success"] is True, (
        "Der Migrations-Helfer meldet Misserfolg, obwohl der Konfigurationsdienst "
        "einen entschluesselten Token liefert. Die Methode liest "
        "self.config_manager, gesetzt wird aber nur self.config_service "
        "(token_security.py:51-59) - der AttributeError wird bei :247 gefangen "
        f"und als Fehlertext durchgereicht: {ergebnis.get('error')!r}. Der "
        "Betreiber sieht diesen rohen Python-Text als Dialog im Token-Fenster."
    )
    assert ergebnis["plaintext_token"] == ENTSCHLUESSELT
    assert any("DISCORD_BOT_TOKEN" in zeile for zeile in ergebnis["instructions"]), (
        "Die Anleitung muss den Namen der Umgebungsvariable nennen - sonst ist "
        "sie als Migrationshilfe wertlos."
    )
    assert dienst.gerufen == 1, (
        "get_config wurde nicht genau einmal gerufen - dann nimmt die Methode "
        "einen anderen Weg als angenommen."
    )


def test_ohne_entschluesselten_token_bleibt_es_ein_misserfolg():
    """Abgrenzung: Der Fehlerpfad muss erhalten bleiben.

    Liefert der Konfigurationsdienst keinen entschluesselten Token, ist
    Misserfolg richtig - mit einer Meldung, die auf das Entschluesseln zeigt und
    nicht auf ein fehlendes Attribut. Ohne diese Abgrenzung koennte eine
    Korrektur den Fehlerpfad mitreissen.
    """
    manager = TokenSecurityManager(
        config_service=_KonfigurationsDienstAttrappe({"bot_token": "noch-verschluesselt"})
    )

    ergebnis = manager.migrate_to_environment_variable()

    assert ergebnis["success"] is False
    assert "decrypt" in ergebnis["error"].lower(), (
        "Die Fehlermeldung muss auf das Entschluesseln zeigen. Steht dort ein "
        "AttributeError, ist der Weg weiterhin gar nicht erreichbar."
    )
    assert len(ergebnis["instructions"]) > 0
