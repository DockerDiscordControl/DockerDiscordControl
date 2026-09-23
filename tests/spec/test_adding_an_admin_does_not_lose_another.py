# -*- coding: utf-8 -*-
"""Adding an admin in Discord does not drop one the panel just saved.

THE FINDING (noted but unverified by the independent review of the cog
modules, 2026-09-23; verified here): admins.json has two writers and no lock.

    cogs/donation_ui.py   AddAdminModal: get_admin_data(force_refresh=True)
                          -> append -> save_admin_data(...)
    app/web/routes.py     the panel's admin editor: save_admin_data(...)

save_admin_data writes atomically - temp file plus os.replace, so the file is
never truncated - and REPLACES THE WHOLE DOCUMENT. The write being atomic says
nothing about the cycle around it, which is what utils/atomic_io spells out in
its own docstring and what auto_actions.json was fixed for earlier today.

    /addadmin reads the list          (A, B)
    the operator saves the panel      (A, B, C)
    /addadmin appends and writes      (A, B, D)   -> C is gone

Both sides answered success. The panel says the admin was saved, Discord says
the admin was added, and one of them is not in the file. Nothing is logged,
because nothing went wrong as far as either writer can see.

WHAT CHANGES: the read and the write become ONE step. AdminService grows
add_admin_user(), which reads, checks, appends and writes while holding the
file lock, and the modal uses it instead of doing the cycle itself.

HOW THIS TEST CAN FAIL: it holds the Discord side inside its read and asks
whether a panel save can finish in that window. If it can, the list the Discord
side writes was built from something that is already out of date, and the test
is red.

A FIRST VERSION OF THIS TEST ASKED THE WRONG THING - that BOTH admins survive.
They need not: a panel save replaces the whole list deliberately, so whichever
cycle finishes last is what stands. That is last-writer-wins, not a loss.

COUNTER-CHECK (2026-09-23): red before - the panel save went straight through. The other
tests keep the everyday behaviour: an admin is added, a duplicate is refused,
and the notes survive.
"""

import json
import threading

import pytest

from services.admin.admin_service import AdminService


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    import services.admin.admin_service as module

    monkeypatch.setattr(module, "_admins_file", lambda: tmp_path / "admins.json")
    (tmp_path / "admins.json").write_text(json.dumps({
        "discord_admin_users": ["111"],
        "admin_notes": {"111": "the first one"},
        "admin_containers": {},
    }), encoding="utf-8")
    instance = AdminService()
    return instance, tmp_path / "admins.json"


def _on_disk(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_a_panel_save_cannot_land_between_the_read_and_the_write(service):
    """THE FINDING: it could, and the Discord side then wrote a stale list.

    Not "both admins survive": a panel save replaces the whole list on purpose,
    so whichever cycle finishes last is what stands - that is last-writer-wins,
    not a loss. The damage was a panel save landing INSIDE the Discord cycle, so
    the list written had never seen it. That is what this pins.
    """
    admin_service, path = service
    inside = threading.Event()
    may_finish = threading.Event()
    panel_got_through = threading.Event()
    real_load = admin_service.get_admin_data

    def slow_load(*args, **kwargs):
        data = real_load(*args, **kwargs)
        inside.set()
        may_finish.wait(5)
        return data

    admin_service.get_admin_data = slow_load
    discord_side = threading.Thread(
        target=lambda: admin_service.add_admin_user("222", "from discord"))
    discord_side.start()
    assert inside.wait(5), "the Discord side never reached its read"

    def panel_save():
        admin_service.get_admin_data = real_load
        admin_service.save_admin_data(["111", "333"], {"111": "the first one",
                                                       "333": "from the panel"})
        panel_got_through.set()

    panel = threading.Thread(target=panel_save)
    panel.start()
    slipped_in = panel_got_through.wait(1.5)
    may_finish.set()
    discord_side.join(10)
    panel.join(10)

    assert not slipped_in, (
        "a panel save completed while the Discord side was between its read "
        "and its write - the list it then wrote had never seen that save")


def test_an_admin_is_added(service):
    """Counter-check: the method's own job."""
    admin_service, path = service

    assert admin_service.add_admin_user("222", "a note") is True
    assert _on_disk(path)["discord_admin_users"] == ["111", "222"]
    assert _on_disk(path)["admin_notes"]["222"] == "a note"


def test_a_duplicate_is_refused(service):
    """Counter-check: the check has to stay inside the locked step."""
    admin_service, path = service

    assert admin_service.add_admin_user("111", "again") is False
    assert _on_disk(path)["discord_admin_users"] == ["111"]


def test_the_existing_notes_survive(service):
    """Counter-check: the whole document is replaced, so nothing may fall out."""
    admin_service, path = service

    admin_service.add_admin_user("222", "second")

    assert _on_disk(path)["admin_notes"]["111"] == "the first one"
