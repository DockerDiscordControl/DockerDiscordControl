# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                      #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Audit 2026-09, package F - startup regressions (run.py / bot.py).

F1  rejected token / missing intents keep the process + Web UI alive and
    re-exec once a new token is configured (no sys.exit restart loop)
F4  a dying web thread terminates the whole process
F10 SIGTERM handler outside py-cord's bot.run()
F11 invalid TZ falls back to UTC instead of crashing
"""

from __future__ import annotations

import logging
import signal
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import discord

import bot as bot_module
import run as run_module


class _StopLoop(Exception):
    """Raised by the fake sleep to end the otherwise infinite wait loop."""


def _runtime():
    return SimpleNamespace(logger=MagicMock(spec=logging.Logger))


def _fake_bot(exc):
    fake = MagicMock()
    fake.run.side_effect = exc
    return fake


@pytest.fixture
def no_sleep(monkeypatch):
    calls = []

    def _sleep(seconds):
        calls.append(seconds)
        if len(calls) > 50:
            raise _StopLoop()

    monkeypatch.setattr(bot_module.time, "sleep", _sleep)
    return calls


@pytest.fixture
def sigterm_spy(monkeypatch):
    spy = MagicMock()
    monkeypatch.setattr(bot_module, "install_sigterm_handler", spy)
    return spy


# --------------------------------------------------------------------------- #
# F1                                                                           #
# --------------------------------------------------------------------------- #

class TestF1LoginFailureKeepsProcessAlive:
    def test_login_failure_waits_then_reexecs_on_new_token(self, monkeypatch, no_sleep, sigterm_spy):
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        tokens = iter(["old-token", None, "new-token"])
        monkeypatch.setattr(bot_module, "_read_configured_token", lambda runtime: next(tokens))
        execv = MagicMock()
        monkeypatch.setattr(bot_module.os, "execv", execv)
        runtime = _runtime()

        # Must not raise / sys.exit - the process has to stay alive for the Web UI
        bot_module._run_bot_until_stopped(_fake_bot(discord.LoginFailure("bad")), runtime, "old-token")

        execv.assert_called_once()
        executable, argv = execv.call_args.args
        assert executable == sys.executable
        assert argv[0] == sys.executable
        assert argv[1:] == list(sys.orig_argv[1:])
        # three token checks at the recheck interval, then the short grace period
        assert no_sleep[:3] == [bot_module.TOKEN_RECHECK_INTERVAL] * 3
        # py-cord resets SIGTERM when its loop closes -> handler re-installed
        sigterm_spy.assert_called()
        logged = " ".join(str(c.args[0]) for c in runtime.logger.error.call_args_list)
        assert "Web UI" in logged

    def test_same_token_does_not_restart(self, monkeypatch, no_sleep, sigterm_spy):
        monkeypatch.setattr(bot_module, "_read_configured_token", lambda runtime: "old-token")
        execv = MagicMock()
        monkeypatch.setattr(bot_module.os, "execv", execv)

        with pytest.raises(_StopLoop):
            bot_module._run_bot_until_stopped(
                _fake_bot(discord.LoginFailure("bad")), _runtime(), "old-token"
            )
        execv.assert_not_called()

    def test_privileged_intents_required_keeps_process_alive(self, monkeypatch, no_sleep, sigterm_spy):
        # Audit R3-1: the intents are fixed in the Developer Portal (same token), so the
        # process waits (no SystemExit) and then re-executes itself to retry the login.
        monkeypatch.setenv(bot_module.INTENTS_RETRY_ENV, "0")
        monkeypatch.setattr(bot_module, "_read_configured_token", lambda runtime: "tok")
        execv = MagicMock()
        monkeypatch.setattr(bot_module.os, "execv", execv)
        runtime = _runtime()

        bot_module._run_bot_until_stopped(
            _fake_bot(discord.PrivilegedIntentsRequired(None)), runtime, "tok"
        )
        execv.assert_called_once()
        assert sum(no_sleep) >= bot_module.INTENTS_RETRY_INITIAL_DELAY
        logged = " ".join(str(c.args[0]) for c in runtime.logger.error.call_args_list)
        assert "Privileged Gateway Intents" in logged

    def test_env_token_hint(self, monkeypatch, no_sleep, sigterm_spy):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "env-token")
        monkeypatch.setattr(bot_module, "_read_configured_token", lambda runtime: "env-token")
        runtime = _runtime()
        with pytest.raises(_StopLoop):
            bot_module._run_bot_until_stopped(_fake_bot(discord.LoginFailure("bad")), runtime, "env-token")
        logged = " ".join(str(c.args[0]) for c in runtime.logger.error.call_args_list)
        assert "DISCORD_BOT_TOKEN" in logged

    def test_normal_stop_returns_without_waiting(self, monkeypatch, no_sleep, sigterm_spy):
        fake = MagicMock()
        fake.run.return_value = None
        bot_module._run_bot_until_stopped(fake, _runtime(), "tok")
        assert no_sleep == []
        sigterm_spy.assert_not_called()

    def test_restart_exits_when_exec_fails(self, monkeypatch):
        monkeypatch.setattr(bot_module.os, "execv", MagicMock(side_effect=OSError("nope")))
        with pytest.raises(SystemExit) as exc:
            bot_module._restart_process(MagicMock())
        assert exc.value.code == 1

    def test_read_configured_token_uses_fresh_config(self, monkeypatch, tmp_path):
        import pytz
        import services.config.config_service as config_service
        from app.bot.runtime import BotRuntime

        runtime = BotRuntime(
            config={},
            logger=logging.getLogger("test.pkg_f"),
            timezone=pytz.utc,
            logs_dir=tmp_path,
            dependencies=SimpleNamespace(config_service_factory=None),
        )
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "env-token")
        monkeypatch.setattr(config_service, "load_config", lambda: {})
        assert bot_module._read_configured_token(runtime) == "env-token"

        def _broken():
            raise RuntimeError("config unavailable")

        monkeypatch.setattr(config_service, "load_config", _broken)
        assert bot_module._read_configured_token(runtime) is None


# --------------------------------------------------------------------------- #
# F4                                                                           #
# --------------------------------------------------------------------------- #

class TestF4WebThreadDeathTerminatesProcess:
    @pytest.fixture
    def exits(self, monkeypatch):
        codes = []
        monkeypatch.setattr(run_module, "_terminate_process", codes.append)
        return codes

    def test_create_app_failure_terminates(self, monkeypatch, exits):
        def _boom():
            raise RuntimeError("create_app failed")

        monkeypatch.setattr(run_module, "create_app", _boom)
        run_module.start_web_server()
        assert exits == [1]

    def test_port_bind_failure_terminates(self, monkeypatch, exits):
        monkeypatch.setattr(run_module, "create_app", lambda: object())
        serve = MagicMock(side_effect=OSError(98, "Address in use"))
        monkeypatch.setattr(run_module, "serve", serve)
        monkeypatch.setattr(run_module.time, "sleep", lambda s: None)
        run_module.start_web_server()
        assert exits == [1]
        assert serve.call_count == run_module.WEB_BIND_ATTEMPTS  # audit R3-3: retried first

    def test_serve_returning_terminates(self, monkeypatch, exits):
        monkeypatch.setattr(run_module, "create_app", lambda: object())
        monkeypatch.setattr(run_module, "serve", MagicMock(return_value=None))
        run_module.start_web_server()
        assert exits == [1]


# --------------------------------------------------------------------------- #
# F10                                                                          #
# --------------------------------------------------------------------------- #

class TestF10Sigterm:
    def test_install_sigterm_handler(self):
        previous = signal.getsignal(signal.SIGTERM)
        try:
            bot_module.install_sigterm_handler()
            assert signal.getsignal(signal.SIGTERM) is bot_module._handle_sigterm
        finally:
            signal.signal(signal.SIGTERM, previous)

    def test_handler_exits_cleanly(self):
        with pytest.raises(SystemExit) as exc:
            bot_module._handle_sigterm(signal.SIGTERM, None)
        assert exc.value.code == 0

    def test_run_main_installs_handler_first(self, monkeypatch):
        order = []
        monkeypatch.setattr(run_module, "install_sigterm_handler", lambda *a: order.append("sigterm"))
        monkeypatch.setattr(
            run_module.threading, "Thread",
            lambda *a, **k: SimpleNamespace(start=lambda: order.append("web")),
        )
        monkeypatch.setattr(run_module.time, "sleep", lambda s: None)
        monkeypatch.setattr(run_module, "run_bot", lambda: order.append("bot"))
        run_module.main()
        assert order == ["sigterm", "web", "bot"]


# --------------------------------------------------------------------------- #
# F11                                                                          #
# --------------------------------------------------------------------------- #

class TestF11InvalidTimezone:
    @pytest.mark.parametrize("tz_value", ["GMT+1", "Not/AZone", "../etc/passwd", ""])
    def test_invalid_tz_falls_back_to_utc(self, monkeypatch, tz_value):
        monkeypatch.setenv("TZ", tz_value)
        logger = MagicMock(spec=logging.Logger)
        bot_module._ensure_timezone(logger)  # must not raise
        if tz_value in ("GMT+1", "Not/AZone", "../etc/passwd"):
            logger.warning.assert_called()

    def test_valid_tz(self, monkeypatch):
        monkeypatch.setenv("TZ", "Europe/Berlin")
        logger = MagicMock(spec=logging.Logger)
        bot_module._ensure_timezone(logger)
        logger.warning.assert_not_called()
