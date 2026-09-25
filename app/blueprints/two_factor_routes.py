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
import secrets
from urllib.parse import quote

from flask import (Blueprint, Flask, Response, current_app, jsonify, redirect, render_template,
                   request, session, url_for)

from app.auth import auth, two_factor_limiter, verify_password
from services.web.two_factor_service import (TRUSTED_DEVICE_DAYS, TwoFactorStore,
                                            TwoFactorUnreadable)

logger = logging.getLogger("ddc.web.two_factor")

two_factor_bp = Blueprint("two_factor", __name__, url_prefix="/security/2fa")

SESSION_KEY = "two_factor_ok"
ISSUER = "DockerDiscordControl"
# Paths the second factor never stands in front of: the code page itself, what
# it needs to render, the container healthcheck and the first-time setup.
EXEMPT_PREFIXES = ("/static/", "/security/2fa/verify", "/health", "/setup", "/logout",
                   # The way out needs no passed second factor: it exists for
                   # somebody who cannot pass one - the authenticator is gone,
                   # or TLS was switched off. It still takes the panel password
                   # and a current code (PLAIN_HTTP_WAY_OUT below).
                   "/security/2fa/disable",
                   # The password comes first; sending an unauthenticated
                   # browser to the code page instead of the form leaves it
                   # with nothing to type.
                   "/login")


DEVICE_COOKIE = "ddc_2fa_device"


def _remembered_device_passes(store, binding: str) -> bool:
    """Whether this browser was told to be remembered, and still is.

    IT SKIPS THE SECOND FACTOR ONLY. The password check above has already
    run; this says the browser proved once, within ninety days, that it
    holds the phone.
    """
    return store.knows_device(request.cookies.get(DEVICE_COOKIE, ""), binding)


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

# THE WAY OUT IS REACHABLE WITHOUT TLS. Once the second factor is on, DDC
# answers only over HTTPS - and whoever switches TLS off afterwards would be
# locked into a factor he can no longer confirm, with no way to switch it off
# either. The route said so in a comment of its own since it was written; the
# gate below refused it first, so the promise was never kept (operator,
# 2026-09-25: "2FA must always be optional").
#
# It is NOT in ALWAYS_PLAIN: that returns before the state file is read, and an
# unreadable state file must still close everything - refusing to guess whether
# the factor is on is a separate promise, and an older one. This exemption
# skips the HTTPS requirement and nothing else.
#
# It still takes the panel password AND a current code, so it opens nothing -
# it only keeps the door out of a room whose lock is out of reach.
PLAIN_HTTP_WAY_OUT = "/security/2fa/disable"


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
        if not request.is_secure and not request.path.startswith(PLAIN_HTTP_WAY_OUT):
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
    binding = _binding()
    if not enabled or session.get(SESSION_KEY) == binding:
        return None
    # A device the operator asked to be remembered. It carries the same
    # weight as the session marker and no more: the password was checked
    # three lines up, and this only says the phone was shown here before.
    if _remembered_device_passes(TwoFactorStore(), binding):
        session[SESSION_KEY] = binding
        return None
    if _wants_json():
        return jsonify(error="second factor required"), 401
    return redirect(url_for("two_factor.verify", next=request.full_path.rstrip("?")))


def _notice_state():
    """Whether to offer the second factor, and to whom.

    ONLY TO SOMEBODY WHO IS LOGGED IN (operator, 2026-09-25). This is a context
    processor, so it runs for every template the app renders - including the
    login page, where the banner asked for something that cannot be done: "Set
    up now" goes to a page that is login_required, which answers 302 back to
    the login, and "Later" posts a dismissal into a session that does not
    exist. It also told anybody who could reach the port that this panel has no
    second factor, before they had typed anything.
    """
    from app.auth import session_user

    if session_user() is None:
        return {"two_factor": {"show": False}}
    # NOT ON THE PAGES THAT DO IT. The same lesson as the login page above,
    # one step further: these templates now use the shared shell, so the
    # notice came with them and the setup page opened by urging the reader to
    # set up the second factor - "Set up now" linking to the page they were
    # already on, and "Later" dismissing the offer they had just accepted.
    if request.blueprint == two_factor_bp.name:
        return {"two_factor": {"show": False}}
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
                           remaining=store.remaining_recovery_codes(),
                           may_remember=store.remembering_devices_allowed(),
                           remembered=store.remembered_devices(),
                           secure=request.is_secure)


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
        return render_template("two_factor.html", view="verify", next=target,
                               may_remember=TwoFactorStore().remembering_devices_allowed(),
                               secure=request.is_secure)
    if two_factor_limiter.is_rate_limited(request.remote_addr):
        logger.warning(f"Second-factor attempts rate-limited from {request.remote_addr}")
        return render_template("two_factor.html", view="verify", next=target, error="rate",
                               secure=request.is_secure), 429
    store = TwoFactorStore()
    if store.verify(request.form.get("code", "")):
        binding = _binding()
        session[SESSION_KEY] = binding
        answer = redirect(_safe_next(target))
        if request.form.get("remember_device") and store.remembering_devices_allowed():
            # The browser keeps the token, the panel keeps its hash - the
            # same split the recovery codes use, for the same reason.
            token = secrets.token_urlsafe(32)
            store.remember_device(token, binding)
            answer.set_cookie(DEVICE_COOKIE, token, max_age=TRUSTED_DEVICE_DAYS * 86400,
                              httponly=True, samesite="Lax", secure=True)
            logger.info("This browser will not be asked for a second factor for %d days",
                        TRUSTED_DEVICE_DAYS)
        return answer
    logger.warning(f"Wrong second-factor code from {request.remote_addr}")
    return render_template("two_factor.html", view="verify", next=target, error="wrong",
                           secure=request.is_secure), 401


@two_factor_bp.route("/disable", methods=["POST"])
@auth.login_required
def disable():
    # Allowed over plain HTTP too: whoever switches TLS off later must not be
    # locked into a second factor they can no longer set up.
    # The store forgets every remembered device as part of switching off, so
    # no caller has to remember to (services/web/two_factor_service.py).
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


@two_factor_bp.route("/codes.txt", methods=["POST"])
@auth.login_required
def codes_txt():
    """The recovery codes as a file, from the one screen that has them.

    THEY EXIST FOR EXACTLY ONE SCREEN. confirm_setup returns them once and the
    store keeps only sha256 of each, so this is the only chance to keep them -
    which makes the download part of how the feature works, not a convenience.

    THE ROUTE CANNOT KNOW THEM, for the same reason. So the page posts back
    what it is showing and this answers only with the codes whose hash the
    store recognises: without that check it would be a machine that turns any
    text into a file with the panel's name on it. Nothing is kept between the
    two requests - the other way was the session, which Flask signs into a
    COOKIE, and ten recovery codes have no business in a browser's jar.

    ASKED, NOT SPENT: holds_recovery_code does not consume one.
    """
    store = TwoFactorStore()
    offered = [line.strip() for line in request.form.get("codes", "").splitlines() if line.strip()]
    if not offered or not all(store.holds_recovery_code(code) for code in offered):
        logger.warning("Refused a recovery-code download that did not match the stored codes")
        return render_template("two_factor.html", view="setup_failed", secure=True), 400

    body = ("DockerDiscordControl - recovery codes\r\n"
            "https://ddc.bot\r\n\r\n"
            "Each code works once, instead of the six digits from the app.\r\n"
            "Keep this file somewhere the phone is not.\r\n\r\n"
            + "\r\n".join(offered) + "\r\n")
    return Response(body, mimetype="text/plain; charset=utf-8", headers={
        "Content-Disposition": 'attachment; filename="ddc-recovery-codes.txt"',
        "Cache-Control": "no-store",
    })


@two_factor_bp.route("/devices", methods=["POST"])
@auth.login_required
def devices():
    """Withdraw or restore the offer to remember a device.

    AN ABSENT CHECKBOX IS AN UNTICKED ONE: a browser sends nothing for a box
    it did not tick, so the form's silence means "off". Switching it off
    forgets every device already written down - the store does that, so no
    caller has to remember to.
    """
    allowed = bool(request.form.get("remember_devices_allowed"))
    TwoFactorStore().set_remembering_devices(allowed)
    logger.info("Remembering devices for %d days is now %s",
                TRUSTED_DEVICE_DAYS, "allowed" if allowed else "off - all forgotten")
    return redirect(url_for("two_factor.status"))
