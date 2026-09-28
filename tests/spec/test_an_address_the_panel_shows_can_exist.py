# -*- coding: utf-8 -*-
"""An address the panel shows is an address that could exist.

THE FINDING (review D28, pass 2, section 01 F5): `validate_custom_address`
calls itself a check "for security" and lets through addresses that cannot
exist.

    999.999.999.999      -> rejected. The IP pattern matches and the octets
                            are checked.
    999.999.999.999:80   -> ACCEPTED. The IP pattern has no port group, so it
                            does not match; the hostname pattern does, and
                            that one never looks at numbers at all.

The port has the same hole from the other side: the pattern allows
`[0-9]{1,5}`, which counts digits and not values, so `host:99999` and
`host:0` pass although neither is a TCP port.

And the callers never get as far as the question. Both copies of
`_get_ip_info` (control_ui.py and status_info_integration.py - the twins this
helper was extracted from) validate `custom_ip`, and then append `custom_port`
to it with nothing but `.isdigit()`. So the displayed address can carry port
99999 no matter how careful the validation of the host part is. That is why
the rule about ports has to live in one place too, and why both callers use it.

What a member sees: "🔗 Custom Address: 999.999.999.999:80" under a game
server, and a connection that cannot be made. The panel said the address was
fine.
"""

import pytest

from cogs import control_helpers


@pytest.mark.parametrize("address", [
    "999.999.999.999:80",     # the finding
    "256.1.1.1:8080",         # one octet over, with a port
    "1.2.3.4:99999",          # five digits, not a port
    "1.2.3.4:0",              # port 0 is not a port anybody connects to
    "host:99999",
    "host:0",
])
def test_an_impossible_address_is_refused(address):
    assert control_helpers.validate_custom_address(address) is False, (
        f"{address!r} was accepted and will be shown to members as the "
        f"address of this server"
    )


@pytest.mark.parametrize("address", [
    "1.2.3.4",
    "1.2.3.4:80",
    "192.168.1.249:65535",    # the highest port there is
    "192.168.1.249:1",
    "example.com",
    "example.com:443",
    "my-host",
])
def test_a_real_address_still_gets_through(address):
    """The counter-case: refusing everything would satisfy the test above."""
    assert control_helpers.validate_custom_address(address) is True, (
        f"{address!r} is a perfectly ordinary address and was refused"
    )


@pytest.mark.parametrize("address", [
    "999.999.999.999",        # already refused before this repair
    "",
    "a" * 256,
    "..example.com",
    "example.com.",
])
def test_what_was_already_refused_stays_refused(address):
    """A pin on the ground that was already held.

    "1.2.3.4.5" was in this list on the first run and turned the announcement
    wrong - 15 red announced, 16 measured. The code was right and the test was
    not: five dotted numbers are a perfectly legal DNS name, and nothing here
    promises to refuse one. What the function does promise is that something
    shaped like four dotted numbers really is an address, with or without a
    port attached.
    """
    assert control_helpers.validate_custom_address(address) is False


def _port_rule():
    """The one place that says which ports are real - named, not guessed."""
    check = getattr(control_helpers, "validate_custom_port", None)
    assert check is not None, (
        "there is no single place that decides whether a port is a port, so "
        "both copies of _get_ip_info go on appending whatever passes "
        "str.isdigit() to the address they show"
    )
    return check


@pytest.mark.parametrize("port,expected", [
    ("80", True),
    ("1", True),
    ("65535", True),
    ("65536", False),
    ("99999", False),
    ("0", False),
    ("", False),
    ("http", False),
    ("-1", False),
])
def test_the_port_rule_counts_values_and_not_digits(port, expected):
    assert _port_rule()(port) is expected, (
        f"port {port!r} was judged {not expected} - the check counts digits "
        f"where it should weigh the number"
    )


# --------------------------------------------------------------------------
# And where it is actually shown. The two copies of _get_ip_info - plus the
# overview dropdown's own, which validated nothing - became ONE function in
# v3.1.0, cogs/info_extras.address_line, used by every path. It appends the
# separate custom_port field, on two branches: the custom address and the
# public IP. The public-IP branch is only reached when custom_ip is EMPTY -
# which is how the first version of this repair broke it: the import sat
# inside the custom_ip branch, so the public-IP branch raised NameError for
# every container without a custom address. Caught here before it was
# committed, and these cases are why the tests stay.
#
# Without a port of its own, the address takes the port the game server names
# (operator, 2026-09-28) - but never glued onto an address carrying its own.
# COUNTER-CHECK (2026-09-28): without the fallback the completing case went
# red; with the fallback glued onto any address, the own-port case did.
# --------------------------------------------------------------------------

import asyncio


def _address(info_config, *, game_port=None, wan_ip=None, monkeypatch=None):
    from cogs.info_extras import address_line
    if wan_ip is not None:
        import utils.common_helpers as helpers

        async def _wan(*args, **kwargs):
            return wan_ip
        monkeypatch.setattr(helpers, "get_wan_ip_async", _wan)
    return asyncio.run(address_line(info_config, game_port))


def test_a_shown_custom_address_carries_only_a_real_port():
    text = _address({"custom_ip": "1.2.3.4", "custom_port": "99999"})
    assert "99999" not in text, f"a port that is not a port is shown: {text!r}"


def test_an_impossible_custom_address_is_not_shown():
    text = _address({"custom_ip": "999.999.999.999:80", "custom_port": ""})
    assert "999" not in text


def test_the_public_ip_is_shown_with_its_port(monkeypatch):
    """The branch the first version of this repair broke."""
    text = _address({"custom_ip": "", "custom_port": "80"}, wan_ip="203.0.113.7", monkeypatch=monkeypatch)
    assert "203.0.113.7:80" in text, text


def test_the_game_port_completes_an_address_without_one(monkeypatch):
    text = _address({"custom_ip": "", "custom_port": ""}, game_port=2456,
                    wan_ip="185.137.173.157", monkeypatch=monkeypatch)
    assert "`185.137.173.157:2456`" in text, text
    assert "1.2.3.4:27015" in _address({"custom_ip": "1.2.3.4", "custom_port": "27015"}, game_port=2456), \
        "the port set by the operator lost to the game's"


def test_the_game_port_is_not_glued_onto_an_address_with_its_own():
    text = _address({"custom_ip": "play.example.com:2500", "custom_port": ""}, game_port=2456)
    assert "play.example.com:2500`" in text and "2456" not in text, text
