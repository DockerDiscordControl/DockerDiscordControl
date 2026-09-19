# -*- coding: utf-8 -*-
"""Die Spendenmeldung vom Web-Panel an den Bot muss in ``DDC_CONFIG_DIR`` liegen.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND. Die Meldung ist eine UEBERGABE: ``DonationService`` (Web-Panel)
schreibt ``donation_notification.json``, ``DonationNotificationService`` (Bot)
liest und loescht sie. Beide haben ``/app/config`` FEST verdrahtet::

    services/web/donation_service.py:55         NOTIFICATION_DIR = "/app/config"
    services/donation/notification_service.py:23  "/app/config/donation_notification.json"

Untereinander einig - aber beide ignorieren die Variable, und ausserhalb des
Containers (Entwicklungslauf ohne /app) scheitert schon das Anlegen des
Verzeichnisses: Die Spendenankuendigung geht verloren, gemeldet nur im Log.
Im Testlauf zielt der Schreiber ohne Umleitung aufs echte /app/config (Z2).

ABGRENZUNG: ``NOTIFICATION_DIR`` bleibt als Stellschraube erhalten - vier
Testdateien setzen sie am Objekt. Ungesetzt (None) gilt die gemeinsame Quelle.

WIE HIER GEPRUEFT WIRD: von Ende zu Ende - der echte Schreiber schreibt, der
echte Leser liest. Keiner der beiden wird umgeleitet; nur die Variable ist
gesetzt.
"""

import pytest

from services.donation.notification_service import DonationNotificationService
from services.web.donation_service import DonationRequest, DonationService


@pytest.fixture
def verzeichnis(tmp_path, monkeypatch):
    ziel = tmp_path / "eigene_konfig"
    ziel.mkdir()
    monkeypatch.setenv("DDC_CONFIG_DIR", str(ziel))
    return ziel


def test_die_meldung_kommt_beim_bot_an(verzeichnis):
    anfrage = DonationRequest(amount=5.0, donor_name="Probe")

    assert DonationService()._handle_discord_notification(anfrage) is True
    assert (verzeichnis / "donation_notification.json").exists(), (
        "Das Web-Panel schrieb die Spendenmeldung nicht nach DDC_CONFIG_DIR."
    )

    daten = DonationNotificationService().check_and_retrieve_notification()

    assert daten is not None and daten.get("donor") == "Probe", (
        f"Der Bot fand die Meldung nicht in DDC_CONFIG_DIR: {daten!r}"
    )
    assert not (verzeichnis / "donation_notification.json").exists(), (
        "Der Bot hat die Meldung nicht verbraucht."
    )


def test_eine_gesetzte_stellschraube_gilt_weiter(verzeichnis, tmp_path):
    """Abgrenzung: die Umleitung der vorhandenen Tests."""
    anderswo = tmp_path / "anderswo"
    dienst = DonationService()
    dienst.NOTIFICATION_DIR = str(anderswo)

    assert dienst._handle_discord_notification(DonationRequest(amount=1.0, donor_name="X")) is True
    assert (anderswo / "donation_notification.json").exists()
    assert not (verzeichnis / "donation_notification.json").exists()
