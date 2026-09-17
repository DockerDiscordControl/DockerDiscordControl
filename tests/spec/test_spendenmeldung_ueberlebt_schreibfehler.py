# -*- coding: utf-8 -*-
"""Ein fehlgeschlagener Schreibvorgang darf die alte Spendenmeldung nicht zerstoeren.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers. Der Sache nach gehoert dieser Test zu Z7.

DER BEFUND (Stufe 2, Punkt 2 - lautloses Wegraeumen; gefunden bei der
Z7-Nachmessung, die ich zuvor mit dem falschen Muster durchgefuehrt hatte).

``services/web/donation_service.py:197`` schreibt die Meldedatei so::

    with open(notification_file, "w") as f:
        json.dump(notification, f)

``open(..., "w")`` KUERZT die Datei im Moment des Oeffnens. Erst danach wird
geschrieben. Dazwischen liegt ein Fenster, in dem die Datei existiert und leer
oder halb ist.

WARUM DAS HIER MEHR IST ALS EIN ABSTURZRISIKO: Diese Datei hat einen
NEBENLAEUFIGEN LESER. ``services/donation/notification_service.py:26`` liest
sie, und ``cogs/docker_control.py:5152`` fragt sie per ``@tasks.loop(seconds=30)``
ab. Beide Haelften laufen im SELBEN Prozess - die Weboberflaeche in einem
Hintergrundfaden, der Bot im Hauptfaden.

Und der Leser ist unbarmherzig: Bei ``json.JSONDecodeError`` LOESCHT er die
Datei (``notification_service.py:56-64``, Kommentar "Try to delete corrupted
file so we don't get stuck") und liefert ``None``. Trifft der Poller also das
Kuerzungsfenster, ist die Spendenankuendigung weg - nicht verzoegert, sondern
endgueltig. Gemeldet wird das durch eine ``logger.error``-Zeile. Es braucht
dafuer keinen Absturz, nur Zeitablauf.

WAS DIESER TEST BEWEIST - und was nicht. Er beweist die Eigenschaft, die Z7
WOERTLICH behauptet: "Ein Absturz mitten im Schreiben laesst die alte Datei
unversehrt." Das ist deterministisch pruefbar, indem die Serialisierung
scheitert. ``atomic_write_json`` serialisiert VOR dem Oeffnen
(``utils/atomic_io.py:66-69``), die Zieldatei bleibt dann unberuehrt; der
Direktschreiber hat sie zu diesem Zeitpunkt laengst gekuerzt.

Er beweist NICHT das 30-Sekunden-Wettrennen oben. Ein Test mit Fadenverschraenkung
waere unzuverlaessig, und ein flatternder Test ist schlimmer als keiner - er wird
ignoriert, und ein ignorierter Test ist so wertlos wie ein gruener. Das Wettrennen
steht hier als BEGRUENDUNG, warum die Eigenschaft praktisch zaehlt, nicht als
Behauptung ueber das Gemessene.

VORHANDENE ABDECKUNG, damit hier kein Zwilling entsteht:
``tests/unit/extended/test_coverage_push_v3.py:77-122`` deckt fuenf Zweige des
LESERS ab (keine Datei, lesen+loeschen, ungueltiges JSON, Loeschfehler,
Singleton). Fuer den SCHREIBER gibt es keinen Test seiner Schreibweise;
``tests/unit/services/donation/test_donation_web_services.py:184-186`` prueft,
DASS geschrieben wird, nicht WIE.

ZWEITEILIG, und der zweite Teil ist die Lehre aus einem heutigen Fehler:
Teil 1 prueft den Schreiber, Teil 2 belegt, dass ``process_donation`` ihn
ueberhaupt anspringt. Ohne Teil 2 waere Teil 1 eine Aussage ueber eine Funktion,
die niemand aufruft - genau die Falle aus Stufe 3, Pruefung 3, an der in diesem
Programm schon ein Melder wertlos wurde.

GEGENPROBE (durchgefuehrt 2026-09-17) - drei Messungen, weil drei Tests zu
belegen waren. Genannt werden TESTNAMEN statt Zeilennummern: Zweimal habe ich
heute eine Zeilenzahl notiert, die derselbe Schreibvorgang sofort veraltet hat.

*1. Der Befundtest war VOR der Korrektur rot* - an der Byte-Behauptung, nicht an
der Existenzpruefung. Und die Messung war SCHLIMMER als meine Erwartung: Ich
hatte eine leere Datei vermutet, tatsaechlich stand dort ein HALBER, gueltig
beginnender Datensatz::

    + b'{"type": "donation", "donor": "Bob", "amount": '
    - b'{"type": "donation", "donor": "Vorher", "amount": 1.0, "timestamp": ...}'

``json.dump`` schreibt stroemend (die Rueckverfolgung zeigt ``for chunk in
iterable`` in json/__init__.py:181), also lagen die ersten Stuecke der neuen
Meldung bereits auf der Platte, als die Serialisierung an ``TypeError: Object of
type object is not JSON serializable`` scheiterte. Zurueck bleibt kein leeres
Nichts, sondern etwas, das wie eine echte Meldung beginnt und mitten im
Schluessel abbricht. Der Poller liest das, ``json.load`` wirft, und der Leser
LOESCHT die Datei - alte UND neue Meldung sind weg. Nach der Korrektur: 3 gruen.

*2. Der Verdrahtungstest war von Anfang an gruen* und damit unbewiesen. Mutation:
``process_donation`` ueberspringt Schritt 3 (``discord_success = False``)::

    -> 1 failed, 2 passed

Rot wurde genau er, an seiner eigenen ``is_file()``-Behauptung; die beiden
anderen blieben gruen, weil sie den Schreiber direkt rufen. Die Mutation traf
also die Verbindung und nichts sonst.

*3. Der Vorrichtungs-Waechter war ebenfalls durchgehend gruen.* Mutation: Der
Schreiber legt die Datei unter einem anderen Namen ab::

    -> 2 failed, 1 passed

Rot wurde er an seiner eigenen ``is_file()``-Behauptung, und das Protokoll nennt
den Grund: "Discord notification created: .../MUTATION_andere_datei.json". Der
Verdrahtungstest fiel als angekuendigte Mitwirkung (er sucht dieselbe Datei), der
Atomaritaetstest blieb gruen - ein misslungener Schreibvorgang auf einen ANDEREN
Namen laesst die alte Meldung unberuehrt, und genau das behauptet er.

*Vier Wege, auf denen diese Roten wertlos gewesen waeren*, standen vor jedem Lauf
fest und traten nie ein: der jeweilige Test bleibt gruen (waere hohl); er faellt
an einer anderen Behauptung als der gepruefte Zusammenhang; die Mutation macht
mehr rot als behauptet; Sammel- oder Importfehler.

BETROFFENE GRUPPEN, alle gruen gemessen: services/donation 52, services/web 358,
spec 82, test_donation_system_functional 3, test_unified_donation_service 4,
integration 5, audit_2026_09 564, blueprints 276, extended 731, services/mech 433.
"""

import json
from unittest.mock import patch

import pytest

from services.web.donation_service import DonationRequest, DonationService

ALTE_MELDUNG = {"type": "donation", "donor": "Vorher", "amount": 1.0,
                "timestamp": "2026-01-01T00:00:00"}


@pytest.fixture
def dienst(tmp_path):
    """DonationService, dessen Meldeverzeichnis auf ein Wegwerf-Verzeichnis zeigt.

    ``NOTIFICATION_DIR`` ist ein Klassenattribut mit dem Wert "/app/config"
    (donation_service.py:53). Es wird auf der INSTANZ ueberschrieben - so wie es
    ``tests/unit/services/donation/test_donation_web_services.py:167`` bereits
    tut; eine zweite Vorrichtung daneben waere genau die Doppelung, die dieses
    Programm sucht.
    """
    service = DonationService()
    service.NOTIFICATION_DIR = str(tmp_path)
    return type("Umgebung", (), {
        "service": service,
        "verzeichnis": tmp_path,
        "datei": tmp_path / "donation_notification.json",
    })


def test_die_vorrichtung_schreibt_ins_wegwerfverzeichnis(dienst):
    """Sicherung gegen ein stumpfes Werkzeug.

    Landet die Meldedatei nicht dort, wo der Test sie sucht, waeren die Tests
    unten gruen, ohne irgendetwas zu belegen - und im schlimmsten Fall haetten
    sie in die echte Ablage geschrieben. Diese Bauart hat in diesem Programm
    schon zweimal einen Melder wertlos gemacht.
    """
    anfrage = DonationRequest(amount=5.5, donor_name="Alice", publish_to_discord=True)

    assert dienst.service._handle_discord_notification(anfrage) is True
    assert dienst.datei.is_file(), (
        f"Keine Meldedatei in {dienst.verzeichnis} - NOTIFICATION_DIR zeigt woanders hin."
    )
    inhalt = json.loads(dienst.datei.read_text(encoding="utf-8"))
    assert inhalt["donor"] == "Alice"
    assert inhalt["amount"] == 5.5


def test_ein_fehlgeschlagener_schreibvorgang_zerstoert_die_alte_meldung_nicht(dienst):
    """DER BEFUND: Die vorherige Meldung muss einen misslungenen Schreibvorgang ueberleben.

    Erzwungen wird der Fehlschlag ueber einen nicht serialisierbaren Betrag -
    deterministisch, ohne Faeden, ohne Zeitabhaengigkeit. ``json.dump`` wirft
    dann ``TypeError``, den ``donation_service.py:208-210`` faengt.

    Der Unterschied, um den es geht: Der Direktschreiber hat die Datei beim
    Oeffnen bereits gekuerzt, bevor die Serialisierung ueberhaupt scheitert.
    ``atomic_write_json`` serialisiert zuerst und fasst die Zieldatei gar nicht
    an (utils/atomic_io.py:66-69).
    """
    dienst.datei.write_text(json.dumps(ALTE_MELDUNG), encoding="utf-8")
    vorher = dienst.datei.read_bytes()

    # Ein Wert, den json nicht serialisieren kann.
    anfrage = DonationRequest(amount=object(), donor_name="Bob", publish_to_discord=True)

    assert dienst.service._handle_discord_notification(anfrage) is False, (
        "Ein nicht serialisierbarer Betrag muss als Fehlschlag gemeldet werden."
    )

    assert dienst.datei.is_file(), (
        "Die alte Meldung ist VERSCHWUNDEN. open(..., 'w') kuerzt die Datei beim "
        "Oeffnen - der Fehlschlag danach kann sie nicht mehr retten."
    )
    assert dienst.datei.read_bytes() == vorher, (
        "Die alte Meldung wurde beschaedigt. Z7 verlangt, dass ein Abbruch mitten "
        "im Schreiben die alte Datei unversehrt laesst. Hier zaehlt das doppelt: "
        "Der Bot pollt diese Datei alle 30 Sekunden, und bei ungueltigem JSON "
        "LOESCHT er sie (notification_service.py:56-64) - die Spendenankuendigung "
        "waere endgueltig weg, gemeldet nur durch eine logger.error-Zeile."
    )


def test_process_donation_ruft_den_schreiber_wirklich(dienst):
    """Verdrahtung: Der oeffentliche Weg muss den Schreiber oben erreichen.

    Sonst waere der Test darueber eine Aussage ueber eine Funktion, die niemand
    aufruft. Geprueft wird ueber ``process_donation``; ersetzt wird nur der
    Mech-Schritt, nicht das ganze unified_donation_service-Geruest - dessen
    Attrappen liegen in einer anderen Testgruppe und muessten hier nachgebaut
    werden.

    ``_build_donation_response`` vertraegt ``mech_state=None``: Jedes Feld faellt
    auf einen Vorgabewert zurueck (donation_service.py:230-236).
    """
    anfrage = DonationRequest(amount=7.25, donor_name="Carol", publish_to_discord=True)

    with patch.object(dienst.service, "_process_mech_donation",
                      return_value={"success": True, "mech_state": None}), \
         patch("services.infrastructure.action_logger.log_user_action"):
        ergebnis = dienst.service.process_donation(anfrage)

    assert ergebnis.success is True
    assert dienst.datei.is_file(), (
        "process_donation hat keine Meldedatei hinterlassen - Schritt 3 "
        "(donation_service.py:85) erreicht den Schreiber nicht mehr."
    )
    inhalt = json.loads(dienst.datei.read_text(encoding="utf-8"))
    assert inhalt["donor"] == "Carol"
    assert inhalt["amount"] == 7.25
