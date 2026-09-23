# -*- coding: utf-8 -*-
"""Changing one setting does not roll a whole save back.

THE FINDING (independent review of the web panel, 2026-09-23):
ConfigService.update_config_fields opens ``with self._save_lock:``, reads
config.json, applies the change - and the write is DEDENTED out of that block:

    with self._save_lock:
        existing = self._load_json_file(...)
        existing.update(updates)
    return self.save_config(existing)

The gap is structural, not a slip: ``_save_lock`` is a plain Lock, so the
write could not be nested inside it without deadlocking.

waitress serves the panel from a pool of threads, so two requests really do
overlap:

    thread A  POST /set_ui_language   -> reads config.json (state S0), lets go
    thread B  POST /save_config_api   -> writes the operator's whole edited
                                         configuration (S1)
    thread A  writes S0 + the language

save_config's critical-field merge only restores bot_token, guild_id,
encrypted_bot_token and web_ui_password_hash - everything else the operator
just changed reverts to S0. Both requests answered success.

/setup and change_web_ui_password go through the same method.

HOW THIS TEST CAN FAIL: it lets another save run to completion in exactly
that gap - after the read, before the write-back - and then asks whether the
operator's edit is still on disk. If the field update wrote the state from
before it, the edit is gone and the test is red.

A FIRST ATTEMPT AT THIS TEST PROVED NOTHING and is worth recording: it blocked
the field update inside its READ and checked that no other save got through.
That was green before the change too, because save_config takes the same lock -
the other save simply waited. The window is not the read; it is the step
between letting go and picking up again.

COUNTER-CHECK (2026-09-23): red before - "the_operators_edit" was gone from
config.json, and both requests had answered success. The last tests keep the
method working: a normal update writes its field, two updates in a row do not
lose each other, and two threads updating different fields keep both.
"""

import json
import threading
import time

import pytest

from services.config.config_service import ConfigService


@pytest.fixture
def service(tmp_path, monkeypatch):
    """ConfigService is a singleton, so the paths are pointed at tmp_path by
    hand - the same shape the other spec tests of this service use."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    svc = ConfigService()
    monkeypatch.setattr(svc, "config_dir", tmp_path)
    monkeypatch.setattr(svc, "main_config_file", tmp_path / "config.json")
    svc.main_config_file.write_text(json.dumps({"timezone": "Europe/Berlin"}),
                                    encoding="utf-8")
    return svc


def _on_disk(service):
    return json.loads(service.main_config_file.read_text(encoding="utf-8"))


def test_a_save_in_the_gap_is_not_rolled_back(service):
    """THE FINDING: the field update wrote the state from before that save."""
    real_save = service.save_config
    started = []

    def save_config(config):
        # Called for the field update's OWN write-back, i.e. after its read -
        # the exact gap the dedented return opened. The other request is only
        # STARTED here, never waited for: with the lock held across, it cannot
        # finish until this returns, and waiting for it here would be the test
        # deadlocking itself, not the product.
        if not started:
            other = threading.Thread(target=lambda: real_save(
                {"timezone": "Europe/Berlin", "the_operators_edit": True}))
            started.append(other)
            other.start()
            time.sleep(0.3)   # long enough for it to get through, if it can
        return real_save(config)

    service.save_config = save_config
    try:
        service.update_config_fields({"ui_language": "de"})
    finally:
        del service.save_config
    started[0].join(10)

    on_disk = _on_disk(service)
    assert on_disk.get("the_operators_edit") is True, (
        "the operator's whole save was rolled back by a one-field update that "
        f"had read the file before it: {on_disk}")


def test_an_ordinary_field_update_still_writes_its_field(service):
    """Counter-check: the method's own job."""
    result = service.update_config_fields({"ui_language": "de"})

    assert result.success, result.message
    assert _on_disk(service)["ui_language"] == "de"
    assert _on_disk(service)["timezone"] == "Europe/Berlin", "the rest was dropped"


def test_two_updates_in_a_row_do_not_lose_each_other(service):
    """Counter-check: locking must not turn a second call into a deadlock."""
    assert service.update_config_fields({"ui_language": "de"}).success
    assert service.update_config_fields({"timezone": "UTC"}).success

    on_disk = _on_disk(service)
    assert on_disk["ui_language"] == "de"
    assert on_disk["timezone"] == "UTC"


def test_two_threads_updating_different_fields_keep_both(service):
    """The everyday shape of the race, without any blocking."""
    threads = [
        threading.Thread(target=lambda: service.update_config_fields({"ui_language": "de"})),
        threading.Thread(target=lambda: service.update_config_fields({"timezone": "UTC"})),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    on_disk = _on_disk(service)
    assert on_disk.get("ui_language") == "de", on_disk
    assert on_disk.get("timezone") == "UTC", on_disk
