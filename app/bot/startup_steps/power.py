# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Startup routines that interact with the mech power gift system."""

from __future__ import annotations

import os

import docker

from ..startup_context import StartupContext, as_step


@as_step
async def grant_power_gift_step(context: StartupContext) -> None:
    logger = context.logger
    try:
        logger.info("Checking if power gift should be granted...")
        from services.mech.mech_service_adapter import get_mech_service

        adapter = get_mech_service()
        # Both calls can grant, and only one of them usually does: on a fresh
        # install the welcome gift lands and the release gift is refused right
        # after (the mech has power now). Keeping only the LAST state reported
        # "not needed" on the one boot where a gift really happened.
        granted = []
        state = adapter.power_gift("startup_gift_v1")
        granted.append(getattr(state, "gift", None))

        # Every release refuels a mech that has run dry: three days of the
        # energy its level consumes, on the energy account only. The campaign
        # carries the version, and the event log refuses a campaign it already
        # holds - so a restart of the same version gives nothing and an update
        # gives once. Without DDC_VERSION there is no release to name, and
        # inventing one would hand out a gift on every restart.
        version = (os.environ.get("DDC_VERSION") or "").strip().lstrip("vV")
        if version:
            state = adapter.release_gift(version)
            granted.append(getattr(state, "gift", None))

        # state.power_level is the power the mech HAS; `gift` is what was just
        # given. Reporting the first under the word "granted" told the operator
        # about a gift on every restart of a mech that simply had power - I read
        # the line on the running installation and believed it myself.
        gift = sum(amount for amount in granted if amount) or None
        if gift:
            logger.info("✅ Power gift granted: $%.2f (power is now $%.2f)",
                        gift, state.power_level)
            # REMOVED: Cache clear not needed - MechStatusCacheService reads from DB
            # The background loop will pick up the new value automatically on next refresh
            # Clearing the cache causes Web UI to show "OFFLINE" until loop refreshes
        else:
            logger.info("Power gift not needed (power > 0 or already granted)")
    except Exception as e:  # noqa: BLE001
        # Broad on purpose. This is step 2 of 9, the sequence that runs it has no
        # handler at all, and neither does its caller - so anything that escapes
        # here stops the seven steps after it: no extensions, no commands, no
        # scheduler. The bot connects to Discord and does nothing.
        #
        # What made it necessary: review D1 gave _heal_if_lagging a raise, so a
        # mech snapshot that lags behind the event log and cannot be rebuilt now
        # raises MechStateError instead of quietly burying a donation. That was
        # right. But power_gift heals first too, the adapter passes the exception
        # through, and MechStateError (-> MechServiceError -> DDCBaseException)
        # is in none of the types that used to stand here. A repair that made
        # the money safe made the startup fragile, on a path nobody checked
        # (review E8).
        #
        # A power gift is a nicety; the bot starting is not. Nothing here is
        # worth stopping a startup for.
        logger.error("Error checking/granting power gift: %s: %s",
                     type(e).__name__, e, exc_info=True)
