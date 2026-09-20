# -*- coding: utf-8 -*-
"""A disk limit that cannot be read is not the same as none being set.

THE FINDING (review C67, section 21 F3): the animation cache reads
``DDC_ANIM_DISK_LIMIT_MB`` with ``int()`` inside a try that catches
``(TypeError, ValueError)`` and, on failure, assigns the default of 200 - no
log line, nothing. A typo in the variable therefore looks exactly like not
having set it at all, and the operator who meant to cap the cache at 50 MB
gets 200 MB with no way to find out from the outside.
"""

import logging
import os
from unittest.mock import patch

import pytest

from services.mech.animation_cache_service import AnimationCacheService


@pytest.fixture
def quiet_service():
    """Construct the service without its event listeners or a disk sweep."""
    def _build(env_value):
        environment = dict(os.environ)
        if env_value is None:
            environment.pop("DDC_ANIM_DISK_LIMIT_MB", None)
        else:
            environment["DDC_ANIM_DISK_LIMIT_MB"] = env_value
        with patch.object(AnimationCacheService, "_setup_event_listeners",
                          lambda self: None), \
             patch.object(AnimationCacheService, "enforce_disk_cache_limit",
                          lambda self, *a, **kw: 0), \
             patch.dict(os.environ, environment, clear=True):
            return AnimationCacheService()
    return _build


def test_a_value_that_is_not_a_number_is_named(quiet_service, caplog):
    with caplog.at_level(logging.DEBUG):
        service = quiet_service("fuenfzig")

    assert service._disk_cache_limit_mb == 200
    assert any("fuenfzig" in r.getMessage() for r in caplog.records
               if r.levelno >= logging.WARNING), (
        "the configured limit was thrown away and nothing says which value it was"
    )


def test_a_sound_value_is_used_without_a_word(quiet_service, caplog):
    """Counter-check: a warning on every start would pass the test above."""
    with caplog.at_level(logging.DEBUG):
        service = quiet_service("50")

    assert service._disk_cache_limit_mb == 50
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING
                and "DDC_ANIM_DISK_LIMIT_MB" in r.getMessage()]


def test_no_setting_is_not_a_rejected_setting(quiet_service, caplog):
    """Counter-check: not setting the variable is a perfectly normal case."""
    with caplog.at_level(logging.DEBUG):
        service = quiet_service(None)

    assert service._disk_cache_limit_mb == 200
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING
                and "DDC_ANIM_DISK_LIMIT_MB" in r.getMessage()]
