# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Helpers for orchestrating the Discord bot startup sequence."""

from __future__ import annotations

import asyncio
from typing import Sequence

from ..startup_context import StartupContext, StartupStep


async def run_startup_sequence(context: StartupContext, steps: Sequence[StartupStep]) -> None:
    """Run every startup step, and say at the end which ones did not work.

    This used to be a bare ``for step in steps: await step(context)``. Anything a
    step raised that its own handler did not list stopped every step after it -
    and the sequence runs in ``handle_ready()``, so the bot is ALREADY connected
    to Discord by then. An abort could therefore never protect anything; it only
    made a bad start worse. A power gift that could not be granted took the
    scheduler down with it, and the containers were not started that night for a
    reason that had nothing to do with them (review E8/E9).

    Decided by the operator on 2026-09-21, step by step: not one of the nine is
    worth stopping the others for. So every step is guarded on its own, the
    sequence always runs to the end, and what failed is said ONCE at the end -
    a single failure line drowns in three hundred lines of startup, and "the
    scheduler is not running" is not something to find out at night.

    CancelledError is not a step failure: it means DDC is shutting down, and it
    travels on. The clause below that says so is a SIGNPOST, not a guard -
    measured: removing it changes nothing, because CancelledError descends from
    BaseException and `except Exception` never caught it in the first place. It
    stays because it becomes load-bearing the moment somebody widens that
    handler, and because the intent should be readable without knowing the
    exception hierarchy by heart.
    """
    logger = context.logger
    failed = []

    for step in steps:
        step_name = getattr(step, "step_name", getattr(step, "__name__", "unknown"))
        logger.info("→ Running startup step: %s", step_name)
        try:
            await step(context)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - see the docstring
            failed.append(step_name)
            logger.error("✗ Startup step FAILED: %s (%s: %s) - continuing with the rest",
                         step_name, type(e).__name__, e, exc_info=True)
            continue
        logger.info("✓ Completed startup step: %s", step_name)

    if failed:
        logger.error("STARTUP INCOMPLETE: %d of %d steps failed (%s). DDC is running, "
                     "but whatever those steps do is missing - check the errors above.",
                     len(failed), len(steps), ", ".join(failed))
    else:
        logger.info("All %d startup steps completed.", len(steps))
