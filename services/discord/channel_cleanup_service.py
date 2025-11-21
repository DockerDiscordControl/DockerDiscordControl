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
from typing import List, Optional, Dict, Any, Callable
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
        target_author: Optional[discord.User] = None,
        custom_filter: Optional[Callable[[discord.Message], bool]] = None,
        use_purge: bool = False,
        purge_timeout: float = 30.0
    ):
        self.channel = channel
        self.reason = reason
        self.message_limit = message_limit
        self.max_age_days = max_age_days
        self.bot_only = bot_only
        self.target_author = target_author
        self.custom_filter = custom_filter  # Custom message filter function
        self.use_purge = use_purge  # Use Discord's purge API for efficiency
        self.purge_timeout = purge_timeout  # Timeout for purge operations


class ChannelCleanupResult:
    """Result object for channel cleanup operations."""

    def __init__(self):
        self.success: bool = False
        self.error: Optional[str] = None
        self.messages_found: int = 0
        self.messages_deleted: int = 0
        self.bulk_deleted: int = 0
        self.individually_deleted: int = 0
        self.purge_deleted: int = 0  # Messages deleted via Discord purge API
        self.permission_errors: int = 0
        self.not_found_errors: int = 0
        self.timeout_errors: int = 0  # Purge timeout errors
        self.messages_preserved: int = 0  # Messages excluded by custom filter
        self.execution_time_ms: float = 0.0
        self.method_used: str = "unknown"  # Track which deletion method was used


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

    async def delete_bot_messages_preserve_live_logs(
        self,
        channel: discord.TextChannel,
        reason: str,
        message_limit: int = 200
    ) -> ChannelCleanupResult:
        """
        Delete bot messages while preserving Live Log messages.

        This method replicates the complex Live Log preservation logic
        from the original delete_bot_messages method.

        Args:
            channel: Discord text channel to clean
            reason: Reason for cleanup (for logging)
            message_limit: Maximum messages to scan (default: 200)

        Returns:
            ChannelCleanupResult with detailed operation statistics
        """

        def is_bot_but_not_live_logs(message: discord.Message) -> bool:
            """Filter function that excludes Live Log messages."""
            if message.author != self.bot.user:
                return False

            # Check if this is a Live Log message by looking for specific indicators
            if message.embeds:
                for embed in message.embeds:
                    # Check for Live Log indicators in title
                    if embed.title and any(keyword in embed.title for keyword in [
                        "Live Logs", "Live Debug Logs", "Debug Logs", "🔍 Live", "🔍 Debug", "🔄 Debug"
                    ]):
                        logger.debug(f"Preserving Live Log message {message.id} with title: {embed.title}")
                        return False

                    # Check for Live Log indicators in footer
                    if embed.footer and embed.footer.text and any(keyword in embed.footer.text for keyword in [
                        "Auto-refreshing", "manually refreshed", "Auto-refresh", "live updates"
                    ]):
                        logger.debug(f"Preserving Live Log message {message.id} with footer: {embed.footer.text}")
                        return False

            return True

        request = ChannelCleanupRequest(
            channel=channel,
            reason=reason,
            message_limit=message_limit,
            bot_only=True,
            target_author=self.bot.user,
            custom_filter=is_bot_but_not_live_logs,
            use_purge=True,  # Use purge for efficiency like original method
            purge_timeout=30.0
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
            if request.use_purge and request.custom_filter:
                # Use Discord purge API with custom filter for efficiency
                await self._purge_with_filter(request, result)
            else:
                # Use traditional bulk/individual deletion method
                await self._delete_messages(request, messages_to_delete, result)

            # Step 3: Calculate results
            result.messages_deleted = result.bulk_deleted + result.individually_deleted + result.purge_deleted
            result.success = True

            # Choose appropriate logging based on method used
            if result.purge_deleted > 0:
                logger.info(f"✅ CLEANUP SUCCESS: Channel {request.channel.id} - "
                           f"Deleted {result.messages_deleted} messages via {result.method_used} "
                           f"(Preserved: {result.messages_preserved})")
            else:
                logger.info(f"✅ CLEANUP SUCCESS: Channel {request.channel.id} - "
                           f"Deleted {result.messages_deleted}/{result.messages_found} messages "
                           f"(Bulk: {result.bulk_deleted}, Individual: {result.individually_deleted})")

        except (RuntimeError, discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
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

            # Apply custom filter if provided
            if request.custom_filter:
                if not request.custom_filter(message):
                    result.messages_preserved += 1
                    continue

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

        except (RuntimeError, asyncio.CancelledError, asyncio.TimeoutError, discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
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
            except (IOError, OSError, PermissionError, RuntimeError, discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
                logger.debug(f"Failed to delete message {message.id}: {e}")

        result.individually_deleted += deleted_count
        logger.info(f"🧹 CLEANUP: Individually deleted {deleted_count}/{len(messages)} messages")

    async def _purge_with_filter(
        self,
        request: ChannelCleanupRequest,
        result: ChannelCleanupResult
    ) -> None:
        """Perform purge deletion with custom filter and timeout handling."""
        import asyncio

        try:
            # Use Discord's purge API with custom filter
            deleted = await asyncio.wait_for(
                request.channel.purge(limit=request.message_limit, check=request.custom_filter),
                timeout=request.purge_timeout
            )
            result.purge_deleted = len(deleted)
            result.method_used = "Discord purge API"
            logger.info(f"🧹 CLEANUP: Purge deleted {result.purge_deleted} messages successfully")

        except asyncio.TimeoutError:
            result.timeout_errors += 1
            result.method_used = "purge timeout -> fallback"
            logger.warning(f"⚠️ CLEANUP: Purge timeout after {request.purge_timeout}s, using fallback method")

            # Fallback: manual deletion with limit for safety
            deleted_count = 0
            messages_checked = 0

            async for message in request.channel.history(limit=min(request.message_limit, 50)):
                messages_checked += 1

                if request.custom_filter and request.custom_filter(message):
                    try:
                        await message.delete()
                        deleted_count += 1
                        await asyncio.sleep(0.1)  # Rate limiting
                    except (discord.NotFound, discord.Forbidden):
                        pass
                elif not request.custom_filter:
                    result.messages_preserved += 1

                if messages_checked >= 50:  # Hard safety limit
                    break

            result.individually_deleted = deleted_count
            logger.info(f"🧹 CLEANUP: Fallback deleted {deleted_count}/{messages_checked} messages")

        except discord.Forbidden:
            result.permission_errors += 1
            result.method_used = "purge forbidden -> no action"
            logger.warning(f"⚠️ CLEANUP: Missing 'Manage Messages' permission for purge in channel {request.channel.id}")

        except (RuntimeError, discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
            result.method_used = f"purge error -> {str(e)[:50]}"
            logger.warning(f"⚠️ CLEANUP: Purge failed with error: {e}")
            raise  # Re-raise to be handled by main cleanup method


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
