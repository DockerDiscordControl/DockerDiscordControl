# -*- coding: utf-8 -*-
"""The update notice knows which version is running, and does not repeat itself.

Three in the update notifier, which posts "DDC has been updated" into the
control channels after an upgrade:

* the version it compares against is the literal "2025.01.07" in the source.
  The real version is DDC_VERSION, set by the Dockerfile and read by /health
  and the panel footer. So after the first installation the marker on disk
  already equals that literal and the notice never fires again - while its
  text still advertises the January 2025 feature set;
* a status file that cannot be written (the classic root-owned file) was
  ignored: the notice counted as shown, and on the next start it was posted
  again, into every channel, for ever;
* one successful channel marked the whole version done, so a channel that was
  unreachable at that moment never got it - and a crash before the mark sent
  it to everybody a second time. The channels that received it are recorded.

COUNTER-CHECK (2026-09-22): red before - the notifier reported the 2025
literal, a failed save still reported success, and the second run posted to
the channel that already had it.
"""

import json

import pytest

from services.infrastructure.update_notifier import UpdateNotifier


@pytest.fixture
def notifier(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("DDC_VERSION", "3.0.0")
    return UpdateNotifier()


def test_the_running_version_is_the_image_version(notifier):
    assert notifier.current_version == "3.0.0"


def test_without_a_version_nothing_is_announced(tmp_path, monkeypatch):
    """Counter-check: guessing a version would post a notice about nothing."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("DDC_VERSION", raising=False)

    quiet = UpdateNotifier()

    assert quiet.should_show_update_notification() is False


def test_a_status_that_cannot_be_written_is_not_counted_as_shown(notifier, monkeypatch):
    monkeypatch.setattr(notifier, "save_update_status", lambda status: False)

    assert notifier.mark_notification_shown() is False
    assert notifier.should_show_update_notification() is True, (
        "the notice would be counted as delivered although nothing was written")


def test_a_channel_that_has_it_is_not_told_again(notifier):
    notifier.mark_notification_shown(channel_ids=[111])

    assert notifier.channels_still_to_tell([111, 222]) == [222]


def test_a_new_version_starts_again(notifier, monkeypatch):
    """Counter-check: the record is per version, not for ever."""
    notifier.mark_notification_shown(channel_ids=[111, 222])
    assert notifier.channels_still_to_tell([111, 222]) == []

    monkeypatch.setenv("DDC_VERSION", "3.1.0")
    later = UpdateNotifier()

    assert later.channels_still_to_tell([111, 222]) == [111, 222]
