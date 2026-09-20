# -*- coding: utf-8 -*-
"""The timeout the operator sets is the timeout that is used.

THE FINDING (review C59, section 16 F2): ``_load_timeout_from_config``
carried a block marked "TEMPORARY FIX" which replaced any configured
``DDC_FAST_STATS_TIMEOUT`` or ``DDC_FAST_INFO_TIMEOUT`` below 30 with 45.0,
logging the substitution at INFO and telling nobody else.

The panel offers these two fields with ``min="1" max="60"`` and a placeholder
of 10, and `configuration_page_service` shows 10 as their default. So the
value the panel itself suggests was dead, together with everything from 1 to
29 - half the range the form accepts. The operator typed a number, the panel
stored it, `get_container_timeouts()` reported 45, and 45 was used.
"""

import pytest

from services.docker_service import docker_utils

# What the panel accepts: app/templates/_advanced_settings_modal.html
PANEL_MIN, PANEL_MAX = 1, 60
KEYS = ("DDC_FAST_STATS_TIMEOUT", "DDC_FAST_INFO_TIMEOUT")


@pytest.fixture
def configured(monkeypatch):
    """Put a value into advanced_settings, as the panel's save does."""
    def _set(key, value):
        import services.config.config_service as config_service
        monkeypatch.setattr(config_service, "load_config",
                            lambda: {"advanced_settings": {key: value}})
    return _set


def test_the_suggested_ten_seconds_are_ten_seconds(configured):
    configured("DDC_FAST_STATS_TIMEOUT", "10")

    assert docker_utils._load_timeout_from_config(
        "DDC_FAST_STATS_TIMEOUT", "DDC_FAST_STATS_TIMEOUT", "45.0") == 10.0, (
        "10 is the value the panel itself puts in the field as a suggestion"
    )


def test_the_info_timeout_behaves_the_same(configured):
    configured("DDC_FAST_INFO_TIMEOUT", "5")

    assert docker_utils._load_timeout_from_config(
        "DDC_FAST_INFO_TIMEOUT", "DDC_FAST_INFO_TIMEOUT", "45.0") == 5.0


@pytest.mark.parametrize("key", KEYS)
def test_every_value_the_panel_accepts_is_used(key, configured):
    """The form offers 1 to 60; a form that accepts a value it then ignores
    is worse than one that refuses it."""
    for value in range(PANEL_MIN, PANEL_MAX + 1):
        configured(key, str(value))
        got = docker_utils._load_timeout_from_config(key, key, "45.0")
        assert got == float(value), (
            f"{key} was set to {value}s in the panel and {got}s is used"
        )


def test_a_large_value_still_works(configured):
    """Counter-check: the values that were never overridden must stay."""
    configured("DDC_FAST_STATS_TIMEOUT", "50")

    assert docker_utils._load_timeout_from_config(
        "DDC_FAST_STATS_TIMEOUT", "DDC_FAST_STATS_TIMEOUT", "45.0") == 50.0


def test_without_a_setting_the_default_applies(monkeypatch):
    """Counter-check: nothing configured means env, then default."""
    import services.config.config_service as config_service
    monkeypatch.setattr(config_service, "load_config", lambda: {"advanced_settings": {}})
    monkeypatch.delenv("DDC_FAST_STATS_TIMEOUT", raising=False)

    assert docker_utils._load_timeout_from_config(
        "DDC_FAST_STATS_TIMEOUT", "DDC_FAST_STATS_TIMEOUT", "45.0") == 45.0
