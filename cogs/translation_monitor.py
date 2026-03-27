# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Translation Monitor Cog                        #
# ============================================================================ #
"""
The Listener for the Channel Translation System.
Passively listens to messages in configured source channels and forwards them
to the TranslationService for translation and posting.
"""

import logging
import discord
from discord.ext import commands

from services.translation.translation_service import (
    get_translation_service, TranslationContext
)

logger = logging.getLogger('ddc.cogs.translation_monitor')


class TranslationMonitor(commands.Cog):
    """Monitors source channels and triggers translations."""

    def __init__(self, bot):
        self.bot = bot
        self.translation_service = get_translation_service()
        logger.info("TranslationMonitor Cog initialized")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen to every message for translation triggers."""

        # 1. Ignore own messages (loop protection)
        if message.author == self.bot.user:
            return

        # 2. Ignore DM messages
        if not message.guild:
            return

        # 3. Check if this is a translated message we posted
        if self.translation_service.is_translated_message(str(message.id)):
            return

        try:
            # 4. Extract embed content and images
            embed_texts = []
            embed_images = []
            for embed in message.embeds:
                if embed.title:
                    embed_texts.append(embed.title)
                if embed.description:
                    embed_texts.append(embed.description)
                if embed.footer and embed.footer.text:
                    embed_texts.append(embed.footer.text)
                for emb_field in embed.fields:
                    if emb_field.value:
                        name = emb_field.name or ""
                        embed_texts.append(f"{name}: {emb_field.value}" if name else emb_field.value)
                # Preserve embed images (link previews, etc.)
                if embed.image and embed.image.url:
                    embed_images.append(embed.image.url)
                elif embed.thumbnail and embed.thumbnail.url:
                    embed_images.append(embed.thumbnail.url)

            # 5. Extract attachments (images, videos, files)
            attachment_urls = []
            for att in message.attachments:
                attachment_urls.append({
                    'url': att.url,
                    'filename': att.filename,
                    'content_type': att.content_type or ''
                })

            # 6. Build context
            ctx = TranslationContext(
                message_id=str(message.id),
                channel_id=str(message.channel.id),
                guild_id=str(message.guild.id),
                author_name=message.author.display_name,
                author_avatar_url=str(message.author.display_avatar.url),
                content=message.content,
                embed_texts=embed_texts,
                embed_images=embed_images,
                attachment_urls=attachment_urls
            )

            # 7. Forward to service
            await self.translation_service.process_message(ctx, self.bot)

        except Exception as e:
            logger.error(f"Error in TranslationMonitor: {e}", exc_info=True)


def setup(bot):
    bot.add_cog(TranslationMonitor(bot))
