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
# And where it is actually shown. Both copies of _get_ip_info append the
# separate custom_port field, on two branches each: the custom address and the
# public IP. The public-IP branch is only reached when custom_ip is EMPTY -
# which is how the first version of this repair broke it: the import sat
# inside the custom_ip branch, so the public-IP branch raised NameError for
# every container without a custom address. Caught here before it was
# committed, and these four cases are why the tests stay.
# --------------------------------------------------------------------------

import asyncio

import pytest as _pytest


def _ip_info(view_class, info_config, *, wan_ip=None, monkeypatch=None):
    view = view_class.__new__(view_class)
    if wan_ip is not None:
        import utils.common_helpers as helpers
        monkeypatch.setattr(helpers, "get_wan_ip_async", _async_return(wan_ip))
    return asyncio.run(view._get_ip_info(info_config))


def _async_return(value):
    async def _call(*args, **kwargs):
        return value
    return _call


@_pytest.fixture(params=["control_ui", "status_info_integration"])
def view_class(request):
    import importlib
    module = importlib.import_module(f"cogs.{request.param}")
    return {"control_ui": "InfoButton",
            "status_info_integration": "StatusInfoButton"}[request.param], module


def test_a_shown_custom_address_carries_only_a_real_port(view_class):
    name, module = view_class
    text = _ip_info(getattr(module, name),
                    {"custom_ip": "1.2.3.4", "custom_port": "99999"})

    assert "99999" not in text, (
        f"{module.__name__} shows a port that is not a port: {text!r}"
    )


def test_the_public_ip_is_shown_with_its_port(view_class, monkeypatch):
    """The branch the first version of this repair broke."""
    name, module = view_class
    text = _ip_info(getattr(module, name),
                    {"custom_ip": "", "custom_port": "80"},
                    wan_ip="203.0.113.7", monkeypatch=monkeypatch)

    assert "203.0.113.7:80" in text, text
