# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Translation Service                            #
# ============================================================================ #
"""
Service First: The "Brain" of the Channel Translation System.
Handles provider abstraction, message translation, embed posting, and rate limiting.
"""

import asyncio
import io
import logging
import os
import re
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field

import aiohttp
import discord

from .translation_config_service import (
    get_translation_config_service,
    ChannelPair,
    TranslationSettings,
    VALID_PROVIDERS,
)

logger = logging.getLogger('ddc.translation_service')

# Maximum tracked message IDs for loop prevention
MAX_TRACKED_MESSAGES = 10000

# Discord embed description limit
DISCORD_EMBED_DESC_LIMIT = 4096

# Retry settings
MAX_RETRIES = 2
RETRY_BACKOFF_BASE = 1.0  # seconds

# Allowed DeepL API URL prefixes (SSRF protection)
ALLOWED_DEEPL_HOSTS = (
    "https://api-free.deepl.com/",
    "https://api.deepl.com/",
)


# --- Data Models ---

@dataclass
class TranslationContext:
    """Context for a message to be translated."""
    message_id: str
    channel_id: str
    guild_id: str
    author_name: str
    author_avatar_url: str
    content: str
    embed_texts: List[str] = field(default_factory=list)
    embed_images: List[str] = field(default_factory=list)  # URLs from embed.image / embed.thumbnail
    attachment_urls: List[Dict[str, str]] = field(default_factory=list)  # [{url, filename, content_type}]

    @property
    def message_link(self) -> str:
        return f"https://discord.com/channels/{self.guild_id}/{self.channel_id}/{self.message_id}"

    @property
    def full_text(self) -> str:
        """Combined content and embed text."""
        parts = []
        if self.content:
            parts.append(self.content)
        parts.extend(self.embed_texts)
        return "\n\n".join(parts)


@dataclass
class TranslationResult:
    """Result from a translation API call."""
    success: bool
    translated_text: Optional[str] = None
    detected_language: Optional[str] = None
    provider: Optional[str] = None
    error: Optional[str] = None
    characters_used: int = 0


# --- Helpers ---

def _safe_truncate(text: str, max_length: int) -> str:
    """Truncate text to max_length characters (Unicode code points)."""
    if len(text) <= max_length:
        return text
    return text[:max_length]


def _normalize_language_code(code: str, provider: str) -> str:
    """Normalize language code for the target provider."""
    if not code:
        return code
    code = code.strip()
    if provider == 'deepl':
        # DeepL uses uppercase: EN-GB, DE, FR
        return code.upper()
    else:
        # Google and Microsoft use lowercase 2-letter: en, de, fr
        return code.lower()[:2]


# --- Provider Interface ---

class TranslationProvider(ABC):
    """Abstract base for translation API providers."""

    @abstractmethod
    async def translate(self, text: str, target_lang: str,
                        source_lang: Optional[str] = None,
                        session: Optional[aiohttp.ClientSession] = None) -> TranslationResult:
        ...

    @abstractmethod
    def get_name(self) -> str:
        ...


class DeepLProvider(TranslationProvider):
    """DeepL Translation API v2."""

    def __init__(self, api_key: str, api_url: str = "https://api-free.deepl.com/v2/translate"):
        self.api_key = api_key
        # Validate API URL against allowed hosts (SSRF protection)
        if not any(api_url.startswith(host) for host in ALLOWED_DEEPL_HOSTS):
            logger.warning(f"DeepL API URL '{api_url}' not in allowed list, using default")
            api_url = "https://api-free.deepl.com/v2/translate"
        self.api_url = api_url

    def get_name(self) -> str:
        return "DeepL"

    async def translate(self, text: str, target_lang: str,
                        source_lang: Optional[str] = None,
                        session: Optional[aiohttp.ClientSession] = None) -> TranslationResult:
        payload: Dict[str, Any] = {
            "text": [text],
            "target_lang": _normalize_language_code(target_lang, 'deepl'),
        }
        if source_lang:
            payload["source_lang"] = _normalize_language_code(source_lang, 'deepl')

        headers = {
            "Authorization": f"DeepL-Auth-Key {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            owns_session = session is None
            if owns_session:
                session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15.0))
            try:
                async with session.post(self.api_url, json=payload, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        translations = data.get("translations", [])
                        if translations:
                            t = translations[0]
                            return TranslationResult(
                                success=True,
                                translated_text=t.get("text", ""),
                                detected_language=t.get("detected_source_language"),
                                provider=self.get_name(),
                                characters_used=len(text)
                            )
                        return TranslationResult(success=False, error="No translations in response",
                                                 provider=self.get_name())
                    elif resp.status == 403:
                        return TranslationResult(success=False, error="Invalid API key",
                                                 provider=self.get_name())
                    elif resp.status == 429:
                        return TranslationResult(success=False, error="Rate limit exceeded (API-side)",
                                                 provider=self.get_name())
                    elif resp.status == 456:
                        return TranslationResult(success=False, error="Quota exceeded",
                                                 provider=self.get_name())
                    else:
                        body = await resp.text()
                        return TranslationResult(
                            success=False,
                            error=f"HTTP {resp.status}: {body[:200]}",
                            provider=self.get_name()
                        )
            finally:
                if owns_session:
                    await session.close()
        except aiohttp.ClientError as e:
            return TranslationResult(success=False, error=f"Connection error: {e}",
                                     provider=self.get_name())
        except asyncio.TimeoutError:
            return TranslationResult(success=False, error="Request timed out",
                                     provider=self.get_name())


class GoogleTranslateProvider(TranslationProvider):
    """Google Cloud Translation API v2."""

    API_URL = "https://translation.googleapis.com/language/translate/v2"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def get_name(self) -> str:
        return "Google"

    async def translate(self, text: str, target_lang: str,
                        source_lang: Optional[str] = None,
                        session: Optional[aiohttp.ClientSession] = None) -> TranslationResult:
        # Google v2 uses query params for auth, form data for content
        query_params = {
            "key": self.api_key,
        }
        form_data = {
            "q": text,
            "target": _normalize_language_code(target_lang, 'google'),
            "format": "text",
        }
        if source_lang:
            form_data["source"] = _normalize_language_code(source_lang, 'google')

        try:
            owns_session = session is None
            if owns_session:
                session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15.0))
            try:
                async with session.post(self.API_URL, params=query_params, data=form_data) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        translations = data.get("data", {}).get("translations", [])
                        if translations:
                            t = translations[0]
                            return TranslationResult(
                                success=True,
                                translated_text=t.get("translatedText", ""),
                                detected_language=t.get("detectedSourceLanguage"),
                                provider=self.get_name(),
                                characters_used=len(text)
                            )
                        return TranslationResult(success=False, error="No translations in response",
                                                 provider=self.get_name())
                    elif resp.status == 403:
                        return TranslationResult(success=False, error="Invalid API key or quota exceeded",
                                                 provider=self.get_name())
                    elif resp.status == 429:
                        return TranslationResult(success=False, error="Rate limit exceeded (API-side)",
                                                 provider=self.get_name())
                    else:
                        body = await resp.text()
                        return TranslationResult(
                            success=False,
                            error=f"HTTP {resp.status}: {body[:200]}",
                            provider=self.get_name()
                        )
            finally:
                if owns_session:
                    await session.close()
        except aiohttp.ClientError as e:
            return TranslationResult(success=False, error=f"Connection error: {e}",
                                     provider=self.get_name())
        except asyncio.TimeoutError:
            return TranslationResult(success=False, error="Request timed out",
                                     provider=self.get_name())


class MicrosoftTranslatorProvider(TranslationProvider):
    """Microsoft Translator Text API v3."""

    API_URL = "https://api.cognitive.microsofttranslator.com/translate"

    def __init__(self, api_key: str, region: str = "global"):
        self.api_key = api_key
        self.region = region

    def get_name(self) -> str:
        return "Microsoft"

    async def translate(self, text: str, target_lang: str,
                        source_lang: Optional[str] = None,
                        session: Optional[aiohttp.ClientSession] = None) -> TranslationResult:
        params = {
            "api-version": "3.0",
            "to": _normalize_language_code(target_lang, 'microsoft'),
        }
        if source_lang:
            params["from"] = _normalize_language_code(source_lang, 'microsoft')

        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Ocp-Apim-Subscription-Region": self.region,
            "Content-Type": "application/json",
        }
        body = [{"text": text}]

        try:
            owns_session = session is None
            if owns_session:
                session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15.0))
            try:
                async with session.post(self.API_URL, params=params,
                                        json=body, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data and isinstance(data, list) and data[0].get("translations"):
                            t = data[0]["translations"][0]
                            detected = None
                            if data[0].get("detectedLanguage"):
                                detected = data[0]["detectedLanguage"].get("language")
                            return TranslationResult(
                                success=True,
                                translated_text=t.get("text", ""),
                                detected_language=detected,
                                provider=self.get_name(),
                                characters_used=len(text)
                            )
                        return TranslationResult(success=False, error="No translations in response",
                                                 provider=self.get_name())
                    elif resp.status in (401, 403):
                        return TranslationResult(success=False, error="Invalid API key",
                                                 provider=self.get_name())
                    elif resp.status == 429:
                        return TranslationResult(success=False, error="Rate limit exceeded (API-side)",
                                                 provider=self.get_name())
                    else:
                        body_text = await resp.text()
                        return TranslationResult(
                            success=False,
                            error=f"HTTP {resp.status}: {body_text[:200]}",
                            provider=self.get_name()
                        )
            finally:
                if owns_session:
                    await session.close()
        except aiohttp.ClientError as e:
            return TranslationResult(success=False, error=f"Connection error: {e}",
                                     provider=self.get_name())
        except asyncio.TimeoutError:
            return TranslationResult(success=False, error="Request timed out",
                                     provider=self.get_name())


# --- Rate Limiter ---

class SlidingWindowRateLimiter:
    """Thread-safe sliding window rate limiter."""

    def __init__(self):
        self._timestamps: deque = deque()
        self._lock = threading.Lock()

    def check(self, limit_per_minute: int) -> bool:
        """Return True if request is allowed. Thread-safe."""
        now = time.monotonic()
        window_start = now - 60.0

        with self._lock:
            # Remove expired timestamps
            while self._timestamps and self._timestamps[0] < window_start:
                self._timestamps.popleft()

            if len(self._timestamps) >= limit_per_minute:
                return False

            self._timestamps.append(now)
            return True


# --- Main Service ---

class TranslationService:
    """Core logic for Channel Translation."""

    def __init__(self):
        self.config_service = get_translation_config_service()
        self._translated_message_ids: deque = deque(maxlen=MAX_TRACKED_MESSAGES)
        self._translated_ids_lock = threading.Lock()
        self._rate_limiter = SlidingWindowRateLimiter()
        self._consecutive_failures: Dict[str, int] = {}
        self._auto_disabled_pairs: set = set()
        self._state_lock = threading.Lock()  # Protects failures + auto_disabled
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock = threading.Lock()
        logger.info("TranslationService initialized")

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create a shared aiohttp session."""
        with self._session_lock:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=15.0)
                )
            return self._session

    async def close(self):
        """Close the shared HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def _resolve_api_key(self, settings: TranslationSettings) -> Optional[str]:
        """Resolve API key: env var > encrypted config > plaintext config fallback."""
        # 1. Environment variable (highest priority)
        key = os.environ.get(settings.api_key_env, '').strip()
        if key:
            return key
        if not settings.api_key_encrypted:
            return None
        # 2. Try to decrypt using the stable translation encryption key
        stored_key = settings.api_key_encrypted
        if stored_key.startswith('gAAAAA'):
            try:
                fernet = self.config_service._get_encryption_key()
                decrypted = fernet.decrypt(stored_key.encode()).decode()
                if decrypted:
                    return decrypted
            except Exception as e:
                logger.warning(f"Could not decrypt translation API key: {e}")
                logger.error("Translation API key decryption failed — "
                             "re-enter the key in the Web UI to re-encrypt")
                return None
        # 3. Plaintext fallback (stored unencrypted if no encryption key existed)
        return stored_key

    def _get_provider(self, settings: TranslationSettings, api_key: str) -> TranslationProvider:
        """Create a provider instance based on settings."""
        if settings.provider == 'google':
            return GoogleTranslateProvider(api_key)
        elif settings.provider == 'microsoft':
            return MicrosoftTranslatorProvider(api_key)
        else:
            return DeepLProvider(api_key, settings.deepl_api_url)

    def mark_as_translated(self, message_id: str):
        """Mark a message ID as posted by translation (for loop prevention)."""
        with self._translated_ids_lock:
            self._translated_message_ids.append(message_id)

    def is_translated_message(self, message_id: str) -> bool:
        """Check if this message was posted by the translation system."""
        with self._translated_ids_lock:
            return message_id in self._translated_message_ids

    async def _translate_with_retry(self, provider: TranslationProvider, text: str,
                                    target_lang: str, source_lang: Optional[str],
                                    session: aiohttp.ClientSession) -> TranslationResult:
        """Translate with retry logic for transient failures."""
        last_result = None
        for attempt in range(MAX_RETRIES + 1):
            result = await provider.translate(text, target_lang, source_lang, session)
            if result.success:
                return result
            last_result = result
            # Only retry on transient errors (timeouts, connection errors, 429 rate limits)
            if result.error and any(kw in result.error for kw in
                                     ("timed out", "Connection error", "Rate limit exceeded (API-side)")):
                if attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF_BASE * (2 ** attempt)
                    logger.info(f"Retrying translation in {wait:.1f}s (attempt {attempt + 1}/{MAX_RETRIES})")
                    await asyncio.sleep(wait)
                    continue
            # Non-retryable error (auth, quota, bad request) — stop immediately
            break
        return last_result

    async def process_message(self, context: TranslationContext, bot_instance) -> List[str]:
        """
        Main entry point: Check all channel pairs, translate if source matches.

        Returns:
            List of translated pair names
        """
        settings = self.config_service.get_settings()
        if not settings.enabled:
            return []

        # Quick check: is this channel even a source channel?
        source_ids = self.config_service.get_source_channel_ids()
        if context.channel_id not in source_ids:
            return []

        # Never translate messages from target channels (loop prevention)
        target_ids = self.config_service.get_target_channel_ids()
        if context.channel_id in target_ids:
            return []

        api_key = self._resolve_api_key(settings)
        if not api_key:
            logger.warning("No translation API key configured — skipping translation")
            return []

        provider = self._get_provider(settings, api_key)
        session = await self._get_session()
        pairs = self.config_service.get_pairs()
        translated_pairs = []

        for pair in pairs:
            if not pair.enabled:
                continue
            if pair.source_channel_id != context.channel_id:
                continue
            with self._state_lock:
                if pair.id in self._auto_disabled_pairs:
                    continue

            # Build text to translate
            text = self._build_translation_text(context, pair)
            has_attachments = bool(context.attachment_urls)

            if not text.strip() and not has_attachments:
                continue

            if text.strip():
                # Unicode-safe truncation
                text = _safe_truncate(text, settings.max_text_length)

                # Rate limit
                if not self._rate_limiter.check(settings.rate_limit_per_minute):
                    logger.warning("Translation rate limit exceeded — skipping")
                    continue

                # Translate with retry
                result = await self._translate_with_retry(
                    provider, text, pair.target_language, pair.source_language, session
                )
            else:
                # Attachment-only message — no text to translate, forward as-is
                result = TranslationResult(
                    success=True, translated_text="", provider="passthrough"
                )

            if result.success:
                with self._state_lock:
                    self._consecutive_failures.pop(pair.id, None)
                await self._post_translation(bot_instance, pair, context, result, settings)
                self.config_service.increment_translation_count(pair.id)
                translated_pairs.append(pair.name)
                if result.provider == "passthrough":
                    logger.info(f"Forwarded attachments for pair '{pair.name}'")
                else:
                    logger.info(f"Translated message for pair '{pair.name}' "
                                f"({result.detected_language} -> {pair.target_language})")
            else:
                with self._state_lock:
                    fail_count = self._consecutive_failures.get(pair.id, 0) + 1
                    self._consecutive_failures[pair.id] = fail_count
                    auto_disabled = fail_count >= 5
                    if auto_disabled:
                        self._auto_disabled_pairs.add(pair.id)
                logger.warning(f"Translation failed for pair '{pair.name}': {result.error} "
                               f"(failure {fail_count}/5)")
                if auto_disabled:
                    logger.error(f"Auto-disabled pair '{pair.name}' after 5 consecutive failures")

        return translated_pairs

    def _build_translation_text(self, context: TranslationContext, pair: ChannelPair) -> str:
        """Build the text to translate based on pair settings."""
        parts = []
        if context.content:
            parts.append(context.content)
        if pair.translate_embeds and context.embed_texts:
            parts.extend(context.embed_texts)
        return "\n\n".join(parts)

    async def _post_translation(self, bot, pair: ChannelPair,
                                context: TranslationContext,
                                result: TranslationResult,
                                settings: Optional['TranslationSettings'] = None):
        """Post compact translation embed to target channel."""
        try:
            target_channel = bot.get_channel(int(pair.target_channel_id))
            if not target_channel:
                logger.error(f"Target channel {pair.target_channel_id} not found for pair '{pair.name}'")
                return

            # Check permissions
            if hasattr(target_channel, 'guild') and target_channel.guild:
                perms = target_channel.permissions_for(target_channel.guild.me)
                if not perms.send_messages:
                    logger.error(f"No send permission in target channel {pair.target_channel_id}")
                    return

            # Build compact embed
            translated_text = _safe_truncate(result.translated_text, DISCORD_EMBED_DESC_LIMIT) if result.translated_text else ""
            embed = discord.Embed(
                description=translated_text or None,
                color=0x3498db
            )
            embed.set_author(
                name=context.author_name,
                icon_url=context.author_avatar_url
            )

            # Set first image attachment as embed image, fall back to original embed images
            image_set = False
            for att in context.attachment_urls:
                ct = att.get('content_type', '')
                if ct.startswith('image/') and not image_set:
                    embed.set_image(url=att['url'])
                    image_set = True
                    break

            # If no attachment image, use image from original embed (link previews etc.)
            if not image_set and context.embed_images:
                embed.set_image(url=context.embed_images[0])
                image_set = True

            show_link = settings.show_original_link if settings else True
            show_footer = settings.show_provider_footer if settings else True

            if show_link:
                embed.add_field(
                    name="\u200b",  # Zero-width space for invisible field name
                    value=f"\U0001F517 [Original]({context.message_link})",
                    inline=False
                )

            if show_footer:
                if result.provider == "passthrough":
                    embed.set_footer(text=f"Forwarded from #{pair.name}")
                else:
                    detected = result.detected_language or "?"
                    embed.set_footer(
                        text=f"Translated from {detected} to {pair.target_language} via {result.provider}"
                    )

            # Extract embeddable URLs from translated text so Discord shows previews
            # (URLs inside embed descriptions don't get auto-previewed by Discord)
            extra_content = ""
            if translated_text:
                url_pattern = re.compile(
                    r'https?://(?:www\.)?(?:youtube\.com/watch\S+|youtu\.be/\S+'
                    r'|twitter\.com/\S+|x\.com/\S+'
                    r'|twitch\.tv/\S+|clips\.twitch\.tv/\S+'
                    r'|reddit\.com/\S+|streamable\.com/\S+'
                    r'|vimeo\.com/\S+)'
                )
                urls = url_pattern.findall(translated_text)
                for url in urls:
                    if len(extra_content) + len(url) + 1 <= 1900:
                        extra_content += url + "\n"

            # Download and re-upload attachments as real discord.File objects
            # so Discord shows proper video players and image previews
            files = []
            session = await self._get_session()
            for att in context.attachment_urls:
                ct = att.get('content_type', '')
                filename = att.get('filename', 'file')
                if ct.startswith('video/') or (ct.startswith('image/') and not image_set):
                    try:
                        async with session.get(att['url'], timeout=aiohttp.ClientTimeout(total=30)) as resp:
                            if resp.status == 200:
                                data = await resp.read()
                                # Discord file upload limit: 25MB for most servers
                                if len(data) <= 25 * 1024 * 1024:
                                    files.append(discord.File(io.BytesIO(data), filename=filename))
                                else:
                                    line = att['url'] + "\n"
                                    if len(extra_content) + len(line) <= 1900:
                                        extra_content += line
                    except Exception as e:
                        logger.warning(f"Could not download attachment {filename}: {e}")
                        line = att['url'] + "\n"
                        if len(extra_content) + len(line) <= 1900:
                            extra_content += line
                elif not ct.startswith('image/'):
                    # Non-media files: link with filename
                    line = f"📎 [{filename}]({att['url']})\n"
                    if len(extra_content) + len(line) <= 1900:
                        extra_content += line

            send_kwargs = {
                'content': extra_content.strip() or None,
                'embed': embed,
            }
            if files:
                send_kwargs['files'] = files

            sent_msg = await target_channel.send(**send_kwargs)
            self.mark_as_translated(str(sent_msg.id))

        except discord.Forbidden:
            logger.error(f"Forbidden: Cannot send to channel {pair.target_channel_id}")
        except discord.HTTPException as e:
            logger.error(f"Discord HTTP error posting translation: {e}")
        except Exception as e:
            logger.error(f"Error posting translation for pair '{pair.name}': {e}", exc_info=True)

    async def test_translation(self, text: str, target_lang: str,
                               source_lang: Optional[str] = None) -> TranslationResult:
        """Test translation with current settings (used by Web UI)."""
        settings = self.config_service.get_settings()
        api_key = self._resolve_api_key(settings)
        if not api_key:
            return TranslationResult(success=False, error="No API key configured")

        # Apply same truncation as real translation
        text = _safe_truncate(text, settings.max_text_length)

        provider = self._get_provider(settings, api_key)
        session = await self._get_session()
        return await provider.translate(text, target_lang, source_lang, session)

    def reset_auto_disabled(self, pair_id: str):
        """Re-enable an auto-disabled pair (called when user re-enables in UI)."""
        with self._state_lock:
            self._auto_disabled_pairs.discard(pair_id)
            self._consecutive_failures.pop(pair_id, None)


# --- Thread-safe Singleton ---

_translation_service: Optional[TranslationService] = None
_translation_service_lock = threading.Lock()


def get_translation_service() -> TranslationService:
    """Thread-safe singleton getter for TranslationService."""
    global _translation_service
    if _translation_service is None:
        with _translation_service_lock:
            if _translation_service is None:
                _translation_service = TranslationService()
    return _translation_service
