# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Translation Config Service                     #
# ============================================================================ #
"""
Service First: Configuration Management for Channel Translation.
Handles CRUD operations, validation, and persistence for channel_translations.json.
"""

import copy
import json
import logging
import threading
import uuid
import os
import re
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

from cryptography.fernet import Fernet

logger = logging.getLogger('ddc.translation_config_service')

# --- Validation Constants ---
DISCORD_SNOWFLAKE_PATTERN = re.compile(r'^\d{17,19}$')
MAX_PAIR_NAME_LENGTH = 100
MAX_TEXT_LENGTH_LIMIT = 50000
MIN_RATE_LIMIT = 1
MAX_RATE_LIMIT = 600

VALID_PROVIDERS = {'deepl', 'google', 'microsoft'}

# ISO 639-1 + DeepL extensions — covers all three provider APIs
SUPPORTED_LANGUAGES = {
    "BG": "Bulgarian", "CS": "Czech", "DA": "Danish", "DE": "German",
    "EL": "Greek", "EN": "English", "EN-GB": "English (British)",
    "EN-US": "English (American)", "ES": "Spanish", "ET": "Estonian",
    "FI": "Finnish", "FR": "French", "HU": "Hungarian", "ID": "Indonesian",
    "IT": "Italian", "JA": "Japanese", "KO": "Korean", "LT": "Lithuanian",
    "LV": "Latvian", "NB": "Norwegian (Bokmål)", "NL": "Dutch",
    "PL": "Polish", "PT": "Portuguese", "PT-BR": "Portuguese (Brazilian)",
    "PT-PT": "Portuguese (European)", "RO": "Romanian", "RU": "Russian",
    "SK": "Slovak", "SL": "Slovenian", "SV": "Swedish", "TR": "Turkish",
    "UK": "Ukrainian", "ZH": "Chinese",
}


# --- Validation ---

def validate_discord_snowflake(value: str, field_name: str) -> Tuple[bool, str]:
    """Validate a Discord Snowflake ID (17-19 digit number)."""
    if not value:
        return False, f"{field_name} is required"
    if not DISCORD_SNOWFLAKE_PATTERN.match(str(value)):
        return False, f"{field_name} must be a valid Discord ID (17-19 digits), got: {value}"
    return True, ""


def sanitize_string(value: str, max_length: int = 100) -> str:
    """Sanitize a string by removing potentially dangerous characters."""
    if not value:
        return ""
    truncated = str(value)[:max_length * 2]
    clean = truncated.replace('<', '').replace('>', '')
    return clean[:max_length].strip()


def validate_pair_data(pair_data: Dict[str, Any]) -> Tuple[bool, str, List[str]]:
    """
    Comprehensive validation of channel pair data.

    Returns:
        Tuple of (is_valid, error_message, warnings_list)
    """
    errors = []
    warnings = []

    # Name
    name = pair_data.get('name', '')
    if not name or not name.strip():
        errors.append("Pair name is required")
    elif len(name) > MAX_PAIR_NAME_LENGTH:
        errors.append(f"Pair name too long (max {MAX_PAIR_NAME_LENGTH} chars)")

    # Source Channel
    source = str(pair_data.get('source_channel_id', ''))
    valid, msg = validate_discord_snowflake(source, "Source Channel ID")
    if not valid:
        errors.append(msg)

    # Target Channel
    target = str(pair_data.get('target_channel_id', ''))
    valid, msg = validate_discord_snowflake(target, "Target Channel ID")
    if not valid:
        errors.append(msg)

    # Source != Target
    if source and target and source == target:
        errors.append("Source and target channel cannot be the same")

    # Target Language
    target_lang = pair_data.get('target_language', '')
    if not target_lang:
        errors.append("Target language is required")
    elif target_lang.upper() not in SUPPORTED_LANGUAGES:
        warnings.append(f"Language '{target_lang}' is not in the standard list — may not be supported by all providers")

    if errors:
        return False, "; ".join(errors), warnings
    return True, "", warnings


# --- Data Models ---

@dataclass
class ChannelPair:
    """A source→target channel translation mapping."""
    id: str
    name: str
    enabled: bool
    source_channel_id: str
    target_channel_id: str
    target_language: str
    source_language: Optional[str] = None  # None = auto-detect
    translate_embeds: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ChannelPair':
        return cls(
            id=data.get('id', str(uuid.uuid4())),
            name=data.get('name', 'New Pair'),
            enabled=data.get('enabled', True),
            source_channel_id=str(data.get('source_channel_id', '')),
            target_channel_id=str(data.get('target_channel_id', '')),
            target_language=data.get('target_language', 'DE'),
            source_language=data.get('source_language'),
            translate_embeds=data.get('translate_embeds', True),
            metadata=data.get('metadata', {})
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "source_channel_id": self.source_channel_id,
            "target_channel_id": self.target_channel_id,
            "target_language": self.target_language,
            "source_language": self.source_language,
            "translate_embeds": self.translate_embeds,
            "metadata": self.metadata
        }


@dataclass
class TranslationSettings:
    """Global translation settings."""
    enabled: bool = False
    provider: str = "deepl"
    api_key_env: str = "TRANSLATION_API_KEY"
    api_key_encrypted: Optional[str] = None
    deepl_api_url: str = "https://api-free.deepl.com/v2/translate"
    google_project_id: Optional[str] = None
    rate_limit_per_minute: int = 60
    max_text_length: int = 5000
    show_original_link: bool = True
    show_provider_footer: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TranslationSettings':
        # Validate provider — fall back to default on invalid values
        provider = data.get('provider', 'deepl')
        if provider not in VALID_PROVIDERS:
            provider = 'deepl'

        # Validate DeepL API URL — must be HTTPS to a known DeepL domain
        deepl_url = data.get('deepl_api_url', 'https://api-free.deepl.com/v2/translate')
        if not deepl_url.startswith(('https://api-free.deepl.com/', 'https://api.deepl.com/')):
            deepl_url = 'https://api-free.deepl.com/v2/translate'

        # Clamp numeric values to valid ranges
        rate_limit = data.get('rate_limit_per_minute', 60)
        if not isinstance(rate_limit, int) or rate_limit < MIN_RATE_LIMIT:
            rate_limit = MIN_RATE_LIMIT
        elif rate_limit > MAX_RATE_LIMIT:
            rate_limit = MAX_RATE_LIMIT

        max_text = data.get('max_text_length', 5000)
        if not isinstance(max_text, int) or max_text < 100:
            max_text = 100
        elif max_text > MAX_TEXT_LENGTH_LIMIT:
            max_text = MAX_TEXT_LENGTH_LIMIT

        return cls(
            enabled=data.get('enabled', False),
            provider=provider,
            api_key_env=data.get('api_key_env', 'TRANSLATION_API_KEY'),
            api_key_encrypted=data.get('api_key_encrypted'),
            deepl_api_url=deepl_url,
            google_project_id=data.get('google_project_id'),
            rate_limit_per_minute=rate_limit,
            max_text_length=max_text,
            show_original_link=data.get('show_original_link', True),
            show_provider_footer=data.get('show_provider_footer', True),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "api_key_env": self.api_key_env,
            "api_key_encrypted": self.api_key_encrypted,
            "deepl_api_url": self.deepl_api_url,
            "google_project_id": self.google_project_id,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "max_text_length": self.max_text_length,
            "show_original_link": self.show_original_link,
            "show_provider_footer": self.show_provider_footer
        }


@dataclass
class ConfigResult:
    """Standard result wrapper."""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None


# --- Service ---

class TranslationKeyUnreadable(RuntimeError):
    """The translation encryption key file exists but cannot be used.

    Raised instead of quietly minting a replacement: the stored API key was
    encrypted with the key in that file, so overwriting it destroys the secret
    (review C27).
    """


class TranslationConfigService:
    """Service for managing channel_translations.json configuration."""

    def __init__(self):
        try:
            self.base_dir = Path(__file__).parents[2]
        except Exception:
            self.base_dir = Path(".")

        # Via utils/config_paths.py (DDC_CONFIG_DIR) - derived from __file__
        # before: outside a DDC_CONFIG_DIR volume, and in test runs the default
        # file written below landed in the real config/.
        from utils.config_paths import get_config_dir
        self.config_file = get_config_dir() / "channel_translations.json"
        self._file_lock = threading.Lock()  # Protects read-modify-write operations
        self._key_lock = threading.Lock()   # Protects encryption key creation
        self._ensure_config_exists()
        logger.info(f"TranslationConfigService initialized: {self.config_file}")

    def _ensure_config_exists(self):
        """Ensure the config file exists with default structure."""
        if not self.config_file.exists():
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            default_config = {
                "settings": TranslationSettings().to_dict(),
                "channel_pairs": []
            }
            self._save_config_file(default_config)

    # Cached copy and the mtime it was read at (review E32).
    _cached_config: Optional[Dict[str, Any]] = None
    _cached_mtime: float = -1.0

    def _load_config_file(self) -> Dict[str, Any]:
        """Load raw JSON config from file, cached on the file's mtime.

        The cache is not a nicety. ``TranslationMonitor.on_message`` listens to
        EVERY message in every channel the bot can see and hands each one to
        ``TranslationService.process_message``, which opens with
        ``get_settings()`` and ``get_source_channel_ids()`` - two calls to this
        method - before it can decide the message has nothing to do with it.

        Measured in the running container, on a channel that is not a
        translation source at all:

            process_message: 0.20 ms per message, 2.0 file reads per message

        So every message anybody wrote anywhere on the server made DDC open and
        parse this file twice, on a bind-mounted filesystem, to find that out.
        Same sentence as review E30: a configuration read on a path that runs
        per item rather than per operation.

        Keyed on the mtime rather than a timer, so an edit from the web panel
        or by hand is picked up on the next call and nothing has to be
        invalidated by hand. A file that cannot be stat'ed is read the old way.
        """
        try:
            mtime = os.path.getmtime(self.config_file)
        except OSError:
            mtime = None

        if mtime is not None and self._cached_config is not None and mtime == self._cached_mtime:
            # A COPY, always. Every write path here does
            # `config = self._load_config_file()`, mutates it and saves it -
            # so handing out the cached object would let a save that FAILED
            # leave its change in memory, and DDC would go on believing
            # something that is not on disk. Copying a one-kilobyte dict costs
            # a fraction of the file read it replaces.
            return copy.deepcopy(self._cached_config)

        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading channel_translations.json: {e}")
            # Not cached: a corrupt file is expected to be fixed, and the next
            # call should see that rather than the fallback.
            return {"settings": TranslationSettings().to_dict(), "channel_pairs": []}

        if mtime is not None:
            self._cached_config = data
            self._cached_mtime = mtime
        return copy.deepcopy(data)

    def _save_config_file(self, data: Dict[str, Any]) -> bool:
        """Save JSON config to file atomically."""
        temp_path = None
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            temp_dir = str(self.config_file.parent)
            fd, temp_path = tempfile.mkstemp(dir=temp_dir, text=True, suffix='.json.tmp')

            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())

            if os.name == 'posix':
                os.rename(temp_path, self.config_file)
            else:
                if self.config_file.exists():
                    self.config_file.unlink()
                os.rename(temp_path, self.config_file)
            return True
        except Exception as e:
            logger.error(f"Error saving channel_translations.json: {e}", exc_info=True)
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            return False

    # --- Public API ---

    def get_settings(self) -> TranslationSettings:
        """Get global translation settings."""
        data = self._load_config_file()
        return TranslationSettings.from_dict(data.get('settings', {}))

    def update_settings(self, settings_data: Dict[str, Any]) -> ConfigResult:
        """Update global translation settings. Thread-safe."""
        # Validate BEFORE acquiring lock (fast-fail)
        provider = settings_data.get('provider', 'deepl')
        if provider not in VALID_PROVIDERS:
            return ConfigResult(success=False, error=f"Invalid provider: {provider}")
        rate_limit = settings_data.get('rate_limit_per_minute', 60)
        if not isinstance(rate_limit, int) or rate_limit < MIN_RATE_LIMIT or rate_limit > MAX_RATE_LIMIT:
            return ConfigResult(success=False, error=f"Rate limit must be between {MIN_RATE_LIMIT} and {MAX_RATE_LIMIT}")
        max_text = settings_data.get('max_text_length', 5000)
        if not isinstance(max_text, int) or max_text < 100 or max_text > MAX_TEXT_LENGTH_LIMIT:
            return ConfigResult(success=False, error=f"Max text length must be between 100 and {MAX_TEXT_LENGTH_LIMIT}")
        deepl_url = settings_data.get('deepl_api_url', 'https://api-free.deepl.com/v2/translate')
        if not deepl_url.startswith(('https://api-free.deepl.com/', 'https://api.deepl.com/')):
            return ConfigResult(success=False, error="DeepL API URL must be a valid DeepL endpoint (api-free.deepl.com or api.deepl.com)")

        with self._file_lock:
            try:
                config = self._load_config_file()
                existing_settings = config.get('settings', {})

                # Preserve api_key_encrypted — it's managed by save_api_key()
                preserved_key = existing_settings.get('api_key_encrypted')

                new_settings = TranslationSettings.from_dict(settings_data)
                new_dict = new_settings.to_dict()

                # Restore the encrypted key (never overwrite from frontend data)
                new_dict['api_key_encrypted'] = preserved_key

                config['settings'] = new_dict

                if self._save_config_file(config):
                    logger.info(f"Translation settings updated (provider={new_settings.provider})")
                    return ConfigResult(success=True, data=new_settings)
                return ConfigResult(success=False, error="Failed to save config file")
            except Exception as e:
                logger.error(f"Error updating translation settings: {e}")
                return ConfigResult(success=False, error=str(e))

    def _get_encryption_key(self) -> Fernet:
        """Get or create a stable Fernet encryption key (independent of password).

        The key is stored in config/.translation_key and persists across
        password changes, unlike the password-hash-derived key used for bot tokens.
        Thread-safe: uses _key_lock to prevent race conditions during key creation.
        """
        key_file = self.config_file.parent / ".translation_key"
        # Fast path: key file already exists (no lock needed)
        if key_file.exists():
            try:
                return Fernet(key_file.read_bytes().strip())
            except Exception as e:
                # NOT "generate a new one". The stored api_key_encrypted was
                # encrypted with the key in this very file; writing a fresh one
                # over it destroys the operator's DeepL or Google key for good,
                # and this runs on the READ path, so a permission mismatch was
                # enough to do it (review C27).
                raise TranslationKeyUnreadable(
                    f"{key_file} exists but cannot be used ({type(e).__name__}: {e}). "
                    "It is NOT being replaced - the stored API key was encrypted "
                    "with it. Fix the file's permissions or contents, or clear the "
                    "API key in the web panel and enter it again."
                ) from e

        # Slow path: the file does not exist. Locked so two callers cannot each
        # create one and the loser's key be lost.
        with self._key_lock:
            # Double-check after acquiring lock
            if key_file.exists():
                try:
                    return Fernet(key_file.read_bytes().strip())
                except Exception as e:
                    raise TranslationKeyUnreadable(
                        f"{key_file} exists but cannot be used "
                        f"({type(e).__name__}: {e})"
                    ) from e

            new_key = Fernet.generate_key()
            try:
                key_file.parent.mkdir(parents=True, exist_ok=True)
                # Atomic write via temp file + rename
                fd, temp_path = tempfile.mkstemp(
                    dir=str(key_file.parent), suffix='.key.tmp'
                )
                with os.fdopen(fd, 'wb') as f:
                    f.write(new_key)
                    f.flush()
                    os.fsync(f.fileno())
                os.rename(temp_path, str(key_file))
                os.chmod(str(key_file), 0o600)
                logger.info("Generated new translation encryption key")
            except Exception as e:
                logger.error(f"Could not save translation encryption key: {e}")
                if 'temp_path' in locals() and os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass
            return Fernet(new_key)

    def save_api_key(self, api_key: Optional[str]) -> ConfigResult:
        """Save or clear the translation API key (encrypted). Thread-safe."""
        with self._file_lock:
            try:
                config = self._load_config_file()
                settings = config.get('settings', {})

                if api_key:
                    try:
                        f = self._get_encryption_key()
                        encrypted = f.encrypt(api_key.encode()).decode()
                        settings['api_key_encrypted'] = encrypted
                    except TranslationKeyUnreadable as e:
                        # The one case where the plaintext fallback below would
                        # be the wrong answer: the key file is there and broken,
                        # so writing the secret unencrypted turns a transient
                        # problem into a plaintext secret on disk (review C27).
                        logger.error(f"Refusing to store the translation API key: {e}")
                        return ConfigResult(success=False, error=str(e))
                    except Exception as e:
                        logger.error(f"Encryption failed for translation API key: {e}")
                        # Fallback: store plaintext (user is warned via log)
                        settings['api_key_encrypted'] = api_key
                        logger.warning("Translation API key stored WITHOUT encryption")
                else:
                    # Clear the key
                    settings['api_key_encrypted'] = None

                config['settings'] = settings
                if self._save_config_file(config):
                    action = "saved" if api_key else "cleared"
                    logger.info(f"Translation API key {action}")
                    return ConfigResult(success=True)
                return ConfigResult(success=False, error="Failed to save config file")
            except Exception as e:
                logger.error(f"Error saving API key: {e}")
                return ConfigResult(success=False, error=str(e))

    def get_pairs(self) -> List[ChannelPair]:
        """Get all configured channel pairs."""
        data = self._load_config_file()
        pairs = []
        for pair_data in data.get('channel_pairs', []):
            try:
                pairs.append(ChannelPair.from_dict(pair_data))
            except Exception as e:
                logger.error(f"Skipping invalid pair data: {e}")
        return pairs

    def get_pair(self, pair_id: str) -> Optional[ChannelPair]:
        """Get a specific channel pair by ID."""
        for pair in self.get_pairs():
            if pair.id == pair_id:
                return pair
        return None

    def add_pair(self, pair_data: Dict[str, Any]) -> ConfigResult:
        """Add a new channel pair with validation. Thread-safe."""
        # Sanitise FIRST, then validate. The other way round, the validator
        # enforced "Pair name is required" on a name that the sanitiser then
        # emptied - "<<>>" passed the check and was saved as a pair with no
        # name at all (review C52).
        pair_data['name'] = sanitize_string(pair_data.get('name', ''), MAX_PAIR_NAME_LENGTH)

        is_valid, error_msg, warnings = validate_pair_data(pair_data)
        if not is_valid:
            return ConfigResult(success=False, error=f"Validation failed: {error_msg}")
        if 'id' not in pair_data or not pair_data['id']:
            pair_data['id'] = str(uuid.uuid4())
        pair_data['metadata'] = {
            "created_at": datetime.utcnow().isoformat(),
            "translation_count": 0,
            "validation_warnings": warnings
        }
        new_pair = ChannelPair.from_dict(pair_data)

        with self._file_lock:
            try:
                config = self._load_config_file()

                # Cross-pair loop detection
                existing_sources = {p.get('source_channel_id') for p in config.get('channel_pairs', [])}
                existing_targets = {p.get('target_channel_id') for p in config.get('channel_pairs', [])}
                if new_pair.target_channel_id in existing_sources:
                    logger.warning(f"Loop risk: target channel {new_pair.target_channel_id} "
                                   f"is a source in another pair")
                if new_pair.source_channel_id in existing_targets:
                    logger.warning(f"Loop risk: source channel {new_pair.source_channel_id} "
                                   f"is a target in another pair")

                config['channel_pairs'].append(new_pair.to_dict())
                if self._save_config_file(config):
                    logger.info(f"Translation pair '{new_pair.name}' created (ID: {new_pair.id})")
                    return ConfigResult(success=True, data=new_pair)
                return ConfigResult(success=False, error="Failed to save config file")
            except Exception as e:
                logger.error(f"Error adding translation pair: {e}")
                return ConfigResult(success=False, error=str(e))

    def update_pair(self, pair_id: str, pair_data: Dict[str, Any]) -> ConfigResult:
        """Update an existing channel pair. Thread-safe."""
        # Same order as add_pair, for the same reason (review C52).
        pair_data['name'] = sanitize_string(pair_data.get('name', ''), MAX_PAIR_NAME_LENGTH)

        is_valid, error_msg, warnings = validate_pair_data(pair_data)
        if not is_valid:
            return ConfigResult(success=False, error=f"Validation failed: {error_msg}")

        with self._file_lock:
            try:
                config = self._load_config_file()
                found = False

                for i, pair in enumerate(config.get('channel_pairs', [])):
                    if pair.get('id') == pair_id:
                        metadata = pair.get('metadata', {})
                        metadata['updated_at'] = datetime.utcnow().isoformat()
                        metadata['validation_warnings'] = warnings
                        pair_data['id'] = pair_id
                        pair_data['metadata'] = metadata

                        updated_pair = ChannelPair.from_dict(pair_data)
                        config['channel_pairs'][i] = updated_pair.to_dict()
                        found = True
                        break

                if not found:
                    return ConfigResult(success=False, error=f"Pair not found: {pair_id}")

                if self._save_config_file(config):
                    logger.info(f"Translation pair '{pair_data.get('name')}' updated (ID: {pair_id})")
                    return ConfigResult(success=True, data=ChannelPair.from_dict(pair_data))
                return ConfigResult(success=False, error="Failed to save config file")
            except Exception as e:
                logger.error(f"Error updating translation pair: {e}")
                return ConfigResult(success=False, error=str(e))

    def delete_pair(self, pair_id: str) -> ConfigResult:
        """Delete a channel pair by ID. Thread-safe."""
        with self._file_lock:
            try:
                config = self._load_config_file()
                original_count = len(config.get('channel_pairs', []))
                config['channel_pairs'] = [
                    p for p in config.get('channel_pairs', []) if p.get('id') != pair_id
                ]

                if len(config['channel_pairs']) == original_count:
                    return ConfigResult(success=False, error=f"Pair not found: {pair_id}")

                if self._save_config_file(config):
                    logger.info(f"Translation pair deleted (ID: {pair_id})")
                    return ConfigResult(success=True)
                return ConfigResult(success=False, error="Failed to save config file")
            except Exception as e:
                logger.error(f"Error deleting translation pair: {e}")
                return ConfigResult(success=False, error=str(e))

    def toggle_pair(self, pair_id: str) -> ConfigResult:
        """Toggle enabled state of a channel pair. Thread-safe."""
        with self._file_lock:
            try:
                config = self._load_config_file()
                for pair in config.get('channel_pairs', []):
                    if pair.get('id') == pair_id:
                        pair['enabled'] = not pair.get('enabled', True)
                        metadata = pair.setdefault('metadata', {})
                        metadata['toggled_at'] = datetime.utcnow().isoformat()
                        if self._save_config_file(config):
                            return ConfigResult(success=True, data={'enabled': pair['enabled']})
                        return ConfigResult(success=False, error="Failed to save config file")
                return ConfigResult(success=False, error=f"Pair not found: {pair_id}")
            except Exception as e:
                logger.error(f"Error toggling translation pair: {e}")
                return ConfigResult(success=False, error=str(e))

    def increment_translation_count(self, pair_id: str) -> bool:
        """Increment the translation counter for a pair. Thread-safe."""
        with self._file_lock:
            try:
                config = self._load_config_file()
                for pair in config.get('channel_pairs', []):
                    if pair.get('id') == pair_id:
                        metadata = pair.setdefault('metadata', {})
                        metadata['translation_count'] = metadata.get('translation_count', 0) + 1
                        metadata['last_translated_at'] = datetime.utcnow().isoformat()
                        return self._save_config_file(config)
                return False
            except Exception as e:
                logger.error(f"Error incrementing translation count: {e}")
                return False

    def get_source_channel_ids(self) -> set:
        """Get all enabled source channel IDs for quick lookup."""
        return {
            pair.source_channel_id
            for pair in self.get_pairs()
            if pair.enabled
        }

    def get_target_channel_ids(self) -> set:
        """Get all target channel IDs to prevent translation loops."""
        return {
            pair.target_channel_id
            for pair in self.get_pairs()
        }


# --- Thread-safe Singleton ---

_translation_config_service: Optional[TranslationConfigService] = None
_translation_config_service_lock = threading.Lock()


def get_translation_config_service() -> TranslationConfigService:
    """Thread-safe singleton getter for TranslationConfigService."""
    global _translation_config_service
    if _translation_config_service is None:
        with _translation_config_service_lock:
            if _translation_config_service is None:
                _translation_config_service = TranslationConfigService()
    return _translation_config_service
