# -*- coding: utf-8 -*-
"""The group editor offers the containers DDC actually manages.

THE FINDING (independent review, 2026-09-23): the multi-select was filled from
the LIVE containers on the host, while a group resolves its members against
the containers configured in DDC (config/containers/*.json). So an operator
could pick `nextcloud` - running on the host, never added to DDC - press save,
and the very next line of the list read "Not found any more: nextcloud". A
task on that group would then fail on every single run.

The list offers what DDC steers. What is running on the host but not
configured belongs in the container selection above, not here.

COUNTER-CHECK (2026-09-23): red before - the template read all_containers,
which is docker_data['live_containers'].
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SECTION = (ROOT / "app" / "templates" / "_container_groups.html").read_text(encoding="utf-8")


def test_the_editor_does_not_offer_every_container_on_the_host():
    assert "all_containers" not in SECTION, (
        "the editor offers containers DDC cannot steer; a group made from them "
        "is broken the moment it is saved")


def test_it_offers_the_configured_ones():
    assert "configured_servers" in SECTION or "active_container_names" in SECTION, (
        "the editor offers nothing at all")


def test_the_page_hands_that_list_to_the_template():
    page = (ROOT / "services" / "web" / "configuration_page_service.py").read_text(encoding="utf-8")

    assert "'configured_servers': configured_servers" in page


def test_the_list_really_renders_the_containers():
    """A template variable that is not in the context renders as nothing.

    COUNTER-CHECK: with `configured_servers` renamed in the template, the page
    shows an empty picker and nobody can put a container into a group -
    silently, because Jinja treats an unknown name as undefined.

    REVISITED 2026-09-23: this counted <option> elements. The picker is a
    checkbox list now - 26 containers behind Ctrl-click was one stray click
    away from losing the whole selection - so it counts the boxes instead. What
    it checks is unchanged: each container once, and the alias key not twice.
    """
    from flask import Flask, render_template

    app = Flask(__name__, template_folder=str(ROOT / "app" / "templates"))
    app.jinja_env.globals["_t"] = lambda key, **kwargs: key

    servers = {
        "Valheim": {"docker_name": "Valheim", "name": "Valheim Server"},
        "Valheim Server": {"docker_name": "Valheim", "name": "Valheim Server"},  # alias key
        "plex": {"docker_name": "plex", "name": "plex"},
    }
    with app.test_request_context("/"):
        html = render_template("_container_groups.html", configured_servers=servers)

    assert 'value="Valheim"' in html, "a configured container is not offered"
    assert 'value="plex"' in html
    boxes = html.count('class="form-check-input group-container-box"')
    assert boxes == 2, f"the alias key was rendered as a second container: {boxes} boxes"
