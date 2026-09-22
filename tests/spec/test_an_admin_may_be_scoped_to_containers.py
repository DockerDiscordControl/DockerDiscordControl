# -*- coding: utf-8 -*-
"""An admin may be tied to certain containers, and the default is all of them.

THE REQUEST (operator, 2026-09-21): today there are two states. Whoever may
write in a control channel may control every configured container (SPEC.md
B1), and whoever is on the global admin list may do the same in a status
channel, where channel membership alone permits nothing (B2). What is missing
is the middle: in a status channel, admin X may control only containers XYZ.

WHICH RULE THIS REFINES, because the distinction decides whether the change
is allowed at all: **B1 is untouched.** B1 says authorization follows the
channel and explicitly forbids "fixing" it with user checks - and that governs
the CHANNEL branch. B2 is already a user check; this makes it finer. The
control channel keeps working exactly as before, which also means the limit
only bites for someone who cannot write in a control channel anyway.

THE DEFAULT IS NOT NEGOTIABLE: an admin with no assignment keeps every
container. Anything else means an update silently strips every existing admin
of their rights - the same trap `_is_discord_created` in the scheduler carries
a comment about. An EMPTY list is different and deliberate: it says "this
admin may control nothing", and the panel that writes it has to show that.

And a permission that cannot be read is not a permission granted: an
unreadable admins.json refuses, it does not wave everybody through.
"""

import json
import os

import pytest

from services.admin.admin_service import AdminService

SCOPED = "756085333619114064"       # may control valheim only
UNSCOPED = "766595606574530581"     # no entry at all -> everything
NOTHING = "319910077043703820"      # an explicit empty list
STRANGER = "111111111111111111"     # not an admin


def _write(path, containers):
    data = {
        "discord_admin_users": [SCOPED, UNSCOPED, NOTHING],
        "admin_notes": {SCOPED: "Luigi", UNSCOPED: "Max :)"},
    }
    if containers is not None:
        data["admin_containers"] = containers
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    admins = tmp_path / "admins.json"
    _write(admins, {SCOPED: ["valheim"], NOTHING: []})
    monkeypatch.setattr("services.admin.admin_service._admins_file", lambda: admins)
    return AdminService(), admins


def test_an_admin_without_an_assignment_keeps_every_container(service):
    """The upgrade default. Getting this wrong locks out every existing admin."""
    admin_service, _ = service

    assert admin_service.may_control(UNSCOPED, "valheim") is True
    assert admin_service.may_control(UNSCOPED, "nginx") is True
    assert admin_service.get_admin_containers(UNSCOPED) is None, (
        "None means 'all containers' - an empty list would mean 'none'"
    )


@pytest.mark.parametrize("container,allowed", [("valheim", True), ("nginx", False)])
def test_an_assigned_admin_controls_only_what_was_assigned(service, container, allowed):
    admin_service, _ = service

    assert admin_service.may_control(SCOPED, container) is allowed


def test_an_empty_assignment_means_no_container(service):
    """Deliberate and different from 'no entry'. The panel must show it as such."""
    admin_service, _ = service

    assert admin_service.get_admin_containers(NOTHING) == []
    assert admin_service.may_control(NOTHING, "valheim") is False


def test_somebody_who_is_not_an_admin_controls_nothing(service):
    """The counter-case: the assignment is a narrowing, never a grant."""
    admin_service, _ = service

    assert admin_service.may_control(STRANGER, "valheim") is False
    assert admin_service.get_admin_containers(STRANGER) == []


def test_an_unreadable_list_refuses(service, monkeypatch):
    """A permission that cannot be read is not a permission granted."""
    admin_service, admins = service
    admins.write_text("{ this is not json", encoding="utf-8")
    admin_service.clear_cache()

    assert admin_service.may_control(UNSCOPED, "valheim") is False


def test_saving_the_admins_does_not_lose_the_assignment(service):
    """The trap in the writer: save_admin_data knew two keys and would drop the third."""
    admin_service, admins = service

    assert admin_service.save_admin_data([SCOPED, UNSCOPED], {SCOPED: "Luigi"}) is True

    stored = json.loads(admins.read_text(encoding="utf-8"))
    assert stored.get("admin_containers", {}).get(SCOPED) == ["valheim"], (
        f"the container assignment was dropped by a save: {stored}"
    )


def test_an_assignment_can_be_written(service):
    """The panel needs a way in - otherwise the rule has no author."""
    admin_service, admins = service

    assert admin_service.save_admin_data(
        [SCOPED, UNSCOPED], {SCOPED: "Luigi"},
        admin_containers={SCOPED: ["valheim", "minecraft"]}) is True
    admin_service.clear_cache()

    assert admin_service.may_control(SCOPED, "minecraft") is True
