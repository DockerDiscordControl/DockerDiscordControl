# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Background loop safety for DockerControlCog (moved from docker_control.py, Phase 3).

Its own module so the loops can sit in a mixin without importing the cog module.
"""

import asyncio
import functools
import logging

from discord.ext import tasks

from utils.logging_utils import setup_logger

# Same logger name as the cog: log lines and log-based tests read as before the move.
logger = setup_logger('ddc.docker_control', level=logging.INFO)


# --------------------------------------------------------------------------- #
# Background loops: one bad cycle must not be the last one (review E17)
# --------------------------------------------------------------------------- #
#
# Measured in the shipped py-cord (ext/tasks/__init__.py):
#
#   line 103  _valid_exception = (OSError, GatewayNotFound, ConnectionClosed,
#                                 aiohttp.ClientError, asyncio.TimeoutError)
#   line 171  only those are retried;
#   line 195  ANYTHING else sets _has_failed, calls the loop's error handler and
#             re-raises - the loop is over, permanently, until DDC restarts;
#   line 474  the DEFAULT error handler is a bare print() to sys.stderr.
#
# So a single ValueError or DDC exception used to end the status display for the
# rest of the run, and DDC's own log never mentioned it. The operator sees stale
# numbers and has nothing to look at. That is the worst shape a defect can have.
#
# Two answers, because they cover different failures. The decorator keeps a bad
# CYCLE from being fatal; the error handler makes a loop that dies anyway say so
# through DDC's logger instead of py-cord's print.

def survives_one_bad_cycle(coro):
    """Let a loop body fail a cycle without ending the loop.

    The cycle is lost and said so at ERROR. The loop runs again at its next
    interval, which is what "periodic" is supposed to mean.

    CancelledError travels on untouched: it means DDC is shutting down, not
    that the cycle failed. It descends from BaseException, so `except Exception`
    would not have caught it anyway - the clause is a signpost, and becomes
    load-bearing the moment somebody widens the handler.

    KNOWN AND ACCEPTED (review 2026-09-22): this also catches the five
    exceptions py-cord would have retried IMMEDIATELY (OSError, ConnectionClosed,
    aiohttp.ClientError, asyncio.TimeoutError, GatewayNotFound) - a dropped
    connection now costs one interval instead of a fast retry. Letting them
    through would hand py-cord the very shape this guard exists to prevent: the
    sixth exception ends the loop for the rest of the run. One late cycle is the
    cheaper failure.
    """
    @functools.wraps(coro)
    async def wrapper(*args, **kwargs):
        try:
            return await coro(*args, **kwargs)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - see above
            logger.error("Background loop '%s' lost a cycle (%s: %s) - it will "
                         "run again at the next interval",
                         coro.__name__, type(e).__name__, e, exc_info=True)
            return None
    # A mark the ratchet can see: tests/spec/test_every_recurring_loop_carries_its_guard.py
    # checks that every loop which REPEATS carries this guard, and it
    # reads the loops off the class so one added tomorrow is covered.
    wrapper._ddc_survives_one_bad_cycle = True

    return wrapper


def _register_loop_error_handlers(cls) -> None:
    """Give every tasks.Loop on a class an error handler that uses the logger."""
    for attribute_name in dir(cls):
        candidate = getattr(cls, attribute_name, None)
        if not isinstance(candidate, tasks.Loop):
            continue

        def make_handler(loop_name):
            async def handler(*args):
                exception = args[-1]
                logger.error(
                    "BACKGROUND LOOP STOPPED: '%s' ended with %s: %s. It will "
                    "NOT run again until DDC is restarted - whatever it does is "
                    "no longer happening.",
                    loop_name, type(exception).__name__, exception,
                    exc_info=exception)
            handler.__name__ = f"on_{loop_name}_stopped"
            return handler

        candidate.error(make_handler(attribute_name))
