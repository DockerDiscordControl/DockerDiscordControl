# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""The panel's login form, and the way out again.

Operator decision (2026-09-23): a real form instead of the browser's HTTP
Basic dialog, with Basic kept as a fallback so curl, scripts and the Unraid
integrations that pass -u admin:... go on working.

The form does not check the password itself. It calls the same
verify_password() every Basic request goes through, so the same 600,000
PBKDF2 rounds, the same verified-credential cache and the same rate limiter
apply, and there is one place where a password is judged.

What a successful login writes is a BINDING to the stored password hash, not
a flag - see app/auth.py. Changing the password ends every session by
construction.

Nothing here carries @auth.login_required: a login page behind the login is a
locked door with the key inside.
"""

from __future__ import annotations

import logging

from datetime import datetime

from flask import (Blueprint, current_app, jsonify, redirect, render_template,
                   request, session, url_for)

from app.auth import SESSION_AUTH_KEY, auth_limiter, password_binding, verify_password

logger = logging.getLogger("ddc.web.login")

login_bp = Blueprint("login", __name__)


def _safe_next(target: str) -> str:
    """Only a path on this host - never an open redirect.

    The same rule the second factor applies to its own next parameter.
    """
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return "/"


@login_bp.route("/login", methods=["GET"])
def login_page():
    """The form. Already logged in goes straight through, so a bookmarked
    /login is not a dead end."""
    from app.auth import session_user

    if session_user() is not None:
        return redirect(_safe_next(request.args.get("next", "/")))
    return render_template("login.html", next=request.args.get("next", "/"), error=None)


@login_bp.route("/login", methods=["POST"])
def login_submit():
    """Check the credentials and, on success, mark the session."""
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    target = _safe_next(request.form.get("next", "/"))

    # The same brake the Basic path gets. Without it the form would be the
    # softer of the two doors, which is the opposite of the point.
    if auth_limiter.is_rate_limited(request.remote_addr):
        logger.warning("Login rate limit exceeded from IP: %s", request.remote_addr)
        return render_template("login.html", next=target, error="rate_limited"), 429

    if verify_password(username, password) is None:
        # verify_password already logged the failure with the user name.
        return render_template("login.html", next=target, error="wrong"), 401

    binding = password_binding()
    if binding is None:
        # verify_password let this through on the admin/setup bootstrap, which
        # only happens while no password is configured. There is no hash to
        # bind a session to, so the only useful place is the setup page - and
        # that one is reachable without a login by design.
        return redirect("/setup")

    session[SESSION_AUTH_KEY] = binding
    session["username"] = username
    current_app.logger.info("Panel login: %s", username)
    return redirect(target)


@login_bp.route('/logout', methods=['GET', 'POST'])
def logout():
    """The way out, and it depends on how the caller got in.

    Moved here from main_routes.py on 2026-09-23 with the form login: logout
    belongs beside login, and main_routes.py was at its line ceiling.
    """
    user = session.get('username') or 'unknown'
    came_with_credentials = 'Authorization' in request.headers
    session.clear()
    current_app.logger.info("User logout: %s", user)

    if not came_with_credentials:
        # A form login: the session was the whole of it, and it is gone. Send
        # the operator to the form rather than to a 401 they cannot answer.
        return redirect(url_for('login.login_page'))

    # Basic is still a fallback (operator decision 2026-09-23), and a browser
    # replays those credentials by itself for the same realm. Clearing the
    # session would leave such a browser logged in with nothing to show for
    # it, so this caller still gets the 401 with a fresh realm - the only
    # portable way to make a browser drop what it cached.
    response = jsonify({
        'success': True,
        'message': 'Logged out. Close the browser tab to fully clear cached credentials.',
    })
    response.status_code = 401
    response.headers['WWW-Authenticate'] = f'Basic realm="DDC-logout-{int(datetime.now().timestamp())}"'
    return response
