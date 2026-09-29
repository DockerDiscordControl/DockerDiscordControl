# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Update Notification System - Shows new features after updates
"""

import asyncio
import json
import os
import re
from services.config.config_service import load_config
import logging
import discord
from pathlib import Path
from typing import Dict, Any, Optional
from utils.atomic_io import atomic_write_json
from utils.logging_utils import get_module_logger
from cogs.translation_manager import _

# Where a version's release notes are - the notice links them instead of listing features
RELEASE_NOTES_URL = "https://github.com/DockerDiscordControl/DockerDiscordControl/releases/tag/v{version}"
# The same notes as text, read once when the notice for a version goes out (operator,
# 2026-09-28: show the notes of the version that was installed, once per version)
RELEASE_API_URL = "https://api.github.com/repos/DockerDiscordControl/DockerDiscordControl/releases/tags/v{version}"
# An embed description holds 4096 characters; room is left for the link under the notes
NOTES_LIMIT = 3800


async def fetch_release_notes(version: str, timeout: float = 10.0) -> Optional[str]:
    """The release notes of `version` from GitHub, or None.

    None when the version has no release there (a build of develop), GitHub
    cannot be reached, or it answers anything but the release. The notice then
    links the notes instead of showing them. Never raises.
    """
    import aiohttp
    if not version:
        return None
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.get(RELEASE_API_URL.format(version=version),
                                   headers={"Accept": "application/vnd.github+json"}) as answer:
                if answer.status != 200:
                    logger.info(f"Release notes for v{version}: GitHub answered {answer.status}")
                    return None
                data = await answer.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
        logger.info(f"Release notes for v{version} not reachable: {e}")
        return None
    body = str((data or {}).get("body") or "").strip() if isinstance(data, dict) else ""
    return body or None


def notes_for_discord(markdown: str) -> str:
    """GitHub release notes as Discord shows them well.

    The notes are written hard-wrapped at about 95 characters. GitHub joins
    those lines into paragraphs; Discord breaks at every one, so a paragraph
    came out ragged. Lines are joined back into their paragraph or list item;
    headings, list items, quotes, tables and code blocks start their own line,
    and a "---" rule, which Discord shows as three dashes, becomes a gap.
    """
    out, fenced = [], False
    for raw in markdown.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            fenced = not fenced
            out.append(line)
            continue
        if fenced:
            out.append(line)
            continue
        if stripped in ("---", "***", "___"):
            out.append("")
            continue
        starts_own_line = (not stripped or stripped.startswith(("#", "- ", "* ", "> ", "|"))
                           or re.match(r"\d+\. ", stripped))
        previous = out[-1].strip() if out else ""
        if not starts_own_line and previous and not previous.startswith(("#", "```", "|")):
            out[-1] = out[-1] + " " + stripped
        else:
            out.append(stripped if stripped.startswith(("- ", "* ")) else line)
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _cut(text: str, limit: int) -> str:
    """At most `limit` characters, cut at a paragraph (or a line) with an ellipsis."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = head.rfind("\n\n")
    if cut < limit // 2:
        cut = head.rfind("\n")
    kept = (head[:cut] if cut > 0 else head).rstrip()
    # A cut inside a code block would turn the rest of the notice - the link to
    # the full notes included - into code: close it (final check before v3.1.0)
    if kept.count("```") % 2:
        kept += "\n```"
    return kept + "\n\n…"

logger = get_module_logger('update_notifier')

class UpdateNotifier:
    """Manages update notifications for new features."""

    def __init__(self, config_dir: str = None):
        """Initialize the update notifier.

        Args:
            config_dir: Directory where update_status.json will be stored
        """
        if config_dir:
            self.config_dir = Path(config_dir)
        else:
            # Via utils/config_paths.py (DDC_CONFIG_DIR) - derived from
            # __file__ before, blind to the variable.
            from utils.config_paths import get_config_dir
            self.config_dir = get_config_dir()
            
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.status_file = self.config_dir / "update_status.json"
        # The running version, from the one source the image sets (Dockerfile ENV
        # DDC_VERSION, also read by /health and the panel footer). A literal here
        # meant the marker on disk equalled it after the first install, so the
        # notice never fired again - while its text advertised that old release.
        self.current_version = (os.environ.get("DDC_VERSION") or "").strip().lstrip("vV")

    def get_update_status(self) -> Dict[str, Any]:
        """Get current update notification status."""
        default_status = {
            "last_notified_version": None,
            "notifications_shown": []
        }

        if not self.status_file.exists():
            return default_status

        try:
            with open(self.status_file, 'r', encoding='utf-8') as f:
                stored = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading update status: {e}")
            return default_status

        # What this method promises is the shape above, not whatever happens to
        # be in the file. A file that parses used to come back untouched, so the
        # two keys were only guaranteed on the error paths - and
        # mark_notification_shown indexes status["notifications_shown"]
        # directly. A hand-edited file, or one from another schema, raised
        # KeyError there, inside send_update_notification, whose clause names
        # RuntimeError and three discord exceptions: it left that method
        # uncaught (review C65).
        if not isinstance(stored, dict):
            logger.error(f"{self.status_file.name} does not hold an object "
                         f"({type(stored).__name__}) - starting from the defaults")
            return default_status

        # Fill the gaps, keep everything else: save_update_status writes the
        # whole record back, so a key this version does not know must survive.
        status = {**default_status, **stored}
        if not isinstance(status.get("notifications_shown"), list):
            logger.error(f"notifications_shown in {self.status_file.name} is not a list "
                         f"({status.get('notifications_shown')!r}) - starting it empty")
            status["notifications_shown"] = []
        return status

    def save_update_status(self, status: Dict[str, Any]) -> bool:
        """Save update notification status."""
        try:
            # Write atomically instead of open(..., "w"): the latter truncates the
            # file on open, and json.dump writes as a stream. Measured: on a
            # serialisation error a HALF record was left behind
            # ('{\n  "last_notified_version": "2.0",\n  "notifications_shown": '),
            # and get_update_status:56-58 then falls back to the defaults - a
            # long-dismissed update notice appears again.
            # atomic_write_json serialises BEFORE opening (utils/atomic_io.py:66-69)
            # and writes with the same parameters (indent=2, ensure_ascii=False).
            atomic_write_json(self.status_file, status)
            return True
        except (IOError, OSError, PermissionError, RuntimeError, json.JSONDecodeError) as e:
            logger.error(f"Error saving update status: {e}", exc_info=True)
            return False

    def should_show_update_notification(self) -> bool:
        """Check if update notification should be shown."""
        if not self.current_version:
            # Without a version there is nothing to announce - and nothing to
            # compare against either
            return False
        status = self.get_update_status()
        if status.get("last_notified_version") != self.current_version:
            return True
        # Marked as shown - but a channel that was unreachable then is still owed
        # it, which the per-channel list below records (final check before v3.1.0:
        # the version mark alone shut them out for good). A mark without a list is
        # from before that list existed, or from a setup without control channels.
        return self.current_version in status.get("channels_notified", {})

    def channels_still_to_tell(self, channel_ids) -> list:
        """The channels that have not had THIS version's notice yet.

        One successful channel used to mark the whole version done, so a channel
        that was unreachable at that moment never got it - and a crash before the
        mark sent it to everybody a second time.
        """
        told = set(self.get_update_status().get("channels_notified", {}).get(self.current_version, []))
        return [channel_id for channel_id in channel_ids if channel_id not in told]

    def mark_notification_shown(self, channel_ids=None) -> bool:
        """Write down that this version's notice went out; True when that WORKED.

        A status file that cannot be written (the classic root-owned file) used
        to be ignored, so the notice counted as shown and was posted again on
        every start, into every channel, for ever.
        """
        status = self.get_update_status()
        status["last_notified_version"] = self.current_version
        if self.current_version not in status["notifications_shown"]:
            status["notifications_shown"].append(self.current_version)
        if channel_ids:
            told = status.setdefault("channels_notified", {}).setdefault(self.current_version, [])
            told.extend(channel_id for channel_id in channel_ids if channel_id not in told)
        if self.save_update_status(status):
            return True
        logger.error("Update notice could not be written down (%s) - it is NOT counted as shown",
                     self.status_file)
        return False

    def create_update_embed(self, notes: Optional[str] = None) -> discord.Embed:
        """The notice a new version posts once in each control channel: the version and
        where its release notes are - nothing that can go out of date.

        It used to list "new features" typed into this method long ago - the spam
        protection, the /info command, the timezones - and announced them as new for
        every release since. Found on 2026-09-28 before the v3.1.0 rebuild would have
        posted them into the operator's control channel once more.
        """
        url = RELEASE_NOTES_URL.format(version=self.current_version)
        if notes:
            # The notes themselves (fetch_release_notes), laid out for Discord
            description = (_cut(notes_for_discord(notes), NOTES_LIMIT)
                           + "\n\n" + _("Full release notes:") + f" {url}")
        else:
            description = _("DDC has been updated to version {version}. What is new is in the "
                            "release notes:").format(version=self.current_version) + f"\n{url}"
        embed = discord.Embed(
            title=_("🎉 DockerDiscordControl v{version}").format(version=self.current_version),
            description=description,
            url=url,
            color=0x00ff00
        )
        embed.set_footer(text=_("This message is only shown once • https://ddc.bot"))
        return embed

    async def send_update_notification(self, bot) -> bool:
        """Send update notification to control channels."""
        if not self.should_show_update_notification():
            logger.debug("Update notification already shown for this version")
            return False

        try:
            config = load_config()
            from services.config.channel_roles import control_channel_ids
            control_channels = control_channel_ids(config)

            if not control_channels:
                logger.info("No control channels configured - skipping update notification")
                # Mark as shown anyway to avoid repeated attempts
                self.mark_notification_shown()
                return False

            pending = self.channels_still_to_tell(control_channels)
            if not pending:
                logger.debug("Update notification already in every control channel")
                return False

            # The notes of this version, read once per notice; without them the link
            embed = self.create_update_embed(await fetch_release_notes(self.current_version))
            sent_count = 0
            told = []

            # Send to the control channels that have not had it yet
            for channel_id in pending:
                try:
                    channel = bot.get_channel(channel_id)
                    if channel:
                        await channel.send(embed=embed)
                        sent_count += 1
                        told.append(channel_id)
                        logger.info(f"Update notification sent to channel {channel_id}")
                    else:
                        logger.warning(f"Could not find channel {channel_id}")
                except (RuntimeError, asyncio.TimeoutError, discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
                    logger.error(f"Error sending update notification to channel {channel_id}: {e}", exc_info=True)

            if sent_count > 0:
                # Per channel, so one that was unreachable gets it next time
                self.mark_notification_shown(channel_ids=told)
                logger.info(f"Update notification sent to {sent_count} control channels")
                return True
            else:
                logger.error("Failed to send update notification to any channel")
                return False

        except (RuntimeError, discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
            logger.error(f"Error in send_update_notification: {e}", exc_info=True)
            return False

# Global instance
_update_notifier = None

def get_update_notifier() -> UpdateNotifier:
    """Get the global update notifier instance."""
    global _update_notifier
    if _update_notifier is None:
        _update_notifier = UpdateNotifier()
    return _update_notifier
