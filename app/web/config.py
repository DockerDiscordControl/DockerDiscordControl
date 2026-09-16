# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Configuration helpers for the Flask web application."""

from __future__ import annotations

import logging
import os
import secrets
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Mapping, MutableMapping, Optional

logger = logging.getLogger(__name__)

def _is_dev_environment(env: Mapping[str, str]) -> bool:
    """Return True if the runtime looks like a dev environment."""
    flask_env = (env.get("FLASK_ENV") or "").strip().lower()
    if flask_env in ("development", "dev"):
        return True
    flask_debug = (env.get("FLASK_DEBUG") or "").strip().lower()
    return flask_debug in ("1", "true", "yes")


DEFAULTS = {
    # Own cookie name: cookies are shared by all ports of a host, so the Flask default
    # "session" would be overwritten by any other Flask app on the same host/IP - which
    # invalidates the CSRF token and makes the next save fail.
    "SESSION_COOKIE_NAME": "ddc_session",
    # Stays False: most installs are plain HTTP on the LAN, where a Secure cookie is never sent.
    "SESSION_COOKIE_SECURE": False,
    "SESSION_COOKIE_HTTPONLY": True,
    # Lax instead of Strict: opening DDC from a link on another site (Discord web, a dashboard)
    # must not start a new session that breaks saving in the other open tabs. Lax still
    # withholds the cookie on cross-site POSTs, and every POST needs the CSRF token anyway.
    "SESSION_COOKIE_SAMESITE": "Lax",
    # Flask-WTF's strict Referer check on HTTPS rejects saves behind many reverse proxies
    # (Referer stripped, or host rewritten); the token check stays in place.
    "WTF_CSRF_SSL_STRICT": False,
    "PERMANENT_SESSION_LIFETIME": timedelta(days=7),
    "SESSION_REFRESH_EACH_REQUEST": False,
    # CSRF tokens live as long as the session instead of Flask-WTF's 1h default, otherwise
    # saving from a config page left open for over an hour fails with "CSRF token expired".
    "WTF_CSRF_TIME_LIMIT": None,
    "JSON_AS_ASCII": False,
    "DOCKER_SOCKET": "/var/run/docker.sock",
    "LOG_LEVEL": "INFO",
    "HOST_DOCKER_PATH": "/usr/bin/docker",
    "TEMPLATES_AUTO_RELOAD": False,
}

# Persistent secret key file in the config directory, used when no (secure)
# FLASK_SECRET_KEY is supplied so sessions survive restarts.
SECRET_KEY_FILENAME = ".flask_secret_key"

# Placeholder / predictable values that must never be used as the signing key:
# the old dev fallback and the "<prefix><epoch seconds>" keys that older
# rebuild.sh / start.sh versions passed when no .env file existed.
_INSECURE_SECRET_KEYS = frozenset({"fallback-secret-key-for-dev-if-not-set"})
_INSECURE_SECRET_KEY_PREFIXES = ("temporary-dev-key-", "dev-only-")


def _is_insecure_secret_key(candidate: str) -> bool:
    return (
        not candidate
        or candidate in _INSECURE_SECRET_KEYS
        or candidate.startswith(_INSECURE_SECRET_KEY_PREFIXES)
    )


def _load_or_create_secret_key(key_file: Path) -> str:
    """Return the persistent key stored in ``key_file``, creating it once if missing.

    Falls back to a random in-memory key (sessions reset on restart) when the
    file can't be read or written.
    """
    try:
        existing = key_file.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except FileNotFoundError:
        pass
    except (OSError, UnicodeDecodeError) as e:
        logger.warning(
            "Could not read Flask secret key file %s (%s); using a random key for this run "
            "(sessions will not survive a restart)", key_file, e
        )
        return secrets.token_hex(32)

    key = secrets.token_hex(32)
    tmp_path = None
    try:
        key_file.parent.mkdir(parents=True, exist_ok=True)
        # mkstemp creates the file with mode 0600; os.replace makes the write atomic.
        fd, tmp_path = tempfile.mkstemp(
            prefix=f"{SECRET_KEY_FILENAME}.", suffix=".tmp", dir=str(key_file.parent)
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(key)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, key_file)
        tmp_path = None
        logger.info("Generated a new persistent Flask secret key in %s", key_file)
    except OSError as e:
        logger.warning(
            "Could not write Flask secret key file %s (%s); using a random key for this run "
            "(sessions will not survive a restart)", key_file, e
        )
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    return key


def resolve_secret_key(env: Mapping[str, str], key_file: Optional[Path] = None) -> str:
    """Return a robust Flask secret key.

    A real ``FLASK_SECRET_KEY`` from the environment is always used as-is. When it
    is empty or a known placeholder/predictable value, the key is loaded from
    ``key_file`` (created once with a random value). Without ``key_file`` a random
    per-process key is returned.
    """
    candidate = env.get("FLASK_SECRET_KEY", "").strip()
    if not _is_insecure_secret_key(candidate):
        return candidate
    if candidate:
        logger.warning("Ignoring placeholder/predictable FLASK_SECRET_KEY value")
    if key_file is None:
        return secrets.token_hex(32)
    return _load_or_create_secret_key(key_file)


def build_config(env: Mapping[str, str], overrides: Optional[Mapping[str, object]] = None) -> MutableMapping[str, object]:
    """Construct the Flask configuration dictionary."""
    config: MutableMapping[str, object] = dict(DEFAULTS)
    # Robust absolute path relative to project root
    try:
        project_root = Path(__file__).parents[2]
    except Exception:
        project_root = Path(".")

    # Same DDC_CONFIG_DIR override as ConfigService, so tests and special
    # deployments keep the secret key file out of the real config directory.
    config_dir_override = (env.get("DDC_CONFIG_DIR") or "").strip()
    config_dir = Path(config_dir_override) if config_dir_override else project_root / "config"

    config.update(
        SECRET_KEY=resolve_secret_key(env, config_dir / SECRET_KEY_FILENAME),
        DOCKER_SOCKET=env.get("DOCKER_SOCKET", DEFAULTS["DOCKER_SOCKET"]),
        LOG_LEVEL=env.get("LOG_LEVEL", DEFAULTS["LOG_LEVEL"]),
        HOST_DOCKER_PATH=env.get("HOST_DOCKER_PATH", DEFAULTS["HOST_DOCKER_PATH"]),
        CONFIG_FILE=str(project_root / "config" / "config.json"),
    )

    if _is_dev_environment(env):
        config["TEMPLATES_AUTO_RELOAD"] = True

    if overrides:
        config.update(overrides)

    return config
