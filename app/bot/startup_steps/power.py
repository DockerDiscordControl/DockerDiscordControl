"""Startup routines that interact with the mech power gift system."""

from __future__ import annotations

from ..startup_context import StartupContext, as_step


@as_step
async def grant_power_gift_step(context: StartupContext) -> None:
    logger = context.logger
    try:
        logger.info("Checking if power gift should be granted...")
        from services.mech.mech_service_adapter import get_mech_service

        campaign_id = "startup_gift_v1"
        adapter = get_mech_service()
        state = adapter.power_gift(campaign_id)

        if state.power_level > 0:
            logger.info("✅ Power gift granted: $%.2f Power", state.power_level)
            docker_cog = context.bot.get_cog("DockerControlCog")
            if docker_cog and hasattr(docker_cog, "mech_status_cache_service"):
                docker_cog.mech_status_cache_service.clear_cache()
                logger.info("🔄 Mech cache cleared after power gift")
            else:
                logger.warning("Could not access DockerControlCog for cache invalidation")
        else:
            logger.info("Power gift not needed (power > 0 or already granted)")
    except (IOError, OSError, PermissionError, RuntimeError, docker.errors.APIError, docker.errors.DockerException) as e:
        logger.error("Error checking/granting power gift: %s", exc, exc_info=True)
