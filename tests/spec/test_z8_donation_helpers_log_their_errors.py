# -*- coding: utf-8 -*-
# @covers Z8
"""Z8 - a service error in the donation helpers leaves a trace.

THE FINDING (stage 4 review pass 1, section 17 F2 and F3, re-checked
2026-09-19): ``validate_donation_key``, ``is_donations_disabled``
(services/donation/donation_utils.py) and ``set_donation_disable_key``
(services/donation/donation_config.py) turned every error of the
configuration service into a quiet ``False`` - no log line at all, not even
DEBUG. An admin whose correct premium key hits a transient error is told the
key is invalid, and a key that could not be saved reports a plain failure;
nothing says why, anywhere.

The return values stay as they are (a failure must not open donations or
accept a key) - what is missing is the trace.
"""

import logging

import pytest

from services.donation import donation_config, donation_utils


class _Boom:
    def __getattr__(self, name):
        def explode(*_a, **_k):
            raise RuntimeError("configuration service unavailable")
        return explode


@pytest.fixture
def broken_config_service(monkeypatch):
    monkeypatch.setattr("services.config.config_service.get_config_service", lambda: _Boom())


def _errors(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]


def test_validate_donation_key_says_why(broken_config_service, caplog):
    with caplog.at_level(logging.DEBUG):
        assert donation_utils.validate_donation_key("some-key") is False
    assert _errors(caplog), "a valid key was called invalid and nothing was logged"


def test_is_donations_disabled_says_why(broken_config_service, caplog):
    with caplog.at_level(logging.DEBUG):
        assert donation_utils.is_donations_disabled() is False
    assert _errors(caplog), "the answer fell back to 'not disabled' with no trace"


def test_set_donation_disable_key_says_why(broken_config_service, caplog):
    with caplog.at_level(logging.DEBUG):
        assert donation_config.set_donation_disable_key("some-key") is False
    assert _errors(caplog), "the key was not saved and nothing was logged"
