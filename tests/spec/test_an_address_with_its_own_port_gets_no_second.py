# -*- coding: utf-8 -*-
"""An address that carries its own port is not given a second one.

THE FINDING (stage 4 review before v3.1.0, section 09 pass 4 F7): with an
address like "play.example.org:2456" and a value in the separate port field,
the info display showed "play.example.org:2456:2456". The guard against
gluing a port onto an address that has one covered only the game server's
port, not the form's.

THE CONTRACT: an address with its own port is shown as written - whichever
port field is filled in. (The IPv6 and URL forms follow the same rule:
test_the_address_field_takes_ipv6_and_urls.py.)

HOW THIS TEST CAN FAIL: two ports again.

COUNTER-CHECK (2026-09-29): red before the change.
"""

import asyncio


def _shown(custom_ip, custom_port):
    from cogs.info_extras import address_line
    return asyncio.run(address_line({"custom_ip": custom_ip, "custom_port": custom_port}, 2457))


def test_the_own_port_wins():
    text = _shown("play.example.org:2456", "2456")
    assert "`play.example.org:2456`" in text and ":2456:" not in text, text


def test_an_address_without_one_still_gets_the_form_port():
    assert "`play.example.org:2456`" in _shown("play.example.org", "2456")
