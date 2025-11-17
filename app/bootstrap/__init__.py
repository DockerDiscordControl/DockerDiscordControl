# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Bootstrap utilities for preparing the Discord bot runtime.

This package centralizes environment and logging setup that previously lived
inside :mod:`bot`.  Keeping the bootstrap logic in one place reduces the amount
of global side-effects that happen during module import and makes it easier to
unit-test the configuration primitives in isolation.
"""

from .performance import apply_runtime_tweaks
from .runtime import (
    configure_environment,
    ensure_log_files,
    ensure_token_security,
    initialize_logging,
    load_main_configuration,
    resolve_timezone,
)

__all__ = [
    "apply_runtime_tweaks",
    "configure_environment",
    "ensure_log_files",
    "ensure_token_security",
    "initialize_logging",
    "load_main_configuration",
    "resolve_timezone",
]
