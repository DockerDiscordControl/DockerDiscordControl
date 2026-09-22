# -*- coding: utf-8 -*-
"""The public mech-display endpoint tells nobody where the server keeps files.

THE FINDING (review D8, pass 2, section 32 F4): `/api/mech/display/info`
carries no `@auth.login_required` - and that is deliberate, because its
sibling `/api/mech/display/<level>/<type>` serves the pre-rendered images
straight to Discord, which fetches them without credentials. What is not
deliberate is the payload: it included

    'cache_directory': str(display_cache_service.cache_dir)

the absolute filesystem path of the server's cache directory, handed to any
caller on the open internet. Nothing in the panel reads that field; nothing
in the project reads it at all.

The route stays public, the path goes. Adding a login here would have been
the wrong repair - it would break the pairing with the image route without
removing what was actually leaking.
"""

import re
from types import SimpleNamespace

import pytest
from flask import Flask

from app.blueprints.main_routes import main_bp

LOOKS_LIKE_A_PATH = re.compile(r"(^|[\"' ])/(app|mnt|home|Users|var|tmp)/")


@pytest.fixture
def client(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cached_displays"
    cache_dir.mkdir()
    (cache_dir / "mech_5_shadow.webp").write_bytes(b"not really a webp")

    monkeypatch.setattr(
        "services.mech.mech_display_cache_service.get_mech_display_cache_service",
        lambda: SimpleNamespace(cache_dir=cache_dir))

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-d8"
    app.register_blueprint(main_bp)
    return app.test_client()


def test_the_answer_carries_no_server_path(client):
    response = client.get("/api/mech/display/info")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "cache_directory" not in body, (
        "an unauthenticated caller is told where the server keeps its files"
    )
    assert not LOOKS_LIKE_A_PATH.search(body), body[:200]


def test_what_the_endpoint_is_for_still_works(client):
    """Counter-check: removing the leak must not empty the answer."""
    payload = client.get("/api/mech/display/info").get_json()

    assert payload["success"] is True
    assert payload["available_levels"] == list(range(1, 12))
    assert payload["total_cached"] == 1
    assert payload["cached_images"]["5"]["shadow"]["available"] is True


def test_the_endpoint_stays_public(client):
    """Counter-check, and a deliberate decision: Discord fetches the images
    with no credentials, so this pair must not start demanding a login."""
    assert client.get("/api/mech/display/info").status_code == 200
