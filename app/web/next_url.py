# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Where the panel may send a browser after a login: a path on this host, nothing else.

The login and the second factor both take a ``next`` parameter from the request
and redirect to it. Each carried its own copy of the rule "starts with / but not
with //, no backslash" - and both let ``/<TAB>/evil.example`` through
(CodeQL py/url-redirection, 2026-09-27). Werkzeug writes the tab into the
Location header unchanged, and a browser removes tabs and line breaks from a
URL before it reads it (WHATWG URL standard), so what it follows is
``//evil.example``: another host. A crafted login link would have carried the
operator to a page of the sender's choosing right after entering the password.

The rule now refuses every control character, space and backslash, and asks the
URL parser whether a scheme or a host is left.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

# Control characters, space, DEL and the backslash (which browsers read as "/").
_REFUSED = re.compile(r"[\x00-\x20\x7f\\]")


def safe_next(target: str) -> str:
    """``target`` if it is a path on this host, otherwise ``"/"``."""
    if not target or not target.startswith("/") or target.startswith("//") or _REFUSED.search(target):
        return "/"
    parts = urlsplit(target)
    if parts.scheme or parts.netloc:
        return "/"
    return target
