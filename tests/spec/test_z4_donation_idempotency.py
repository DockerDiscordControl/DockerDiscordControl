# -*- coding: utf-8 -*-
# @deckt Z4
"""Z4 - Geld wird nie doppelt oder unbelegt gutgeschrieben.

Jede Spende traegt einen Idempotenzschluessel, der nicht von der Uhrzeit
abhaengt. Zweimal dieselbe Absendung ergibt einen Eintrag, nicht zwei - eine
echte zweite Spende desselben Spenders aber sehr wohl zwei.

Vom Betreiber entschieden (2026-09-16): Der Browser erzeugt beim Oeffnen des
Spenden-Dialogs ein einmaliges Token und sendet es mit; der Discord-Weg benutzt
``interaction.id``. Bewusst NICHT gewaehlt wurde ein Zeitfenster ueber
(Spender, Betrag): das haette eine echte schnelle Zweitspende verschluckt und
damit echtes Geld verloren.

Der Befund ist ein Durchreichungsfehler, kein fehlendes Verfahren:
``ProgressService.add_donation`` kann Idempotenz bereits und ist dafuer getestet
(``tests/unit/services/mech/test_progress_service.py:322``). Der Schluessel geht
aber zwischen Eintrittsstelle und Dienst verloren - ``DonationRequest`` hat kein
Feld dafuer, und ``processors.py:36/52`` reicht keinen weiter. Ohne Schluessel
bildet ``progress_service.py:1024`` einen aus
``mech_id|donor|amount|utcnow().isoformat()``; zwei identische Absendungen
Mikrosekunden auseinander gelten damit als verschieden.

Geprueft wird das beobachtbare Verhalten am Eintrittspunkt, nicht die Verkabelung
dazwischen - sonst pruefte der Test die Umsetzung statt der Zusicherung.

GEGENPROBE (durchgefuehrt 2026-09-16), in zwei ungleichen Haelften:

*Die drei Dienst-Tests* schlugen vor der Korrektur mit
``TypeError: ... unexpected keyword argument 'idempotency_key'`` fehl. Das ist
ein ehrliches, aber **schwaches** Rot: es beweist, dass das Verfahren an der
Eintrittsstelle fehlte, nicht dass die Zusicherung verletzt wurde. Seit der
Korrektur pruefen sie Buchungszahlen statt Signaturen und koennen daher auch
kuenftig fehlschlagen, wenn die Durchreichung zurueckfaellt.

*Die beiden Vertragstests zur Oberflaeche* waren zuerst aus dem FALSCHEN Grund
rot - der Fehler lag in ihnen selbst, nicht im Code: der Ausschnitt endete an der
verschachtelten ``resetSubmitButton()``, und die Liste erlaubter Schreibweisen
erkannte die tatsaechliche Absicherung ``(window.crypto && crypto.randomUUID)``
nicht. Beinahe waere funktionierender Code umgebaut worden, bis ein kaputter Test
gruen wird. Nach der Korrektur des Tests wurde die Gegenprobe echt nachgeholt:
``idempotency_key`` im Frontend umbenannt und die Absicherung entschaerft ->
genau diese zwei Tests rot (9 gruen); Datei wiederhergestellt -> 11 gruen.

Dabei gefunden und mitbehoben: ``FakeMechService.add_donation`` in
``tests/test_unified_donation_service.py`` nagelte die alte Signatur fest und
verschluckte den Schluessel im async-Pfad.
"""

import uuid
from pathlib import Path

import pytest

from services.donation.unified_donation_service import (
    process_discord_donation,
    process_web_ui_donation,
)
from services.mech.progress_service import read_events


def _spenden_zaehlen(marke: str) -> int:
    """Zaehle gebuchte Spenden, deren Spendername ``marke`` enthaelt.

    Absolut zu zaehlen waere unsicher: das Ereignislog ist innerhalb eines
    Testlaufs geteilt. Die Marke ist pro Test einmalig.
    """
    return sum(
        1
        for e in read_events()
        if e.type == "DonationAdded" and marke in str(e.payload.get("donor") or "")
    )


@pytest.fixture
def marke() -> str:
    """Einmaliger Spendername, damit Tests einander nicht zaehlen."""
    return f"z4-{uuid.uuid4().hex[:12]}"


async def test_discord_zweimal_derselbe_schluessel_bucht_einmal(marke):
    """Dieselbe Absendung zweimal verarbeitet: eine Buchung.

    Entspricht dem Fall, den es in der Wirklichkeit gibt: derselbe
    ``interaction.id`` erreicht den Dienst zweimal (Wiederholung, doppelte
    Zustellung).
    """
    schluessel = f"interaction-{uuid.uuid4().hex}"

    for _ in range(2):
        ergebnis = await process_discord_donation(
            discord_username=marke,
            amount=1.0,
            user_id="42",
            bot_instance=None,
            idempotency_key=schluessel,
        )
        assert ergebnis.success is True

    assert _spenden_zaehlen(marke) == 1, (
        "Dieselbe Absendung wurde mehrfach gebucht - das Spendenbuch zeigt "
        "mehr Geld an, als eingegangen ist"
    )


async def test_discord_verschiedene_schluessel_buchen_zweimal(marke):
    """Zwei echte Spenden gleicher Hoehe muessen beide durchgehen.

    Die Gegenrichtung zur Zusicherung, und der Grund gegen ein Zeitfenster ueber
    (Spender, Betrag): eine echte Zweitspende darf nie verschluckt werden.
    """
    for _ in range(2):
        ergebnis = await process_discord_donation(
            discord_username=marke,
            amount=1.0,
            user_id="42",
            bot_instance=None,
            idempotency_key=f"interaction-{uuid.uuid4().hex}",
        )
        assert ergebnis.success is True

    assert _spenden_zaehlen(marke) == 2, (
        "Eine echte zweite Spende wurde als Dublette verworfen - es ist Geld "
        "eingegangen, das nicht im Buch steht"
    )


def test_web_zweimal_dasselbe_token_bucht_einmal(marke):
    """Das Token aus dem Browser wird bis ins Spendenbuch durchgereicht."""
    token = f"web-{uuid.uuid4().hex}"

    for _ in range(2):
        ergebnis = process_web_ui_donation(marke, 1.0, idempotency_key=token)
        assert ergebnis.success is True

    assert _spenden_zaehlen(marke) == 1, (
        "Erneutes Absenden desselben Formulars hat ein zweites Mal gebucht"
    )


# ---------------------------------------------------------------------------
# Vertrag zur Aufrufstelle
#
# Die Tests oben pruefen die Dienst-Eintrittspunkte. Sie wuerden auch dann gruen,
# wenn nur das Backend den Schluessel durchreicht und der Browser nie einen
# sendet - dann waere Z4 im Alltag weiterhin gebrochen. Genau dieser Fall ("die
# Funktion ist geprueft, die Aufrufstelle nicht") war ein Befund aus Stufe 0,
# deshalb wird hier der Quelltext der Oberflaeche gelesen. Dasselbe Mittel
# benutzt das Projekt bereits in test_pkg_a_web.py und
# test_pkg_d2_mech_difficulty_contract.py.
# ---------------------------------------------------------------------------

CONFIG_HTML = (
    Path(__file__).resolve().parents[2] / "app" / "templates" / "config.html"
)


def _funktionsrumpf(quelltext: str, name: str) -> str:
    """Schneide den Rumpf einer Funktion oberster Ebene aus ``config.html``.

    Funktionen oberster Ebene sind dort mit 8 Leerzeichen eingerueckt,
    verschachtelte mit 12. Ein naiver Schnitt am naechsten ``function `` endet
    deshalb an der verschachtelten ``resetSubmitButton()`` - die erste Fassung
    dieses Tests tat genau das und blieb rot, obwohl der Code stimmte.
    """
    start = quelltext.index(f"function {name}()")
    rest = quelltext[start:]
    naechste = rest.find("\n        function ")
    return rest if naechste == -1 else rest[:naechste]


def _token_zuweisung(rumpf: str) -> str:
    """Die eine Anweisung, die das Token erzeugt (bis zum Semikolon)."""
    ab = rumpf[rumpf.index("window.__ddcDonationToken ="):]
    return ab[: ab.index(";") + 1]


def test_oberflaeche_sendet_ein_token_mit():
    """``submitDonation()`` legt ein Token an und schickt es im Rumpf mit.

    Hinweis zur Belastbarkeit: Das ist ein Test ueber Quelltext, kein
    ausgefuehrtes JavaScript. Er faellt, wenn niemand mehr ein Token sendet -
    aber auch, wenn jemand die Funktion umbenennt. Das Projekt benutzt dasselbe
    Mittel in ``test_pkg_a_web.py`` und ``test_pkg_d2_mech_difficulty_contract.py``.
    """
    rumpf = _funktionsrumpf(CONFIG_HTML.read_text(encoding="utf-8"), "submitDonation")

    assert "idempotency_key" in rumpf, (
        "Der Spenden-Dialog sendet kein Token - ein Wiederholungsversuch nach "
        "dem Zeitlimit wuerde ein zweites Mal buchen"
    )
    assert "__ddcDonationToken" in rumpf, "kein Token angelegt"


def test_token_hat_einen_rueckfallweg_ohne_https():
    """``crypto.randomUUID`` fehlt ohne sicheren Kontext.

    DDC laeuft bewusst als reines HTTP im LAN (SPEC.md B3). Dort ist
    ``crypto.randomUUID`` nicht verfuegbar; ohne Rueckfall entstuende gar kein
    Token und die Absendung liefe unbemerkt ohne Schutz.

    Geprueft wird die Zuweisung selbst - Absicherung UND Ersatzweg - statt
    bestimmter Schreibweisen: das Aufzaehlen erlaubter Schreibweisen war der
    Fehler der ersten Fassung dieses Tests.
    """
    rumpf = _funktionsrumpf(CONFIG_HTML.read_text(encoding="utf-8"), "submitDonation")
    zuweisung = _token_zuweisung(rumpf)

    assert "randomUUID" in zuweisung, "kein Token-Erzeuger in der Zuweisung"
    assert ("window.crypto" in zuweisung or "typeof crypto" in zuweisung), (
        "randomUUID wird ohne Verfuegbarkeitspruefung benutzt - ueber HTTP ist "
        "die Funktion undefiniert"
    )
    assert ("?" in zuweisung and ":" in zuweisung) or "||" in zuweisung, (
        "kein Ersatzweg, wenn randomUUID fehlt - dann entstuende gar kein Token "
        "und die Spende ginge ungeschuetzt raus"
    )
