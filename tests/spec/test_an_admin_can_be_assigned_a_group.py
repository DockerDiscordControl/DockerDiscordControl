# -*- coding: utf-8 -*-
"""A group can be assigned to an admin, like a container and apart from one.

THE OPERATOR'S RULE, stated again on 2026-09-24 when I got it wrong: a
group's rights and a container's rights are completely separate and condition
each other in NEITHER direction.

I had proposed that an assigned admin may press a group when every member is
theirs. That couples the two again - it makes a group's reachability depend on
container rights - so it is the wrong answer to the right question. The right
one follows from his rule: a group is its own thing, and an admin is assigned
that thing, or is not. Whether the members are theirs one by one does not
enter into it.

WHAT WAS ALREADY CORRECT: admin_service.may_control() compares the name it is
given against the admin's list, literally. Hand it "group:Gameserver" and it
answers for the group, not for its members. Nothing there had to change.

WHAT WAS MISSING was the panel's ability to SAY it. The assignment dialog is
offered the configured containers and nothing else, so an operator could not
put a group in the list - and the save refused an unknown name by design,
which would have refused a hand-written one too. The group that is shown in
Discord, picked in the admin list and acted on like a container was the one
thing that could not be handed to an admin.

SO A GROUP IS OFFERED AND ACCEPTED, and it stays refused for a name that is
neither a container nor a group: a typo in that field does not fail, it
silently means "this admin controls nothing on that one", and nobody would
connect the refusal to a letter (review F5).

HOW THIS TEST CAN FAIL: a dialog that cannot offer a group, a save that
refuses one, or a save that waves any name through.

COUNTER-CHECK (2026-09-24): red before - the choices held containers only and
the validation refused "group:Gameserver" by name.
"""

import json
from types import SimpleNamespace

import pytest
from flask import Flask

AUTH = {"Authorization": "Basic YWRtaW46YWRtaW4="}   # admin:admin


@pytest.fixture
def client(tmp_path, monkeypatch):
    """The admin route on a bare app, with two containers and one group."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir()
    for name in ("alpha", "beta"):
        (containers / f"{name}.json").write_text(json.dumps(
            {"container_name": name, "docker_name": name, "active": True,
             "allowed_actions": ["status"]}), encoding="utf-8")
    (tmp_path / "admins.json").write_text(
        json.dumps({"discord_admin_users": ["111"]}), encoding="utf-8")

    from app import auth as auth_module
    from app.web import routes as web_routes
    from services.config import group_service

    group_service.reset_group_service()
    group_service.get_group_service().save_group(
        "Gameserver", ["alpha", "beta"],
        active=True, allowed_actions=["status", "restart"])

    monkeypatch.setattr(auth_module.auth, "verify_password_callback",
                        lambda user, password: "admin" if user and password else None)
    monkeypatch.setattr(web_routes.auth, "login_required", lambda f: f)
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="admins")
    web_routes.register_routes(app)
    return app.test_client()


def _choices(client):
    return client.get("/api/admin-users", headers=AUTH).get_json()["available_containers"]


def test_the_dialog_offers_the_groups(client):
    """THE GAP: the one thing that could not be handed to an admin."""
    choices = _choices(client)

    assert "group:Gameserver" in choices, choices
    assert "alpha" in choices and "beta" in choices, choices


def test_a_group_is_offered_even_when_its_members_are_not_configured(client, tmp_path):
    """The rule itself: the two do not condition each other. A group whose
    members DDC has no configuration for is still a group that can be given
    away."""
    from services.config.group_service import get_group_service

    get_group_service().save_group("Lonely", ["Nothing DDC knows"],
                                   active=True, allowed_actions=["restart"])

    assert "group:Lonely" in _choices(client)


def test_a_group_can_be_saved_as_an_assignment(client):
    answer = client.post("/api/admin-users", headers=AUTH, json={
        "discord_admin_users": ["111"],
        "admin_containers": {"111": ["group:Gameserver"]},
    })

    assert answer.status_code == 200, answer.get_data(as_text=True)
    assert answer.get_json().get("success") is True


def test_an_invented_name_is_still_refused(client):
    """Counter-check: a typo does not fail, it silently means "nothing", and
    nobody would connect that to a letter (review F5)."""
    answer = client.post("/api/admin-users", headers=AUTH, json={
        "discord_admin_users": ["111"],
        "admin_containers": {"111": ["group:Nope"]},
    })
    body = answer.get_json()

    assert body.get("success") is False, body
    assert "group:Nope" in (body.get("error") or ""), body


def test_the_assignment_decides_for_the_group_alone(client, tmp_path, monkeypatch):
    """What the panel writes is what the bot reads, and it reads it literally:
    the group is allowed, its members are not, and neither follows from the
    other."""
    client.post("/api/admin-users", headers=AUTH, json={
        "discord_admin_users": ["111"],
        "admin_containers": {"111": ["group:Gameserver"]},
    })

    from services.admin import admin_service

    admin_service.reset_admin_service() if hasattr(admin_service, "reset_admin_service") else None
    service = admin_service.get_admin_service()

    assert service.may_control("111", "group:Gameserver") is True
    assert service.may_control("111", "alpha") is False, (
        "being given the group handed over its members as well")


# --- and it has to be readable in the dialog --------------------------------
# The value stored is `group:Gameserver`, because that is what the bot compares.
# What the operator READS must not be that: a checkbox labelled "group:Gameserver"
# among plain container names is the same complaint he made about the Discord
# dropdown, one screen further on.

def test_the_dialog_shows_a_group_as_a_group():
    import re
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "app" / "static" / "js"
              / "config-ui.js").read_text(encoding="utf-8")
    source = re.sub(r"//[^\n]*", "", source)

    assert "adminAssignmentLabel" in source, (
        "nothing turns the stored name into something to read")
    assert "group:" in source, "the dialog does not know the group spelling"


def test_the_label_drops_the_prefix_and_marks_the_group():
    """The rule itself, in node, because that is where it runs."""
    import shutil
    import subprocess
    from pathlib import Path

    import pytest

    root = Path(__file__).resolve().parents[2]
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/admin_assignment.test.js by hand")
    result = subprocess.run([node, str(root / "tests" / "js" / "admin_assignment.test.js")],
                            capture_output=True, text=True, timeout=60)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("ok   - ") == 4, result.stdout
