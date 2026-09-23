# -*- coding: utf-8 -*-
"""The panel offers a way to log out, and it is not a link.

THE GAP, found while verifying the form login on the running container
(2026-09-23): /logout works - it clears the session and sends a form user back
to the form - and nothing in the panel points at it. A way out nobody can
reach is the same as no way out, and it matters more now than it did under
HTTP Basic: with a form login, logging out is the only thing that ends a
session before its seven days are up.

WHY IT IS A FORM AND NOT A LINK: logging out changes state. A plain <a
href="/logout"> is a GET, and a GET that changes state is fetched by anything
that walks links - a browser prefetch, a link checker, an accessibility scan.
Flask-WTF's CSRFProtect validates POST and the other state-changing methods,
not GET, so a link would also carry no token. The control posts, with the
token the page already has.

/logout still accepts GET as well: that is the entry a browser holding HTTP
Basic credentials needs, because for it the answer is a 401 with a fresh realm
rather than a redirect, and it must be reachable by typing the address. The
panel's own control does not use it.

HOW THIS TEST CAN FAIL: it reads the navigation and asks for a control that
points at /logout by POST and carries a CSRF token. A link, or a form without
the token, is red.

COUNTER-CHECK (2026-09-23): red before - the navigation had eleven dots and
none of them was a way out.
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NAV = ROOT / "app" / "templates" / "base.html"
KEYS = ("web.nav.logout",)


def test_the_navigation_offers_a_way_out():
    """THE GAP: the route existed and nothing pointed at it."""
    nav = NAV.read_text(encoding="utf-8")

    assert "/logout" in nav or "login.logout" in nav, (
        "the panel has no way out - the route is reachable only by typing it")


def test_it_posts_rather_than_linking():
    """A GET that changes state is fetched by anything that walks links."""
    nav = NAV.read_text(encoding="utf-8")
    position = nav.index("logout")
    block = nav[max(0, position - 600):position + 600]

    assert 'method="POST"' in block or "method='POST'" in block, (
        "logging out is a link, so a prefetch or a link checker can end the "
        "session by reading the page")
    assert 'href="/logout"' not in nav, "there is still a plain link to /logout"


def test_it_carries_the_security_token():
    """Counter-check: CSRFProtect covers POST, so a form without the token
    would be refused - a way out that always fails is worse than none."""
    nav = NAV.read_text(encoding="utf-8")
    position = nav.index("logout")
    block = nav[max(0, position - 600):position + 600]

    assert "csrf_token()" in block, "the logout form carries no security token"


def test_the_route_still_takes_get_for_a_basic_browser():
    """The other caller: a browser holding HTTP Basic credentials gets a 401
    with a fresh realm, not a redirect, and has to be able to ask for it by
    typing the address."""
    import ast

    tree = ast.parse((ROOT / "app" / "blueprints" / "login_routes.py").read_text(encoding="utf-8"))
    methods = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "logout":
            for decorator in node.decorator_list:
                for keyword in getattr(decorator, "keywords", []):
                    if keyword.arg == "methods":
                        methods = [e.value for e in keyword.value.elts]

    assert methods is not None, "the logout route has no methods= at all"
    assert set(methods) == {"GET", "POST"}, methods


@pytest.mark.parametrize("language", ["en", "de"])
def test_the_text_exists_in_the_catalogue(language):
    catalogue = json.loads((ROOT / "locales" / f"{language}.json").read_text(encoding="utf-8"))

    missing = [key for key in KEYS if not catalogue.get(key)]

    assert missing == [], f"{language}.json has no text for {missing}"


def test_every_locale_has_the_text():
    locales = [p for p in (ROOT / "locales").glob("*.json") if p.name != "meta.json"]

    assert len(locales) >= 40
    for path in locales:
        catalogue = json.loads(path.read_text(encoding="utf-8"))
        assert all(key in catalogue for key in KEYS), path.name
