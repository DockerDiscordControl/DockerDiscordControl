# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Auto Action Monitor Cog                        #
# ============================================================================ #
"""
The Listener for the Auto-Action System.
Passively listens to all messages and forwards them to the AutomationService.
"""

import logging
import discord
from discord.ext import commands

from services.automation.automation_service import get_automation_service, TriggerContext

logger = logging.getLogger('ddc.cogs.auto_action_monitor')

class AutoActionMonitor(commands.Cog):
    """Passively monitors channels for update triggers."""

    def __init__(self, bot):
        self.bot = bot
        self.automation_service = get_automation_service()
        logger.info("AutoActionMonitor Cog initialized")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen to every message."""
        
        # 1. Ignore own messages (Loop protection)
        if message.author == self.bot.user:
            return

        # 2. Ignore DM messages
        if not message.guild:
            return

        try:
            # 3. Extract Embed Content (Title, Description, Fields)
            embeds_text = []
            for embed in message.embeds:
                if embed.title:
                    embeds_text.append(embed.title)
                if embed.description:
                    embeds_text.append(embed.description)
                if embed.footer and embed.footer.text:
                    embeds_text.append(embed.footer.text)
                for field in embed.fields:
                    embeds_text.append(f"{field.name} {field.value}")
            
            # 4. Determine if webhook
            is_webhook = bool(message.webhook_id)

            # 5. Build Context
            ctx = TriggerContext(
                message_id=str(message.id),
                channel_id=str(message.channel.id),
                user_id=str(message.author.id),
                username=message.author.name,
                is_webhook=is_webhook,
                content=message.content,
                embeds_text="\n".join(embeds_text)
            )

            # 6. Forward to Service
            # Pass self.bot so the service can send feedback messages
            await self.automation_service.process_message(ctx, self.bot)

        except Exception as e:
            logger.error(f"Error processing message in AutoActionMonitor: {e}", exc_info=True)

def setup(bot):
    bot.add_cog(AutoActionMonitor(bot))