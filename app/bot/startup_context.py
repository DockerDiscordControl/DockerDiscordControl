# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Shared context and helpers for Discord bot startup orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
from typing import Awaitable, Callable, Protocol

import discord

from .runtime import BotRuntime


@dataclass
class StartupContext:
    """Lightweight view over the runtime data shared across startup steps."""

    bot: discord.Bot
    runtime: BotRuntime

    @property
    def logger(self):
        """Expose the shared logger that all startup routines should use."""

        return self.runtime.logger


class StartupStep(Protocol):
    """Protocol describing a coroutine-based startup routine."""

    async def __call__(self, context: StartupContext) -> None:
        """Execute the startup routine for the provided context."""


StepCallable = Callable[[StartupContext], Awaitable[None]]


def as_step(func: StepCallable) -> StartupStep:
    """Helper to annotate plain callables as startup steps with metadata."""

    step_name = getattr(func, "__name__", func.__class__.__name__)

    @wraps(func)
    async def _runner(context: StartupContext) -> None:
        context.logger.debug("Executing startup step: %s", step_name)
        await func(context)

    setattr(_runner, "step_name", step_name)
    return _runner

