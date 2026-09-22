# -*- coding: utf-8 -*-
"""The donation notification from the web panel to the bot must live in ``DDC_CONFIG_DIR``.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

THE FINDING. The notification is a HANDOVER: ``DonationService`` (web panel)
writes ``donation_notification.json``, ``DonationNotificationService`` (bot)
reads and deletes it. Both have ``/app/config`` HARD-wired::

    services/web/donation_service.py:55         NOTIFICATION_DIR = "/app/config"
    services/donation/notification_service.py:23  "/app/config/donation_notification.json"

They agree with each other - but both ignore the variable, and outside the
container (development run without /app) even creating the directory fails:
the donation announcement is lost, reported only in the log. In the test run
the writer, without redirection, targets the real /app/config (Z2).

SCOPE: ``NOTIFICATION_DIR`` stays as an adjustment knob - four test files set
it on the object. When unset (None) the shared source applies.

HOW IT IS CHECKED HERE: end to end - the real writer writes, the real reader
reads. Neither of them is redirected; only the variable is set.
"""

import pytest

from services.donation.notification_service import DonationNotificationService
from services.web.donation_service import DonationRequest, DonationService


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    target = tmp_path / "own_config"
    target.mkdir()
    monkeypatch.setenv("DDC_CONFIG_DIR", str(target))
    return target


def test_the_notification_reaches_the_bot(config_dir):
    request = DonationRequest(amount=5.0, donor_name="Probe")

    assert DonationService()._handle_discord_notification(request) is True
    # One file per announcement, so the test asks the directory, not a name.
    assert list(config_dir.glob("donation_notification*.json")), (
        "The web panel did not write the donation notification to DDC_CONFIG_DIR."
    )

    data = DonationNotificationService().check_and_retrieve_notification()

    assert data is not None and data.get("donor") == "Probe", (
        f"The bot did not find the notification in DDC_CONFIG_DIR: {data!r}"
    )
    assert not list(config_dir.glob("donation_notification*.json")), (
        "The bot did not consume the notification."
    )


def test_a_set_knob_still_applies(config_dir, tmp_path):
    """Scope: the redirection used by the existing tests."""
    elsewhere = tmp_path / "elsewhere"
    service = DonationService()
    service.NOTIFICATION_DIR = str(elsewhere)

    assert service._handle_discord_notification(DonationRequest(amount=1.0, donor_name="X")) is True
    assert list(elsewhere.glob("donation_notification*.json"))
    assert not list(config_dir.glob("donation_notification*.json"))
