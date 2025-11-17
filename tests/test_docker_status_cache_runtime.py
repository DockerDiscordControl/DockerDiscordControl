# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Tests for the Docker status cache runtime helper."""

from services.docker_service.status_cache_runtime import (
    get_docker_status_cache_runtime,
    reset_docker_status_cache_runtime,
)


def setup_function() -> None:  # type: ignore[override]
    """Ensure every test gets a fresh runtime instance."""

    reset_docker_status_cache_runtime()


def test_publish_and_snapshot_are_isolated():
    runtime = get_docker_status_cache_runtime()

    runtime.publish({"alpha": {"running": True}})
    snapshot = runtime.snapshot()

    # Mutating the snapshot should not leak back into the runtime.
    snapshot["alpha"]["running"] = False

    stored = runtime.lookup("alpha")
    assert stored == {"running": True}


def test_items_return_copies():
    runtime = get_docker_status_cache_runtime()

    runtime.publish({"beta": {"running": False}})
    items = runtime.items()

    assert items == (("beta", {"running": False}),)

    # Mutate the returned structure and ensure the runtime copy stays intact.
    items[0][1]["running"] = True

    stored = runtime.lookup("beta")
    assert stored == {"running": False}


def test_clear_resets_snapshot():
    runtime = get_docker_status_cache_runtime()

    runtime.publish({"gamma": {"running": True}})
    runtime.clear()

    assert runtime.snapshot() == {}
    assert runtime.lookup("gamma") is None
