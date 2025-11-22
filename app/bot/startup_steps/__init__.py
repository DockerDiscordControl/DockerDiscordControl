# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Composable startup routines executed when the Discord bot becomes ready."""

from __future__ import annotations

from typing import Sequence

from ..startup_context import StartupStep
from .commands import (
    load_extensions_step,
    prepare_schedule_commands_step,
    synchronize_commands_step,
)
from .cooldowns import apply_dynamic_cooldowns_step
from .diagnostics import run_port_diagnostics_step
from .member_count import initialize_member_count_step
from .notifications import send_update_notification_step
from .power import grant_power_gift_step
from .scheduler import start_scheduler_step
from .sequence import run_startup_sequence

STARTUP_STEPS: Sequence[StartupStep] = (
    run_port_diagnostics_step,
    grant_power_gift_step,          # MUST run before load_extensions to ensure power is set before status messages
    load_extensions_step,
    prepare_schedule_commands_step,
    synchronize_commands_step,
    apply_dynamic_cooldowns_step,
    start_scheduler_step,
    send_update_notification_step,
    initialize_member_count_step,
)

__all__ = [
    "STARTUP_STEPS",
    "run_startup_sequence",
    "run_port_diagnostics_step",
    "load_extensions_step",
    "prepare_schedule_commands_step",
    "synchronize_commands_step",
    "apply_dynamic_cooldowns_step",
    "start_scheduler_step",
    "send_update_notification_step",
    "initialize_member_count_step",
    "grant_power_gift_step",
]
