# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Discord Channel Cleanup Service                #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Discord Channel Cleanup Service

Provides centralized channel maintenance and cleanup operations:
- Clean sweep bot messages
- Bulk delete operations
- Permission-aware cleanup
- Configurable thresholds and limits

Service-First Architecture:
- Single Source of Truth for Discord cleanup operations
- Used by multiple cogs and recovery systems
- Isolated, testable, and reusable
"""

import discord
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
from utils.logging_utils import get_module_logger

logger = get_module_logger('channel_cleanup_service')


class ChannelCleanupRequest:
    """Request object for channel cleanup operations."""

    def __init__(
        self,
        channel: discord.TextChannel,
        reason: str,
        message_limit: int = 100,
        max_age_days: int = 30,
        bot_only: bool = True,
        target_author: Optional[discord.User] = None
    ):
        self.channel = channel
        self.reason = reason
        self.message_limit = message_limit
        self.max_age_days = max_age_days
        self.bot_only = bot_only
        self.target_author = target_author


class ChannelCleanupResult:
    """Result object for channel cleanup operations."""

    def __init__(self):
        self.success: bool = False
        self.error: Optional[str] = None
        self.messages_found: int = 0
        self.messages_deleted: int = 0
        self.bulk_deleted: int = 0
        self.individually_deleted: int = 0
        self.permission_errors: int = 0
        self.not_found_errors: int = 0
        self.execution_time_ms: float = 0.0


class ChannelCleanupService:
    """
    Service for Discord channel cleanup and maintenance operations.

    Features:
    - Smart bulk delete for recent messages (< 14 days Discord limit)
    - Individual delete fallback for older messages
    - Permission-aware error handling
    - Configurable filtering (bot messages, specific authors, etc.)
    - Comprehensive result reporting
    """

    def __init__(self, bot: discord.Bot):
        self.bot = bot
        logger.info("Discord Channel Cleanup Service initialized")

    async def clean_sweep_bot_messages(
        self,
        channel: discord.TextChannel,
        reason: str,
        message_limit: int = 100
    ) -> ChannelCleanupResult:
        """
        Clean sweep: Delete all bot messages in channel.

        Args:
            channel: Discord text channel to clean
            reason: Reason for cleanup (for logging)
            message_limit: Maximum messages to scan (default: 100)

        Returns:
            ChannelCleanupResult with detailed operation statistics
        """
        request = ChannelCleanupRequest(
            channel=channel,
            reason=reason,
            message_limit=message_limit,
            bot_only=True,
            target_author=self.bot.user
        )

        return await self.cleanup_channel(request)

    async def cleanup_channel(self, request: ChannelCleanupRequest) -> ChannelCleanupResult:
        """
        Perform comprehensive channel cleanup based on request parameters.

        Args:
            request: ChannelCleanupRequest with cleanup configuration

        Returns:
            ChannelCleanupResult with detailed operation statistics
        """
        result = ChannelCleanupResult()
        start_time = datetime.now(timezone.utc)

        try:
            logger.info(f"🧹 CLEANUP START: Channel {request.channel.id} (reason: {request.reason})")

            # Step 1: Collect target messages
            messages_to_delete = await self._collect_messages(request, result)

            if not messages_to_delete:
                logger.info(f"🧹 CLEANUP: No messages found to delete in channel {request.channel.id}")
                result.success = True
                return result

            result.messages_found = len(messages_to_delete)
            logger.info(f"🧹 CLEANUP: Found {result.messages_found} messages to delete in channel {request.channel.id}")

            # Step 2: Perform deletions
            await self._delete_messages(request, messages_to_delete, result)

            # Step 3: Calculate results
            result.messages_deleted = result.bulk_deleted + result.individually_deleted
            result.success = True

            logger.info(f"✅ CLEANUP SUCCESS: Channel {request.channel.id} - "
                       f"Deleted {result.messages_deleted}/{result.messages_found} messages "
                       f"(Bulk: {result.bulk_deleted}, Individual: {result.individually_deleted})")

        except Exception as e:
            result.error = str(e)
            logger.error(f"❌ CLEANUP FAILED: Channel {request.channel.id} - {e}", exc_info=True)

        finally:
            # Calculate execution time
            end_time = datetime.now(timezone.utc)
            result.execution_time_ms = (end_time - start_time).total_seconds() * 1000

        return result

    async def _collect_messages(
        self,
        request: ChannelCleanupRequest,
        result: ChannelCleanupResult
    ) -> List[discord.Message]:
        """Collect messages that match the cleanup criteria."""
        messages_to_delete = []
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=request.max_age_days)

        async for message in request.channel.history(limit=request.message_limit):
            # Check age limit
            if message.created_at < cutoff_date:
                continue

            # Filter by author
            if request.bot_only and message.author != self.bot.user:
                continue
            elif request.target_author and message.author != request.target_author:
                continue
            elif not request.bot_only and not request.target_author:
                # Include all messages if no specific filtering
                pass

            messages_to_delete.append(message)

        return messages_to_delete

    async def _delete_messages(
        self,
        request: ChannelCleanupRequest,
        messages_to_delete: List[discord.Message],
        result: ChannelCleanupResult
    ) -> None:
        """Delete messages using optimal strategy (bulk vs individual)."""

        # Separate messages by age for optimal deletion strategy
        two_weeks_ago = datetime.now(timezone.utc) - timedelta(days=14)
        bulk_eligible = [msg for msg in messages_to_delete if msg.created_at > two_weeks_ago]
        old_messages = [msg for msg in messages_to_delete if msg.created_at <= two_weeks_ago]

        # Strategy 1: Bulk delete recent messages (< 14 days)
        if bulk_eligible:
            await self._bulk_delete_messages(request, bulk_eligible, result)

        # Strategy 2: Individual delete old messages (> 14 days)
        if old_messages:
            await self._individual_delete_messages(request, old_messages, result)

    async def _bulk_delete_messages(
        self,
        request: ChannelCleanupRequest,
        messages: List[discord.Message],
        result: ChannelCleanupResult
    ) -> None:
        """Perform bulk deletion for eligible messages."""
        try:
            if len(messages) == 1:
                # Single message deletion
                await messages[0].delete()
                result.bulk_deleted = 1
                logger.info(f"🧹 CLEANUP: Deleted 1 recent message")
            else:
                # True bulk deletion
                await request.channel.delete_messages(messages)
                result.bulk_deleted = len(messages)
                logger.info(f"🧹 CLEANUP: Bulk deleted {result.bulk_deleted} recent messages")

        except discord.Forbidden:
            logger.warning(f"⚠️ CLEANUP: Missing 'Manage Messages' permission in channel {request.channel.id}")
            result.permission_errors += 1
            # Fallback to individual deletion
            await self._individual_delete_messages(request, messages, result)

        except Exception as e:
            logger.warning(f"⚠️ CLEANUP: Bulk delete failed, trying individual deletion: {e}")
            # Fallback to individual deletion
            await self._individual_delete_messages(request, messages, result)

    async def _individual_delete_messages(
        self,
        request: ChannelCleanupRequest,
        messages: List[discord.Message],
        result: ChannelCleanupResult
    ) -> None:
        """Perform individual deletion for messages."""
        deleted_count = 0

        for message in messages:
            try:
                await message.delete()
                deleted_count += 1
            except discord.NotFound:
                result.not_found_errors += 1
                # Message already deleted, count as success
                deleted_count += 1
            except discord.Forbidden:
                result.permission_errors += 1
                logger.debug(f"No permission to delete message {message.id}")
            except Exception as e:
                logger.debug(f"Failed to delete message {message.id}: {e}")

        result.individually_deleted += deleted_count
        logger.info(f"🧹 CLEANUP: Individually deleted {deleted_count}/{len(messages)} messages")


# Singleton instance
_channel_cleanup_service: Optional[ChannelCleanupService] = None


def get_channel_cleanup_service(bot: discord.Bot = None) -> ChannelCleanupService:
    """
    Get the singleton instance of ChannelCleanupService.

    Args:
        bot: Discord bot instance (required for first initialization)

    Returns:
        ChannelCleanupService singleton instance
    """
    global _channel_cleanup_service

    if _channel_cleanup_service is None:
        if bot is None:
            raise ValueError("Bot instance required for first initialization of ChannelCleanupService")
        _channel_cleanup_service = ChannelCleanupService(bot)

    return _channel_cleanup_service


def reset_channel_cleanup_service() -> None:
    """Reset the singleton instance (primarily for testing)."""
    global _channel_cleanup_service
    _channel_cleanup_service = None