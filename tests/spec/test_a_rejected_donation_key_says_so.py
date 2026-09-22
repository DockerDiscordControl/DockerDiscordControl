# -*- coding: utf-8 -*-
"""A donation key the validator rejects is reported, not dropped in silence.

THE FINDING (review C53, section 12 F3): ``_process_donation_key`` asks
``validate_donation_key`` and, when the answer is no, does nothing at all -
it does not store the key, does not log, and does not tell anybody. The same
goes for the case where the validator cannot even be imported.
``process_config_form`` meanwhile saves the rest of the configuration and
answers "Configuration saved". The operator typed a key, was told everything
went through, and the key was never stored.
"""

from unittest.mock import MagicMock

import pytest

from services.config.config_form_parser_service import ConfigFormParserService

KEY = "DDC-TEST-KEY-0001"


@pytest.fixture
def config_service():
    service = MagicMock()
    service.save_config.return_value = MagicMock(success=True, message="Configuration saved")
    return service


def _run(monkeypatch, config_service, *, key, valid=True, importable=True,
         current=None):
    import sys

    import services.donation.donation_utils as donation_utils

    if importable:
        monkeypatch.setattr(donation_utils, "validate_donation_key", lambda k: valid)
    else:
        # A None entry in sys.modules is what an import of a missing module hits.
        monkeypatch.setitem(sys.modules, "services.donation.donation_utils", None)

    return ConfigFormParserService.process_config_form(
        {"donation_disable_key": key}, dict(current or {}), config_service)


def test_a_rejected_key_is_named_in_the_answer(monkeypatch, config_service):
    _config, _success, message = _run(monkeypatch, config_service, key=KEY, valid=False)

    assert "donation" in message.lower(), (
        f"the key was rejected and thrown away, and the panel only says: {message!r}"
    )


def test_a_validator_that_cannot_run_is_named_in_the_answer(monkeypatch, config_service):
    _config, _success, message = _run(monkeypatch, config_service, key=KEY,
                                      importable=False)

    assert "donation" in message.lower(), (
        f"the key could not be checked at all, and the panel only says: {message!r}"
    )


def test_a_rejected_key_does_not_overwrite_the_stored_one(monkeypatch, config_service):
    """The refusal must cost the operator nothing that was already working."""
    config, _success, _message = _run(monkeypatch, config_service, key=KEY, valid=False,
                                      current={"donation_disable_key": "OLD-KEY"})

    assert config["donation_disable_key"] == "OLD-KEY"


def test_an_accepted_key_is_stored_without_a_warning(monkeypatch, config_service):
    """Counter-check: a message that always mentions donations would pass above."""
    config, success, message = _run(monkeypatch, config_service, key=KEY, valid=True)

    assert config["donation_disable_key"] == KEY
    assert success
    assert "donation" not in message.lower(), message


def test_an_emptied_field_removes_the_key_without_a_warning(monkeypatch, config_service):
    """Counter-check: clearing the field is a wish, not a rejected key."""
    config, _success, message = _run(monkeypatch, config_service, key="   ", valid=True,
                                     current={"donation_disable_key": "OLD-KEY"})

    assert "donation_disable_key" not in config
    assert "donation" not in message.lower(), message
