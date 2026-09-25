# -*- coding: utf-8 -*-
"""The recovery codes can be taken away from the one screen that shows them.

THE OPERATOR, 2026-09-25: "we have to offer the 2FA recovery codes as a
download - I do not see them at all."

HE WAS RIGHT TWICE. He does not see them because 2FA is off on his panel, and
the codes exist for exactly one screen: ``confirm_setup`` returns them once
and the store keeps only ``sha256`` of each. There is no page that shows them
again, by design - so the screen after switching 2FA on is the only chance to
keep them, and until now the only way to keep them was to select the text.

That makes the download not a convenience but the way the feature works at
all. A lost phone with no codes means the break-glass route on the host
(services/web/two_factor_service.py) or nothing.

TXT, NOT PDF, and that was his call: "pdf only if it does not bloat DDC, txt
is enough". Writing a PDF needs a library the image does not carry, for a
file with ten lines of five-plus-five characters in it.

HOW THE ROUTE KNOWS WHICH CODES TO SEND, which is the part worth reading. It
cannot: the store holds hashes. So the page posts the codes it is already
showing, and the route answers only with those whose hash the store knows -
anything else is refused whole. That is what keeps it from being a machine
that turns any text into a file with the panel's name on it.

NOTHING NEW IS STORED. Keeping the codes in the session was the other way,
and Flask signs the session into a COOKIE, which would put ten recovery codes
in the browser's jar to be read at leisure.

HOW THIS TEST CAN FAIL: no way to keep the codes off that screen, a download
that answers with something the store does not know, or one that spends a
code.

COUNTER-CHECK (2026-09-25): red before - no route, no button.
"""

import base64

import pytest
from werkzeug.security import generate_password_hash

PASSWORD = "correct horse"
SECURE = "https://localhost"


def _basic(user="admin", password=PASSWORD):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def panel(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_ENABLE_BACKGROUND_REFRESH", "false")
    monkeypatch.setenv("DDC_ENABLE_MECH_DECAY", "false")
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("DDC_TLS_MODE", raising=False)

    import app.auth as auth_module
    from app.auth import (auth_limiter, clear_credential_cache, setup_limiter,
                          two_factor_limiter)
    from app.web import create_app
    from services.web.two_factor_service import TwoFactorStore

    # HASHED ONCE, and that matters: generate_password_hash salts afresh every
    # call, the session's second-factor marker is bound to the hash, and a
    # lambda that hashed on each call made the binding differ on every
    # request - so every page after confirm was sent back to verify and the
    # download looked broken when it was the harness.
    hashed = generate_password_hash(PASSWORD)
    monkeypatch.setattr(auth_module, "load_config",
                        lambda: {"web_ui_user": "admin", "web_ui_password_hash": hashed})
    for limiter in (auth_limiter, setup_limiter, two_factor_limiter):
        limiter.ip_dict.clear()
    clear_credential_cache()

    yield create_app({"TESTING": True, "WTF_CSRF_ENABLED": False}), \
        TwoFactorStore(tmp_path / "two_factor.json")

    for limiter in (auth_limiter, setup_limiter, two_factor_limiter):
        limiter.ip_dict.clear()


def _through_the_panel(panel):
    """(client, codes) with 2FA switched on the way the operator switches it.

    THROUGH THE APP, not through the store. Enabling it behind the panel's
    back leaves the session unverified, so every following request is sent to
    the verify page - which is what the first version of this measured, and
    it told me nothing about the download. The codes are what the CONFIRM
    screen showed, because that screen is the whole subject here.
    """
    import re
    import time

    from services.web.two_factor_service import secret_bytes, totp

    app, store = panel
    client = app.test_client()
    client.post("/security/2fa/setup", headers=_basic(), base_url=SECURE)
    page = client.post("/security/2fa/confirm", headers=_basic(), base_url=SECURE,
                       data={"code": totp(secret_bytes(store.pending_or_active_secret()),
                                          time.time())}).get_data(as_text=True)
    codes = re.findall(r"\b[0-9a-f]{5}-[0-9a-f]{5}\b", page)

    assert len(codes) >= 5, f"the confirm screen showed no codes: {page[:300]}"

    return client, codes


def test_the_screen_that_shows_them_offers_to_keep_them(panel):
    """THE FINDING: the one screen that has the codes let you select them or
    lose them."""
    client, codes = _through_the_panel(panel)

    kept = client.post("/security/2fa/codes.txt", headers=_basic(), base_url=SECURE,
                       data={"codes": "\n".join(codes)})

    assert kept.status_code == 200, kept.status_code
    assert kept.headers["Content-Type"].startswith("text/plain"), kept.headers["Content-Type"]
    assert "attachment" in kept.headers.get("Content-Disposition", ""), kept.headers


def test_the_screen_offers_the_download_itself(panel):
    """A route nothing links to is not an offer. The button has to be on the
    screen that holds the codes, because there is no second chance."""
    import re

    app, store = panel
    client = app.test_client()
    client.post("/security/2fa/setup", headers=_basic(), base_url=SECURE)

    import time

    from services.web.two_factor_service import secret_bytes, totp

    page = client.post("/security/2fa/confirm", headers=_basic(), base_url=SECURE,
                       data={"code": totp(secret_bytes(store.pending_or_active_secret()),
                                          time.time())}).get_data(as_text=True)

    assert "codes.txt" in page, "the recovery screen does not offer the download"
    assert re.search(r'<form[^>]*codes\.txt', page), page[page.index("codes.txt") - 300:][:400]


def test_the_file_holds_every_code_and_nothing_else(panel):
    """What is kept has to be what was shown, or it is worse than nothing."""
    client, codes = _through_the_panel(panel)

    body = client.post("/security/2fa/codes.txt", headers=_basic(), base_url=SECURE,
                       data={"codes": "\n".join(codes)}).get_data(as_text=True)

    for code in codes:
        assert code in body, f"{code} is missing from the file"


def test_it_will_not_turn_any_text_into_a_file(panel):
    """THE REASON THE ROUTE VALIDATES. The page posts back what it is
    showing, so without a check this would answer with whatever it was
    handed, under the panel's name."""
    client, _codes = _through_the_panel(panel)

    answer = client.post("/security/2fa/codes.txt", headers=_basic(), base_url=SECURE,
                         data={"codes": "not-a-code\nalso-not-one"})

    assert answer.status_code == 400, answer.status_code
    assert "not-a-code" not in answer.get_data(as_text=True)


def test_downloading_does_not_spend_a_code(panel):
    """The opposite mistake: the store spends a recovery code when it is
    USED. Keeping a copy is not using one, and a download that consumed them
    would hand over ten codes that no longer work."""
    _app, store = panel
    client, codes = _through_the_panel(panel)
    before = store.remaining_recovery_codes()

    client.post("/security/2fa/codes.txt", headers=_basic(), base_url=SECURE,
                data={"codes": "\n".join(codes)})

    assert store.remaining_recovery_codes() == before, "the download spent codes"


def test_nobody_else_may_ask_for_them(panel):
    """They are the way past the second factor, so the route is behind the
    same login as everything else."""
    app, _store = panel
    _client, codes = _through_the_panel(panel)

    answer = app.test_client().post("/security/2fa/codes.txt", base_url=SECURE,
                                    data={"codes": "\n".join(codes)})

    assert answer.status_code in (401, 302), answer.status_code


def test_the_codes_never_go_into_the_session():
    """The other way of holding them between two requests. Flask signs the
    session into a cookie, so this would put ten recovery codes in the
    browser's jar."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "app" / "blueprints"
              / "two_factor_routes.py").read_text(encoding="utf-8")
    for line in source.splitlines():
        if "session[" in line and "=" in line and "#" not in line.split("session[")[0]:
            assert "code" not in line.lower(), f"a code is put into the session: {line.strip()}"
