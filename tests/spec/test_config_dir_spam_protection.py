# -*- coding: utf-8 -*-
"""The spam protection must look for its settings in ``DDC_CONFIG_DIR``.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

THE FINDING. Without an argument, ``SpamProtectionService`` derives its
directory from ``Path(__file__).parents[2] / "config"``. Its settings live in
the ``spam_protection`` section of ``channels_config.json`` - a file it shares
with ``config_service``, and THAT one follows the variable. With
``DDC_CONFIG_DIR`` set there are therefore TWO ``channels_config.json`` files:
what the panel saves as spam protection lands in one, what the rest of the
application keeps as channel configuration lands in the other.

HOW IT IS CHECKED HERE: the test puts a ``channels_config.json`` with its own
spam protection value into the configured directory. The service must return
EXACTLY that value - the default (``restart`` 20) differs from it.
"""

import json

import pytest

from services.infrastructure.spam_protection_service import SpamProtectionService


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    target = tmp_path / "own_config"
    target.mkdir()
    monkeypatch.setenv("DDC_CONFIG_DIR", str(target))
    return target


def test_the_settings_come_from_the_directory(config_dir):
    (config_dir / "channels_config.json").write_text(json.dumps({
        "spam_protection": {"button_cooldowns": {"restart": 7}},
    }), encoding="utf-8")

    service = SpamProtectionService()

    assert service.config_file == config_dir / "channels_config.json"
    assert service.get_button_cooldown("restart") == 7, (
        "The spam protection does not read its settings from DDC_CONFIG_DIR "
        "(the default would be 20)."
    )
