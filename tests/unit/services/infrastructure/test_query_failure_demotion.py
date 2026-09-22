#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Demoting stale positive query-support verdicts (finding P1b).

A positive verdict used to be permanent: ``should_probe()`` skips final entries,
so nothing ever re-checked a container that answered once. Measured on the live
installation, Enshrouded_Proton had a 77-day-old "supported" verdict while its
query port was no longer published - every status cycle paid a full 5 s timeout
for it (reproduced twice: 5005 ms and 5006 ms).

Repeated failed live queries now put such a verdict back into probing. From
there the normal lifecycle takes over: it either recovers, or it becomes a final
negative and the status loop skips it entirely (finding P1).

Only FINAL POSITIVE verdicts are touched. Unknown and already-negative
containers belong to the probe path and must not be disturbed, otherwise two
mechanisms would fight over the same state.
"""

import json

import pytest

from services.infrastructure.game_query_support_service import (
    QUERY_FAILURE_DEMOTE_THRESHOLD,
    GameQuerySupportService,
)


@pytest.fixture
def service(tmp_path):
    """A support service on its own verdict file - never touches the real config."""
    return GameQuerySupportService(path=tmp_path / "query_support.json")


def _make_supported(service, name="enshrouded"):
    """Bring a container into the state the bug needed: supported AND final."""
    service.record_result(name, True, "source", 15637)
    assert service.is_supported(name) is True
    assert service.is_final(name) is True
    return name


# ---------------------------------------------------------------------------
# The demotion itself
# ---------------------------------------------------------------------------

class TestDemotion:
    def test_failures_below_the_threshold_change_nothing(self, service):
        name = _make_supported(service)
        for _ in range(QUERY_FAILURE_DEMOTE_THRESHOLD - 1):
            assert service.note_query_failure(name) is False
        assert service.is_supported(name) is True
        assert service.is_final(name) is True

    def test_the_threshold_failure_demotes(self, service):
        name = _make_supported(service)
        results = [service.note_query_failure(name)
                   for _ in range(QUERY_FAILURE_DEMOTE_THRESHOLD)]
        assert results[-1] is True
        assert results[:-1] == [False] * (QUERY_FAILURE_DEMOTE_THRESHOLD - 1)

    def test_demoted_verdict_is_negative_and_not_final(self, service):
        """Not final is the point: only then does the probe path pick it up again."""
        name = _make_supported(service)
        for _ in range(QUERY_FAILURE_DEMOTE_THRESHOLD):
            service.note_query_failure(name)
        assert service.is_supported(name) is False
        assert service.is_final(name) is False

    def test_demoted_container_is_probed_again(self, service):
        name = _make_supported(service)
        assert service.should_probe(name, now_mono=1000.0) is False  # final -> never probed
        for _ in range(QUERY_FAILURE_DEMOTE_THRESHOLD):
            service.note_query_failure(name)
        assert service.should_probe(name, now_mono=1000.0) is True

    def test_demotion_is_persisted(self, service, tmp_path):
        """The web process reads this file; an in-memory-only demotion would be invisible."""
        name = _make_supported(service)
        for _ in range(QUERY_FAILURE_DEMOTE_THRESHOLD):
            service.note_query_failure(name)
        stored = json.loads((tmp_path / "query_support.json").read_text(encoding="utf-8"))
        assert stored[name]["supported"] is False
        assert stored[name]["final"] is False

    def test_a_custom_threshold_is_honoured(self, service):
        name = _make_supported(service)
        assert service.note_query_failure(name, threshold=1) is True


# ---------------------------------------------------------------------------
# A success clears the streak
# ---------------------------------------------------------------------------

class TestSuccessResets:
    def test_success_clears_a_partial_streak(self, service):
        """An occasional hiccup must not accumulate towards demotion over hours."""
        name = _make_supported(service)
        for _ in range(QUERY_FAILURE_DEMOTE_THRESHOLD - 1):
            service.note_query_failure(name)
        service.note_query_success(name)

        for _ in range(QUERY_FAILURE_DEMOTE_THRESHOLD - 1):
            assert service.note_query_failure(name) is False
        assert service.is_supported(name) is True

    def test_success_on_an_unknown_container_is_harmless(self, service):
        service.note_query_success("never-seen")  # must not raise or create state
        assert service.is_supported("never-seen") is None


# ---------------------------------------------------------------------------
# Everything else is left alone
# ---------------------------------------------------------------------------

class TestOnlyFinalPositivesAreTouched:
    def test_unknown_container_is_not_demoted(self, service):
        assert service.note_query_failure("never-seen") is False
        assert service.is_supported("never-seen") is None

    def test_already_negative_final_verdict_is_untouched(self, service):
        """It is already excluded by the status loop; re-writing it would only churn the file."""
        name = "dead"
        # Deliberately not 0.0: the service does `probing_since or now_wall`, so a zero
        # timestamp would be treated as unset and the window would never elapse.
        service.record_result(name, False, now_wall=1_000_000.0)      # opens the probe window
        service.record_result(name, False, now_wall=1_002_000.0)      # window elapsed -> final
        assert service.is_final(name) is True
        assert service.is_supported(name) is False

        for _ in range(QUERY_FAILURE_DEMOTE_THRESHOLD + 2):
            assert service.note_query_failure(name) is False

    def test_non_final_negative_is_left_to_the_probe_path(self, service):
        name = "probing"
        service.record_result(name, False)
        assert service.is_final(name) is False

        for _ in range(QUERY_FAILURE_DEMOTE_THRESHOLD + 2):
            assert service.note_query_failure(name) is False

    def test_demotion_happens_only_once_per_streak(self, service):
        """After demotion the container is no longer a final positive, so it stops counting."""
        name = _make_supported(service)
        for _ in range(QUERY_FAILURE_DEMOTE_THRESHOLD):
            service.note_query_failure(name)
        for _ in range(QUERY_FAILURE_DEMOTE_THRESHOLD + 1):
            assert service.note_query_failure(name) is False

    def test_other_containers_are_unaffected(self, service):
        doomed = _make_supported(service, "doomed")
        healthy = _make_supported(service, "healthy")
        for _ in range(QUERY_FAILURE_DEMOTE_THRESHOLD):
            service.note_query_failure(doomed)

        assert service.is_supported(doomed) is False
        assert service.is_supported(healthy) is True
        assert service.is_final(healthy) is True
