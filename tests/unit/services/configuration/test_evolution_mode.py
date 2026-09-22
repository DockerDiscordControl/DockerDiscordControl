#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Tests for persisting the mech evolution mode (finding M2).

Until v2.4.1 there was a *reader* for ``config/evolution_mode.json`` and nothing
that ever wrote it. The Web UI called ``mech_service.set_evolution_mode(...)``,
a method that does not exist on the adapter, so every save raised AttributeError
and came back as HTTP 500 "Failed to set difficulty".

The consequence was silent and total: the file never came into existence, the
reader always fell back to its defaults, and every installation stayed on dynamic
pricing no matter what the difficulty slider displayed. A maintainer who set
"easy" (0.5) kept paying full price.

These tests pin the writer, its validation, and the round-trip through the
reader, so the pairing cannot come apart again.
"""

import json

import pytest

import services.config.config_service as config_service_module
from services.config.config_service import (
    ConfigService,
    GetEvolutionModeRequest,
    SetEvolutionModeRequest,
)


@pytest.fixture
def service(tmp_path, monkeypatch):
    """A ConfigService on an empty, throwaway config directory."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(ConfigService, "_instance", None)
    svc = ConfigService()
    monkeypatch.setattr(config_service_module, "_config_service_instance", svc)
    return svc


def _mode_file(svc):
    return svc.config_dir / "evolution_mode.json"


def _read(svc):
    return svc.get_evolution_mode_service(GetEvolutionModeRequest())


# ---------------------------------------------------------------------------
# The writer that was missing
# ---------------------------------------------------------------------------

class TestWriterExists:
    def test_the_service_can_persist_a_mode_at_all(self, service):
        """The regression itself: without this method the slider could never work."""
        assert hasattr(service, "set_evolution_mode_service")

    def test_writing_creates_the_file(self, service):
        assert not _mode_file(service).exists()
        result = service.set_evolution_mode_service(
            SetEvolutionModeRequest(use_dynamic=False, difficulty_multiplier=0.5))
        assert result.success is True
        assert _mode_file(service).exists()

    def test_only_the_two_consumed_keys_are_written(self, service):
        """Keeping the file minimal means an older version can still read it."""
        service.set_evolution_mode_service(
            SetEvolutionModeRequest(use_dynamic=False, difficulty_multiplier=2.0))
        data = json.loads(_mode_file(service).read_text(encoding="utf-8"))
        assert set(data) == {"use_dynamic", "difficulty_multiplier"}


# ---------------------------------------------------------------------------
# Round-trip through the reader
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_static_mode_survives_a_read(self, service):
        service.set_evolution_mode_service(
            SetEvolutionModeRequest(use_dynamic=False, difficulty_multiplier=0.5))
        read = _read(service)
        assert read.success is True
        assert read.use_dynamic is False
        assert read.difficulty_multiplier == 0.5

    def test_dynamic_mode_survives_a_read(self, service):
        service.set_evolution_mode_service(
            SetEvolutionModeRequest(use_dynamic=True, difficulty_multiplier=1.0))
        read = _read(service)
        assert read.use_dynamic is True
        assert read.difficulty_multiplier == 1.0

    def test_switching_back_and_forth_keeps_the_last_value(self, service):
        service.set_evolution_mode_service(
            SetEvolutionModeRequest(use_dynamic=False, difficulty_multiplier=3.0))
        service.set_evolution_mode_service(
            SetEvolutionModeRequest(use_dynamic=True, difficulty_multiplier=1.0))
        read = _read(service)
        assert read.use_dynamic is True

    def test_missing_file_reads_as_dynamic(self, service):
        """The documented default: community-based pricing, multiplier ignored."""
        read = _read(service)
        assert read.use_dynamic is True
        assert read.difficulty_multiplier == 1.0


# ---------------------------------------------------------------------------
# Validation - a rejected value must not be reported as saved
# ---------------------------------------------------------------------------

class TestValidation:
    @pytest.mark.parametrize("multiplier", [0.0, -1.0, 0.05, 10.1, 1000.0])
    def test_out_of_range_multipliers_are_rejected(self, service, multiplier):
        result = service.set_evolution_mode_service(
            SetEvolutionModeRequest(use_dynamic=False, difficulty_multiplier=multiplier))
        assert result.success is False
        assert result.error and "multiplier" in result.error.lower()

    @pytest.mark.parametrize("multiplier", ["halb", None, object()])
    def test_non_numeric_multipliers_are_rejected(self, service, multiplier):
        result = service.set_evolution_mode_service(
            SetEvolutionModeRequest(use_dynamic=False, difficulty_multiplier=multiplier))
        assert result.success is False

    def test_a_rejected_value_does_not_touch_the_file(self, service):
        """Half-written state would be worse than the original bug."""
        service.set_evolution_mode_service(
            SetEvolutionModeRequest(use_dynamic=False, difficulty_multiplier=0.5))
        before = _mode_file(service).read_text(encoding="utf-8")

        service.set_evolution_mode_service(
            SetEvolutionModeRequest(use_dynamic=False, difficulty_multiplier=99.0))
        assert _mode_file(service).read_text(encoding="utf-8") == before

    @pytest.mark.parametrize("multiplier", [0.1, 0.5, 1.0, 2.0, 10.0])
    def test_boundaries_and_typical_values_are_accepted(self, service, multiplier):
        result = service.set_evolution_mode_service(
            SetEvolutionModeRequest(use_dynamic=False, difficulty_multiplier=multiplier))
        assert result.success is True
        assert result.difficulty_multiplier == multiplier

    def test_integer_multipliers_are_accepted(self, service):
        """The Web UI may send 2 rather than 2.0."""
        result = service.set_evolution_mode_service(
            SetEvolutionModeRequest(use_dynamic=False, difficulty_multiplier=2))
        assert result.success is True
        assert result.difficulty_multiplier == 2.0
