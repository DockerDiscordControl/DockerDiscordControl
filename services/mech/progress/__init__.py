# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""Progress service support package."""

from .runtime import ProgressRuntime, get_progress_runtime, reset_progress_runtime

__all__ = [
    "ProgressRuntime",
    "get_progress_runtime",
    "reset_progress_runtime",
]
