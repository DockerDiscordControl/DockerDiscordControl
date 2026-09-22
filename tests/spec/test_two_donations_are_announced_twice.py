# -*- coding: utf-8 -*-
"""Two donations booked in the panel are announced twice, not once.

THE FINDING: the panel wrote the announcement for the bot into ONE file,
config/donation_notification.json, and the bot polls that file every 30
seconds (cogs/docker_control.py, check_donation_notifications). Two donations
entered inside one interval - an operator booking what came in that day - and
the second write replaced the first: both are counted, but only the second one
is ever announced, and nothing says the first was dropped.

Each announcement is its own file now, and the bot takes them oldest first.

COUNTER-CHECK (2026-09-22): red before the fix - the second write overwrote the
first, `first` and `second` came back as the same donor and the third read was
None. A file left over from an older version (the fixed name) is still read
(test_a_file_from_an_older_version_is_still_read); a directory with nothing in
it is still not an error (test_nothing_to_announce_is_not_an_error).
"""

import json

import pytest

from services.donation.notification_service import DonationNotificationService
from services.web.donation_service import DonationRequest, DonationService


@pytest.fixture
def reader(tmp_path):
    return DonationNotificationService(
        notification_path=str(tmp_path / "donation_notification.json"))


def _announce(tmp_path, donor, amount):
    service = DonationService()
    service.NOTIFICATION_DIR = str(tmp_path)
    assert service._handle_discord_notification(
        DonationRequest(amount=amount, donor_name=donor)) is True


def test_both_announcements_survive(tmp_path, reader):
    _announce(tmp_path, "Bob", 5.0)
    _announce(tmp_path, "Ada", 7.0)

    first = reader.check_and_retrieve_notification()
    second = reader.check_and_retrieve_notification()

    assert first is not None and second is not None, "an announcement was lost"
    assert sorted([first["donor"], second["donor"]]) == ["Ada", "Bob"]
    assert reader.check_and_retrieve_notification() is None


def test_the_older_one_comes_first(tmp_path, reader):
    _announce(tmp_path, "First", 1.0)
    _announce(tmp_path, "Second", 2.0)

    assert reader.check_and_retrieve_notification()["donor"] == "First"


def test_a_file_from_an_older_version_is_still_read(tmp_path, reader):
    """Counter-check: an update must not leave an announcement lying around."""
    (tmp_path / "donation_notification.json").write_text(
        json.dumps({"type": "donation", "donor": "Old", "amount": 3.0}), encoding="utf-8")

    assert reader.check_and_retrieve_notification()["donor"] == "Old"
    assert reader.check_and_retrieve_notification() is None


def test_nothing_to_announce_is_not_an_error(reader):
    """Counter-check: the case that holds 30 seconds out of 30."""
    assert reader.check_and_retrieve_notification() is None


def test_an_unreadable_announcement_does_not_block_the_next(tmp_path, reader):
    """Counter-check: one broken file must not stop the queue."""
    (tmp_path / "donation_notification.json").write_text("{not json", encoding="utf-8")
    _announce(tmp_path, "Ada", 7.0)

    assert reader.check_and_retrieve_notification() is None  # the broken one, dropped
    assert reader.check_and_retrieve_notification()["donor"] == "Ada"


def test_one_cycle_announces_everything_that_waits(tmp_path, monkeypatch):
    """Both donations are told in the same cycle, not one per 30 seconds.

    COUNTER-CHECK: red before - one embed went out, the second donation waited
    for the next poll. test_nothing_to_announce_is_not_an_error keeps the empty
    case honest, so the drain cannot become "always send something".
    """
    import asyncio
    from unittest.mock import MagicMock

    from discord.ext import tasks

    import cogs.docker_control as dc

    _announce(tmp_path, "Bob", 5.0)
    _announce(tmp_path, "Ada", 7.0)

    monkeypatch.setattr(tasks.Loop, "start", lambda self, *a, **k: None)
    monkeypatch.setattr(dc, "DockerControlCog", MagicMock())
    config_service = MagicMock()
    config_service.get_config.return_value = {}
    monkeypatch.setattr("services.config.config_service.get_config_service",
                        lambda: config_service)
    monkeypatch.setattr("services.donation.donation_utils.is_donations_disabled",
                        lambda: False)
    service = DonationNotificationService(
        notification_path=str(tmp_path / "donation_notification.json"))
    monkeypatch.setattr(
        "services.donation.notification_service.get_donation_notification_service",
        lambda: service)
    monkeypatch.setattr(dc, "load_config",
                        lambda: {"channel_permissions": {"123": {"donation_broadcasts": True}}})

    bot = MagicMock()
    channel = MagicMock()
    sent = []
    async def send(**kwargs):
        sent.append(kwargs["embed"].description)
    channel.send = send
    bot.get_channel.return_value = channel

    dc.setup(bot)
    asyncio.run(dc.DockerControlCog.return_value.donation_notification_task.coro())

    assert len(sent) == 2, f"only these went out: {sent}"
    assert any("Bob" in text for text in sent) and any("Ada" in text for text in sent)
