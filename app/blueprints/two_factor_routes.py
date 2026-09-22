# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""The second factor in the web panel (v3.0 step 9, docs/V3_ARCHITECTURE_PLAN.md §5).

Door B of V3 §1 is the panel, reached by whoever holds its password. With 2FA
on, a correct password is not enough: every authenticated request needs a
session that has also passed a code (or a recovery code). Operator decision
2026-09-22: offered and strongly recommended, never forced - a setup dialog
with "Later" and a notice that stays while 2FA is off - and set up only over
TLS, because a code typed over plain HTTP is readable on the LAN and
replayable inside its window (V3 §5.1).
"""

from __future__ import annotations

import hashlib
import logging
from urllib.parse import quote

from flask import (Blueprint, Flask, Response, current_app, jsonify, redirect, render_template,
                   request, session, url_for)

from app.auth import auth, two_factor_limiter, verify_password
from services.web.two_factor_service import TwoFactorStore, TwoFactorUnreadable

logger = logging.getLogger("ddc.web.two_factor")

two_factor_bp = Blueprint("two_factor", __name__, url_prefix="/security/2fa")

SESSION_KEY = "two_factor_ok"
ISSUER = "DockerDiscordControl"
# Paths the second factor never stands in front of: the code page itself, what
# it needs to render, the container healthcheck and the first-time setup.
EXEMPT_PREFIXES = ("/static/", "/security/2fa/verify", "/health", "/setup", "/logout")


def _binding() -> str:
    """Ties a passed second factor to the current password: a changed password
    needs the code again."""
    from app.auth import load_config

    stored = (load_config() or {}).get("web_ui_password_hash") or ""
    return hashlib.sha256(stored.encode()).hexdigest()[:24]


def _wants_json() -> bool:
    best = request.accept_mimetypes.best
    return request.is_json or request.path.startswith("/api/") or best == "application/json"


def _safe_next(target: str) -> str:
    # Only a path on this host - never an open redirect.
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return "/"


# Answered in the clear even with 2FA on: the container healthcheck and what a
# browser needs to render the page that says why.
ALWAYS_PLAIN = ("/static/", "/health")


def _require_second_factor():
    if request.path.startswith(ALWAYS_PLAIN):
        return None
    try:
        enabled = TwoFactorStore().enabled
    except TwoFactorUnreadable as error:
        logger.error(f"SECURITY: {error} - the panel stays closed until the file is fixed or removed")
        return Response("The two-factor state cannot be read; see the DDC log.\n", status=503,
                        mimetype="text/plain")
    if enabled:
        # The session marker IS the passed second factor. Without this, a panel
        # behind a TLS-terminating proxy (DDC_TLS_MODE=off, the default) handed
        # that cookie out over the plain port as well, and took codes there too.
        current_app.config["SESSION_COOKIE_SECURE"] = True
        if not request.is_secure:
            return Response(
                "Two-factor authentication is on, so DDC answers only over HTTPS.\n"
                "Open the panel through your reverse proxy, or set DDC_TLS_MODE.\n",
                status=403, mimetype="text/plain")
    if request.path.startswith(EXEMPT_PREFIXES):
        return None
    credentials = request.authorization
    if credentials is None or credentials.type != "basic":
        return None  # the route's own login check answers
    if not verify_password(credentials.username, credentials.password):
        return None  # wrong password: the route's own 401
    if not enabled or session.get(SESSION_KEY) == _binding():
        return None
    if _wants_json():
        return jsonify(error="second factor required"), 401
    return redirect(url_for("two_factor.verify", next=request.full_path.rstrip("?")))


def _notice_state():
    try:
        store = TwoFactorStore()
        enabled = store.enabled
        dismissed = store.prompt_dismissed()
    except TwoFactorUnreadable:
        return {"two_factor": {"show": False}}
    return {"two_factor": {
        "show": not enabled,
        "prompt": not enabled and not dismissed,
        "secure": request.is_secure,
    }}


def install_two_factor(app: Flask) -> None:
    """Stand the second factor in front of every authenticated request."""
    app.before_request(_require_second_factor)
    app.context_processor(_notice_state)


# -- pages ------------------------------------------------------------------

@two_factor_bp.route("", methods=["GET"])
@auth.login_required
def status():
    store = TwoFactorStore()
    return render_template("two_factor.html", view="status", enabled=store.enabled,
                           remaining=store.remaining_recovery_codes(), secure=request.is_secure)


@two_factor_bp.route("/setup", methods=["POST"])
@auth.login_required
def setup():
    if not request.is_secure:
        return render_template("two_factor.html", view="needs_tls", secure=False), 403
    store = TwoFactorStore()
    if store.enabled:
        return render_template("two_factor.html", view="status", enabled=True,
                               remaining=store.remaining_recovery_codes(), secure=True), 409
    secret = store.begin_setup()
    user = auth.current_user() or "admin"
    uri = f"otpauth://totp/{quote(ISSUER)}:{quote(user)}?secret={secret}&issuer={quote(ISSUER)}"
    import segno

    qr_svg = segno.make(uri, error="m").svg_inline(scale=5, dark="#000000", light="#ffffff")
    return render_template("two_factor.html", view="setup", qr_svg=qr_svg, secret=secret, secure=True)


@two_factor_bp.route("/confirm", methods=["POST"])
@auth.login_required
def confirm():
    if not request.is_secure:
        return render_template("two_factor.html", view="needs_tls", secure=False), 403
    codes = TwoFactorStore().confirm_setup(request.form.get("code", ""))
    if not codes:
        return render_template("two_factor.html", view="setup_failed", secure=True), 400
    session[SESSION_KEY] = _binding()
    logger.info("Two-factor authentication switched ON for the web panel")
    return render_template("two_factor.html", view="recovery_codes", codes=codes, secure=True)


@two_factor_bp.route("/verify", methods=["GET", "POST"])
@auth.login_required
def verify():
    target = request.values.get("next", "")
    if request.method == "GET":
        return render_template("two_factor.html", view="verify", next=target, secure=request.is_secure)
    if two_factor_limiter.is_rate_limited(request.remote_addr):
        logger.warning(f"Second-factor attempts rate-limited from {request.remote_addr}")
        return render_template("two_factor.html", view="verify", next=target, error="rate",
                               secure=request.is_secure), 429
    if TwoFactorStore().verify(request.form.get("code", "")):
        session[SESSION_KEY] = _binding()
        return redirect(_safe_next(target))
    logger.warning(f"Wrong second-factor code from {request.remote_addr}")
    return render_template("two_factor.html", view="verify", next=target, error="wrong",
                           secure=request.is_secure), 401


@two_factor_bp.route("/disable", methods=["POST"])
@auth.login_required
def disable():
    # Allowed over plain HTTP too: whoever switches TLS off later must not be
    # locked into a second factor they can no longer set up.
    if TwoFactorStore().disable(request.form.get("code", "")):
        session.pop(SESSION_KEY, None)
        logger.warning("Two-factor authentication switched OFF for the web panel")
        return redirect(url_for("two_factor.status"))
    return render_template("two_factor.html", view="status", enabled=True, error="wrong",
                           remaining=TwoFactorStore().remaining_recovery_codes(),
                           secure=request.is_secure), 401


@two_factor_bp.route("/dismiss", methods=["POST"])
@auth.login_required
def dismiss():
    TwoFactorStore().dismiss_prompt()
    return redirect(_safe_next(request.form.get("next", "")))
