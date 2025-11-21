# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""Centralized helpers for resolving guild member counts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Set, Tuple

from services.mech.progress_paths import get_progress_paths
from utils.logging_utils import get_module_logger


@dataclass
class _ChannelPermissionsCache:
    """Light-weight cache for channel permission configuration."""

    permissions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    loaded: bool = False


class MemberCountService:
    """Service that encapsulates guild member count resolution logic."""

    def __init__(self) -> None:
        self._logger = get_module_logger("member_count.service")
        self._paths = get_progress_paths()
        self._channel_perms = _ChannelPermissionsCache()

    # ------------------------------------------------------------------
    # Guild helpers
    # ------------------------------------------------------------------
    def resolve_guild(self, bot_instance: Any, guild_id: Optional[str]) -> Optional[Any]:
        """Return the guild identified by *guild_id* from *bot_instance*."""

        if not bot_instance or not guild_id:
            return None

        try:
            resolved_id = int(guild_id)
        except (TypeError, ValueError):
            self._logger.warning("Invalid guild id provided for member count lookup: %s", guild_id)
            return None

        guild = bot_instance.get_guild(resolved_id)
        if guild is None:
            self._logger.warning("Could not find guild with ID %s", resolved_id)
        return guild

    def first_connected_guild(self, bot_instance: Any) -> Optional[Any]:
        """Return the first connected guild for *bot_instance*, if available."""

        guilds = getattr(bot_instance, "guilds", None)
        if not guilds:
            return None
        return guilds[0]

    # ------------------------------------------------------------------
    # Member count resolution
    # ------------------------------------------------------------------
    async def resolve_member_context(
        self,
        bot_instance: Any,
        guild_id: Optional[str],
        *,
        use_member_count: bool,
    ) -> Tuple[Optional[Any], Optional[int]]:
        """Resolve the guild and member count used during donation processing."""

        if not bot_instance or not use_member_count or not guild_id:
            return None, None

        guild = self.resolve_guild(bot_instance, guild_id)
        if guild is None:
            return None, None

        member_count = self.compute_unique_member_count(guild)
        self.publish_member_count(member_count)
        return guild, member_count

    def compute_unique_member_count(self, guild: Any, *, fallback: Optional[int] = None) -> int:
        """Compute the unique member count across all configured status channels."""

        if guild is None:
            self._logger.error("Guild object is None, returning default count of 1")
            return 1

        fallback_count = self._resolve_fallback_count(guild, fallback)

        try:
            channel_perms = self._load_channel_permissions()
            if not channel_perms:
                self._logger.info("No channel permissions configured, using fallback member count")
                return fallback_count

            status_channels = list(self._collect_status_channels(guild, channel_perms))
            if not status_channels:
                self._logger.info("No valid status channels found, using fallback member count")
                return fallback_count

            unique_members: Set[int] = set()
            channels_processed = 0

            for channel in status_channels:
                processed = self._collect_channel_members(channel, unique_members)
                channels_processed += int(processed)

            if channels_processed == 0:
                self._logger.warning(
                    "Could not process any status channels, using fallback member count"
                )
                return fallback_count

            unique_count = len(unique_members)
            if unique_count == 0:
                self._logger.warning(
                    "No unique members detected in status channels; using fallback count %s",
                    fallback_count,
                )
                return fallback_count

            self._logger.info("Unique member count across status channels: %s", unique_count)
            return unique_count
        except (RuntimeError, discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
            self._logger.error("Error updating member count: %s", exc, exc_info=True)
            return fallback_count

    def publish_member_count(self, member_count: int) -> None:
        """Persist the provided member count via the progress service."""

        try:
            from services.mech.progress_service import get_progress_service

            progress_service = get_progress_service()
            progress_service.update_member_count(member_count)
            self._logger.debug("Member count updated successfully: %s", member_count)
        except (AttributeError, ImportError, KeyError, ModuleNotFoundError, RuntimeError, TypeError) as e:
            self._logger.error("Error updating member count: %s", exc, exc_info=True)

    def persist_member_count_snapshot(
        self,
        member_count: int,
        *,
        source: str,
        description: str,
        note: Optional[str] = None,
    ) -> None:
        """Write the current member count to the shared JSON snapshot."""

        payload = {
            "count": member_count,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "description": description,
        }
        if note:
            payload["note"] = note

        member_count_file = self._paths.member_count_file
        member_count_file.parent.mkdir(parents=True, exist_ok=True)
        member_count_file.write_text(json.dumps(payload, indent=2))
        self._logger.info("Persisted member count snapshot to %s", member_count_file)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def refresh_configuration(self) -> None:
        """Clear cached configuration so it is reloaded on the next access."""

        self._channel_perms = _ChannelPermissionsCache()

    def _load_channel_permissions(self) -> Dict[str, Dict[str, Any]]:
        if self._channel_perms.loaded:
            return self._channel_perms.permissions

        try:
            from services.config.config_service import load_config

            config = load_config() or {}
            channel_perms = config.get("channel_permissions", {})
            if not isinstance(channel_perms, dict):
                self._logger.warning(
                    "channel_permissions config is not a mapping (found %s)", type(channel_perms)
                )
                channel_perms = {}
            self._channel_perms = _ChannelPermissionsCache(channel_perms, True)
        except (IOError, OSError, PermissionError, RuntimeError, discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
            self._logger.error("Error loading channel permissions: %s", exc, exc_info=True)
            self._channel_perms = _ChannelPermissionsCache({}, True)

        return self._channel_perms.permissions

    def _collect_status_channels(
        self, guild: Any, channel_perms: Dict[str, Dict[str, Any]]
    ) -> Iterable[Any]:
        for channel_id, channel_config in channel_perms.items():
            if not isinstance(channel_config, dict):
                self._logger.warning(
                    "Invalid channel config for %s: %s", channel_id, type(channel_config)
                )
                continue

            commands = channel_config.get("commands", {})
            if not isinstance(commands, dict) or not commands.get("serverstatus", False):
                continue

            try:
                resolved_id = int(channel_id)
            except (TypeError, ValueError):
                self._logger.warning("Invalid channel ID: %s", channel_id)
                continue

            channel = guild.get_channel(resolved_id)
            if channel is None:
                self._logger.debug("Channel %s not found in guild", channel_id)
                continue

            self._logger.debug(
                "Found status channel: %s (ID: %s)",
                channel_config.get("name", "Unknown"),
                channel_id,
            )
            yield channel

    def _collect_channel_members(self, channel: Any, unique_members: Set[int]) -> bool:
        if not hasattr(channel, "members"):
            self._logger.warning(
                "Channel %s has no members attribute (Members Intent required)",
                getattr(channel, "name", "?"),
            )
            return False

        member_count = 0
        for member in getattr(channel, "members", []):
            try:
                if getattr(member, "bot", False):
                    continue
                if hasattr(member, "system") and getattr(member, "system"):
                    continue

                unique_members.add(member.id)
                member_count += 1
            except (RuntimeError, discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
                self._logger.debug("Error processing member: %s", exc)

        self._logger.debug("  └─ #%s: %s non-bot members", getattr(channel, "name", "?"), member_count)
        return True

    def _resolve_fallback_count(self, guild: Any, fallback: Optional[int]) -> int:
        if fallback is not None and fallback > 0:
            return fallback
        return max(1, getattr(guild, "member_count", 1) or 1)


_member_count_service: Optional[MemberCountService] = None


def get_member_count_service() -> MemberCountService:
    global _member_count_service
    if _member_count_service is None:
        _member_count_service = MemberCountService()
    return _member_count_service


def reset_member_count_service() -> None:
    global _member_count_service
    _member_count_service = None
