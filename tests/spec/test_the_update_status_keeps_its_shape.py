# -*- coding: utf-8 -*-
"""What `get_update_status` promises is a shape, not whatever is in the file.

THE FINDING (review C65, section 20 F4): ``get_update_status`` builds a
``default_status`` with ``last_notified_version`` and ``notifications_shown``
and returns it for a missing or unparsable file. For a file that parses, it
returns ``json.load(f)`` as it stands - so the two keys are only guaranteed
on the error paths.

``mark_notification_shown`` then reads ``status["notifications_shown"]`` with
direct indexing, two lines below a defensive ``.get`` for the other key. A
file that parses but does not carry that key - hand-edited, or written by an
older or newer schema - raises ``KeyError`` there. That call happens inside
``send_update_notification``'s try, whose except clause names RuntimeError and
three discord exceptions, so the KeyError left that method uncaught.
"""

import json

import pytest

from services.infrastructure.update_notifier import UpdateNotifier


@pytest.fixture
def notifier(tmp_path):
    return UpdateNotifier(config_dir=str(tmp_path))


def _write(notifier, payload):
    notifier.status_file.write_text(json.dumps(payload), encoding="utf-8")


def test_a_file_without_the_key_is_still_a_status(notifier):
    _write(notifier, {"last_notified_version": "2024.01.01"})

    status = notifier.get_update_status()

    assert status["notifications_shown"] == []


def test_a_file_without_the_key_can_still_be_marked(notifier):
    """THE FINDING in the concrete: this is the call that raised."""
    _write(notifier, {"last_notified_version": "2024.01.01"})

    notifier.mark_notification_shown()

    assert notifier.current_version in notifier.get_update_status()["notifications_shown"]


def test_a_file_that_is_not_an_object_is_not_a_status(notifier):
    """A JSON list parses perfectly well and is not what this file holds."""
    _write(notifier, ["2024.01.01"])

    status = notifier.get_update_status()

    assert status["notifications_shown"] == []
    assert status["last_notified_version"] is None


def test_a_sound_file_is_read_as_written(notifier):
    """Counter-check: always answering with the defaults would pass above."""
    _write(notifier, {"last_notified_version": "2024.01.01",
                      "notifications_shown": ["2024.01.01"]})

    status = notifier.get_update_status()

    assert status["last_notified_version"] == "2024.01.01"
    assert status["notifications_shown"] == ["2024.01.01"]


def test_a_key_this_version_does_not_know_survives(notifier):
    """Counter-check: filling the gaps must not mean dropping what is there -
    save_update_status writes the whole record back."""
    _write(notifier, {"last_notified_version": "2024.01.01",
                      "notifications_shown": [], "dismissed_until": "2030-01-01"})

    assert notifier.get_update_status()["dismissed_until"] == "2030-01-01"


def test_both_keys_are_there_whatever_the_file_says(notifier):
    """The shape is the whole promise, not just the key that is indexed today.

    The list guard below the merge happens to repair `notifications_shown`, so
    a missing `last_notified_version` went unnoticed - until the next caller
    indexes that one (found by mutation M2 of review C65).
    """
    _write(notifier, {"something_else": 1})

    status = notifier.get_update_status()

    assert set(status) >= {"last_notified_version", "notifications_shown"}
    assert status["last_notified_version"] is None
