# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""A second way for the watchdog to raise an alarm: a webhook (operator, 2026-09-26).

WHY. Every watchdog notice went to Discord and nowhere else. With the bot
token revoked, Discord down, or the bot kicked from the server, a container
could die and nobody would hear of it - the heartbeat only covers DDC itself
dying. One URL closes that.

WHAT THE URL IS, read from its shape (operator decision: "generic webhook +
ntfy"):
  * ntfy  (host contains "ntfy", e.g. https://ntfy.sh/my-topic) - the text as
    the body, the title in the Title header: what ntfy's apps show;
  * Gotify (path ends in /message with a token= query) - {title, message,
    priority} as JSON;
  * anything else - a JSON POST {source, title, message, container, kind}
    for Home Assistant, n8n, Node-RED and friends.

WHEN: "fallback" (the default) only when Discord did not take the notice;
"always" beside Discord. Watchdog notices only - the message rules answer in
the channel they were triggered from.

The URL can carry a secret (a topic, a token), so the log names its host only.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("ddc.alert_webhook")

MODES = ("fallback", "always")
TIMEOUT_SECONDS = 10


def valid_url(url: str) -> bool:
    """Empty (off), or an http(s) URL with a host."""
    if not url:
        return True
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.hostname) and len(url) <= 2048


def kind_of(url: str) -> str:
    parsed = urlparse(url)
    if parsed.path.rstrip("/").endswith("/message") and "token" in parse_qs(parsed.query):
        return "gotify"
    if "ntfy" in (parsed.hostname or ""):
        return "ntfy"
    return "generic"


def build_request(url: str, title: str, message: str, container: str = "",
                  kind: str = "") -> Tuple[Dict[str, str], bytes]:
    """(headers, body) for this URL's kind."""
    flavour = kind_of(url)
    if flavour == "ntfy":
        # Header values must be latin-1; an emoji in a title would break the
        # request, so the title is kept plain and the body carries the rest.
        safe_title = title.encode("latin-1", "replace").decode("latin-1")
        return ({"Title": safe_title, "Tags": "warning", "Priority": "high"},
                message.encode("utf-8"))
    if flavour == "gotify":
        return ({"Content-Type": "application/json"},
                json.dumps({"title": title, "message": message, "priority": 8}).encode("utf-8"))
    return ({"Content-Type": "application/json"},
            json.dumps({"source": "DockerDiscordControl", "title": title, "message": message,
                        "container": container, "kind": kind}).encode("utf-8"))


def send(url: str, title: str, message: str, container: str = "", kind: str = "",
         post=None) -> bool:
    """POST the alarm. True on a 2xx answer. Blocking - callers use a thread."""
    if not url or not valid_url(url):
        return False
    headers, body = build_request(url, title, message, container, kind)
    if post is None:
        import requests

        post = requests.post
    host = urlparse(url).hostname
    try:
        answer = post(url, data=body, headers=headers, timeout=TIMEOUT_SECONDS)
    except Exception as error:  # noqa: BLE001 - an alarm path must not raise
        logger.warning(f"Alarm webhook to {host} failed: {type(error).__name__}")
        return False
    if 200 <= getattr(answer, "status_code", 0) < 300:
        return True
    logger.warning(f"Alarm webhook to {host} answered {getattr(answer, 'status_code', '?')}")
    return False


def settings_of(global_settings: Dict) -> Tuple[Optional[str], str]:
    url = (global_settings or {}).get("alert_webhook_url") or None
    mode = (global_settings or {}).get("alert_webhook_mode") or "fallback"
    return url, mode if mode in MODES else "fallback"
