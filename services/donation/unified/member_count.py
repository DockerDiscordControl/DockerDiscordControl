"""Helpers for computing guild member counts for donations."""

from __future__ import annotations

from typing import Any, Optional

from services.member_count import get_member_count_service


async def resolve_member_context(
    bot_instance: Any,
    guild_id: Optional[str],
    *,
    use_member_count: bool,
) -> tuple[Optional[Any], Optional[int]]:
    """Resolve the guild and member count used during donation processing."""

    service = get_member_count_service()
    return await service.resolve_member_context(
        bot_instance,
        guild_id,
        use_member_count=use_member_count,
    )


async def compute_unique_member_count(guild: Any) -> int:
    """Compute the unique member count across all configured status channels."""

    service = get_member_count_service()
    return service.compute_unique_member_count(guild)

