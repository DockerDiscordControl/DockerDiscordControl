# -*- coding: utf-8 -*-
"""The custom address field takes IPv6 addresses and URLs, as its label says.

THE FINDING (stage 4 review before v3.1.0, section 01 pass 3 F2): the field
is labelled "Custom IP/URL Override", but validate_custom_address split at
the last ':' as a port separator, so every IPv6 address ('2001:db8::5') and
every URL with a scheme ('https://example.com') was refused - the panel
saved it, and Discord showed "[Invalid Format]" in its place.

THE OPERATOR (2026-09-29): accept IPv6 and URLs with a scheme.

THE CONTRACT: a bare IPv6 address, one in brackets with a port, and an
http(s) URL with a valid host (and optional port and path) are shown. A
port from the info form is joined correctly: in brackets behind an IPv6
address, never onto a URL. What was refused stays refused - a scheme other
than http(s), a URL with an impossible port, and characters that would
break the code span in Discord.

HOW THIS TEST CAN FAIL: IPv6 or URLs are refused again; a port is glued
onto a bare IPv6 address (which makes it another address) or into a URL;
or the check opens up to anything.

COUNTER-CHECK (2026-09-29): the accepting and joining cases red before the
change; the refused cases green before and after.
"""

import asyncio

import pytest

from cogs.control_helpers import validate_custom_address


@pytest.mark.parametrize("address", [
    "2001:db8::5",
    "::1",
    "[2001:db8::5]:2456",
    "https://example.com",
    "http://play.example.com:8080",
    "https://example.com/servers/valheim?id=3",
    "https://[2001:db8::5]:443/",
])
def test_ipv6_and_urls_are_accepted(address):
    assert validate_custom_address(address), f"{address!r} was refused"


@pytest.mark.parametrize("address", [
    "ftp://example.com",
    "javascript://example.com",
    "https://example.com:99999",
    "https://",
    "https://exa mple.com",
    "https://example.com/`code`",
    "[2001:db8::5]:0",
    "2001:db8::zz",
])
def test_what_is_no_address_stays_refused(address):
    assert not validate_custom_address(address), f"{address!r} was accepted"


def _shown(custom_ip, custom_port="", game_port=None):
    from cogs.info_extras import address_line
    return asyncio.run(address_line({"custom_ip": custom_ip, "custom_port": custom_port}, game_port))


def test_a_port_behind_ipv6_goes_in_brackets():
    assert "`[2001:db8::5]:2456`" in _shown("2001:db8::5", "2456")
    assert "`[2001:db8::5]:2456`" in _shown("2001:db8::5", game_port=2456)


def test_a_url_keeps_its_own_form():
    assert "`https://example.com`" in _shown("https://example.com", "2456", game_port=2457)
