# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Extension initialisation for the web app."""

from __future__ import annotations

import ipaddress
import os

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from app.auth import init_limiter

TRUSTED_PROXIES_ENV = "DDC_TRUSTED_PROXIES"


def parse_trusted_proxies(value, logger):
    """Addresses and CIDR ranges from ``DDC_TRUSTED_PROXIES``.

    An entry that is not an address or range is reported and skipped: a typo
    must neither widen trust nor pass in silence.
    """
    networks = []
    for entry in (value or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.error(f"{TRUSTED_PROXIES_ENV}: '{entry}' is not an address or range - ignored")
    return networks


class TrustedProxyFix:
    """Apply :class:`ProxyFix` only to requests whose direct peer is a known proxy.

    Until v2.4.1 ProxyFix wrapped every request. It does not check who sends
    ``X-Forwarded-*``, so any client that reached the port directly chose its
    own ``remote_addr`` - and the login and setup rate limiters count by that
    address, so rotating the header escaped them (and the action log recorded
    the forged address). Now the headers are believed only from a peer on the
    trust list; with no list, from nobody.
    """

    def __init__(self, wsgi_app, networks):
        self.plain = wsgi_app
        self.proxied = ProxyFix(wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
        self.networks = networks

    def _trusted(self, peer):
        try:
            address = ipaddress.ip_address(peer)
        except ValueError:
            return False
        return any(address in network for network in self.networks)

    def __call__(self, environ, start_response):
        if self.networks and self._trusted(environ.get("REMOTE_ADDR", "")):
            return self.proxied(environ, start_response)
        return self.plain(environ, start_response)


def configure_proxy(app: Flask) -> None:
    """Believe forwarded headers only from the proxies in ``DDC_TRUSTED_PROXIES``."""
    networks = parse_trusted_proxies(os.environ.get(TRUSTED_PROXIES_ENV), app.logger)
    app.wsgi_app = TrustedProxyFix(app.wsgi_app, networks)  # type: ignore[assignment]
    if networks:
        app.logger.info(f"Forwarded headers trusted from: {', '.join(str(n) for n in networks)}")
    else:
        app.logger.info(f"Forwarded headers ignored ({TRUSTED_PROXIES_ENV} not set)")


def init_rate_limiting(app: Flask) -> None:
    """Initialise the authentication rate limiter."""
    init_limiter(app)
    app.logger.info("Rate limiting initialized for authentication")
