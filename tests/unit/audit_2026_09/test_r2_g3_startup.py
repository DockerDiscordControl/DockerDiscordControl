# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                      #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Audit 2026-09, release review round 3 - package G3 (startup / deployment).

R3-1 missing privileged intents: periodic re-exec (backoff 90 s .. 15 min) instead of
     waiting for a different token forever
R5-5 a legacy plaintext bot_config.json no longer shadows the Web UI token
R3-2 HEALTHCHECK ignores HTTP(S)_PROXY; compose does not override it
R3-3 DDC_WEB_PORT + bind retries before giving up
R3-4 unwritable logs dir only disables file logging
R3-6 psutil capped below 8
R3-7 one version source (Dockerfile ENV DDC_VERSION) for entrypoint banner and /health
"""

from __future__ import annotations

import errno
import http.server
import json
import logging
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import discord

import bot as bot_module
import run as run_module
from app.bootstrap import runtime as bootstrap_runtime
from app.bot import token as bot_token

ROOT = Path(__file__).resolve().parents[3]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


class _StopLoop(Exception):
    pass


@pytest.fixture
def fake_sleep(monkeypatch):
    calls = []

    def _sleep(seconds):
        calls.append(seconds)
        if len(calls) > 200:
            raise _StopLoop()

    monkeypatch.setattr(bot_module.time, "sleep", _sleep)
    return calls


@pytest.fixture
def execv(monkeypatch):
    spy = MagicMock()
    monkeypatch.setattr(bot_module.os, "execv", spy)
    monkeypatch.setattr(bot_module, "install_sigterm_handler", MagicMock())
    return spy


def _runtime():
    return SimpleNamespace(logger=MagicMock(spec=logging.Logger))


def _intents_bot():
    fake = MagicMock()
    fake.run.side_effect = discord.PrivilegedIntentsRequired(None)
    return fake


# --------------------------------------------------------------------------- #
# R3-1                                                                         #
# --------------------------------------------------------------------------- #

class TestR31IntentsRetry:
    def test_backoff_schedule(self):
        delays = [bot_module._intents_retry_delay(n) for n in range(7)]
        assert delays == [90, 180, 360, 720, 900, 900, 900]
        assert bot_module._intents_retry_delay(10**6) == bot_module.INTENTS_RETRY_MAX_DELAY

    @pytest.mark.parametrize("raw, expected", [("", 0), ("3", 3), ("-2", 0), ("junk", 0)])
    def test_attempt_counter_parsing(self, monkeypatch, raw, expected):
        monkeypatch.setenv(bot_module.INTENTS_RETRY_ENV, raw)
        assert bot_module._intents_retry_attempt() == expected

    def test_same_token_reexecs_after_retry_delay(self, monkeypatch, fake_sleep, execv):
        monkeypatch.setenv(bot_module.INTENTS_RETRY_ENV, "0")
        monkeypatch.setattr(bot_module, "_read_configured_token", lambda runtime: "tok")
        runtime = _runtime()

        bot_module._run_bot_until_stopped(_intents_bot(), runtime, "tok")

        execv.assert_called_once()
        waited = sum(fake_sleep)
        assert 90 <= waited < 90 + bot_module.TOKEN_RECHECK_INTERVAL
        # the next process starts with the doubled delay
        assert os.environ[bot_module.INTENTS_RETRY_ENV] == "1"
        warned = " ".join(str(c.args[0]) for c in runtime.logger.warning.call_args_list)
        assert "Retrying the Discord login" in warned

    def test_later_attempts_wait_longer(self, monkeypatch, fake_sleep, execv):
        monkeypatch.setenv(bot_module.INTENTS_RETRY_ENV, "3")
        monkeypatch.setattr(bot_module, "_read_configured_token", lambda runtime: "tok")
        bot_module._run_bot_until_stopped(_intents_bot(), _runtime(), "tok")
        assert sum(fake_sleep) >= 720
        assert os.environ[bot_module.INTENTS_RETRY_ENV] == "4"

    def test_new_token_restarts_immediately_and_resets_backoff(self, monkeypatch, fake_sleep, execv):
        monkeypatch.setenv(bot_module.INTENTS_RETRY_ENV, "4")
        tokens = iter(["tok", "new-tok"])
        monkeypatch.setattr(bot_module, "_read_configured_token", lambda runtime: next(tokens))
        bot_module._run_bot_until_stopped(_intents_bot(), _runtime(), "tok")
        execv.assert_called_once()
        assert bot_module.INTENTS_RETRY_ENV not in os.environ
        assert fake_sleep == [bot_module.TOKEN_RECHECK_INTERVAL] * 2 + [2]

    def test_login_failure_still_waits_for_a_new_token(self, monkeypatch, fake_sleep, execv):
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        monkeypatch.setattr(bot_module, "_read_configured_token", lambda runtime: "tok")
        fake = MagicMock()
        fake.run.side_effect = discord.LoginFailure("bad")
        with pytest.raises(_StopLoop):
            bot_module._run_bot_until_stopped(fake, _runtime(), "tok")
        execv.assert_not_called()

    def test_wait_messages_use_configured_port(self, monkeypatch, fake_sleep, execv):
        monkeypatch.setenv("DDC_WEB_PORT", "9480")
        monkeypatch.setenv(bot_module.INTENTS_RETRY_ENV, "0")
        monkeypatch.setattr(bot_module, "_read_configured_token", lambda runtime: "tok")
        runtime = _runtime()
        bot_module._run_bot_until_stopped(_intents_bot(), runtime, "tok")
        first = runtime.logger.warning.call_args_list[0]
        assert 9480 in first.args


# --------------------------------------------------------------------------- #
# R5-5                                                                         #
# --------------------------------------------------------------------------- #

class TestR55LegacyPlaintextToken:
    @pytest.fixture
    def legacy_dir(self, monkeypatch, tmp_path):
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "bot_config.json").write_text(json.dumps({"bot_token": "legacy-plain"}))
        # get_decrypted_bot_token reads utils.config_paths.get_config_dir()
        # (DDC_CONFIG_DIR); this used to fake the module's __file__.
        monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path / "config"))
        return tmp_path

    def _runtime(self, config, factory=None):
        return SimpleNamespace(
            logger=logging.getLogger("test.g3.token"),
            config=config,
            dependencies=SimpleNamespace(config_service_factory=factory),
        )

    def test_web_ui_token_wins_over_legacy_file(self, legacy_dir):
        runtime = self._runtime({"bot_token_decrypted_for_usage": "web-ui-token"})
        assert bot_token.get_decrypted_bot_token(runtime) == "web-ui-token"

    def test_config_service_token_wins_over_legacy_file(self, legacy_dir):
        service = MagicMock()
        service.get_config.return_value = {"bot_token_decrypted_for_usage": "svc-token"}
        runtime = self._runtime({}, factory=lambda: service)
        assert bot_token.get_decrypted_bot_token(runtime) == "svc-token"

    def test_legacy_file_is_still_a_fallback(self, legacy_dir):
        assert bot_token.get_decrypted_bot_token(self._runtime({})) == "legacy-plain"

    def test_watcher_sees_token_saved_in_web_ui(self, legacy_dir, monkeypatch):
        """The F1 watcher re-reads config.json; the legacy file must not hide the new token."""
        import pytz

        import services.config.config_service as config_service
        from app.bot.runtime import BotRuntime

        saved = {"bot_token_decrypted_for_usage": "rejected-token"}
        monkeypatch.setattr(config_service, "load_config", lambda: dict(saved))
        runtime = BotRuntime(  # _read_configured_token uses dataclasses.replace()
            config={},
            logger=logging.getLogger("test.g3.token"),
            timezone=pytz.utc,
            logs_dir=legacy_dir,
            dependencies=SimpleNamespace(config_service_factory=None),
        )
        assert bot_module._read_configured_token(runtime) == "rejected-token"
        saved["bot_token_decrypted_for_usage"] = "new-token-from-web-ui"
        assert bot_module._read_configured_token(runtime) == "new-token-from-web-ui"


# --------------------------------------------------------------------------- #
# R3-2                                                                         #
# --------------------------------------------------------------------------- #

def _healthcheck_code() -> str:
    match = re.search(r'^\s*CMD python3 -c "(.*)" \|\| exit 1$', _read("Dockerfile"), re.M)
    assert match, "HEALTHCHECK CMD not found"
    code = match.group(1)
    assert "$" not in code and "\\" not in code and '"' not in code  # no shell expansion inside
    return code


class _HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - http.server API
        status = 200 if self.path == "/health" else 404
        self.send_response(status)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


@pytest.fixture
def health_server():
    server = http.server.HTTPServer(("127.0.0.1", 0), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


class TestR32Healthcheck:
    def _run(self, env):
        base = {k: v for k, v in os.environ.items() if "proxy" not in k.lower() and k != "DDC_WEB_PORT"}
        base.update(env)
        return subprocess.run([sys.executable, "-c", _healthcheck_code()], env=base,
                              capture_output=True, text=True, timeout=30)

    def test_healthcheck_ignores_http_proxy(self, health_server):
        dead_proxy = "http://127.0.0.1:9"  # discard port: nothing listens there
        result = self._run({"DDC_WEB_PORT": str(health_server), "HTTP_PROXY": dead_proxy,
                            "http_proxy": dead_proxy, "ALL_PROXY": dead_proxy})
        assert result.returncode == 0, result.stderr

    def test_urlopen_would_have_used_the_proxy(self, health_server):
        """Guards the premise: the old urlopen form fails with the same env."""
        dead_proxy = "http://127.0.0.1:9"
        code = f"import urllib.request; urllib.request.urlopen('http://127.0.0.1:{health_server}/health', timeout=8)"
        env = {k: v for k, v in os.environ.items() if "proxy" not in k.lower()}
        env.update({"HTTP_PROXY": dead_proxy, "http_proxy": dead_proxy})
        result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode != 0

    def test_healthcheck_fails_when_nothing_listens(self, health_server):
        result = self._run({"DDC_WEB_PORT": "9"})
        assert result.returncode != 0

    @pytest.mark.parametrize("raw", ["", "  ", "abc", "0", "70000"])
    def test_invalid_port_falls_back_to_default(self, raw):
        code = _healthcheck_code().split("; u.build_opener", 1)[0] + "; print(p)"
        result = subprocess.run([sys.executable, "-c", code], env={**os.environ, "DDC_WEB_PORT": raw},
                                capture_output=True, text=True, timeout=30)
        assert result.stdout.strip() == "9374"
        assert bootstrap_runtime.get_web_port({"DDC_WEB_PORT": raw}) == 9374

    def test_compose_does_not_override_image_healthcheck(self):
        assert not re.search(r"^\s*healthcheck:", _read("docker-compose.yml"), re.M)


# --------------------------------------------------------------------------- #
# R3-3                                                                         #
# --------------------------------------------------------------------------- #

class TestR33WebPort:
    @pytest.mark.parametrize("raw, expected", [
        (None, 9374), ("", 9374), ("9480", 9480), (" 8080 ", 8080), ("65535", 65535),
        ("0", 9374), ("65536", 9374), ("-1", 9374), ("abc", 9374),
    ])
    def test_get_web_port(self, raw, expected):
        env = {} if raw is None else {"DDC_WEB_PORT": raw}
        assert bootstrap_runtime.get_web_port(env) == expected

    @pytest.fixture
    def web(self, monkeypatch):
        exits, sleeps = [], []
        monkeypatch.setattr(run_module, "_terminate_process", exits.append)
        monkeypatch.setattr(run_module, "create_app", lambda: object())
        monkeypatch.setattr(run_module.time, "sleep", sleeps.append)
        return SimpleNamespace(exits=exits, sleeps=sleeps)

    def test_serve_uses_ddc_web_port(self, monkeypatch, web):
        monkeypatch.setenv("DDC_WEB_PORT", "9480")
        serve = MagicMock(return_value=None)
        monkeypatch.setattr(run_module, "serve", serve)
        run_module.start_web_server()
        assert serve.call_args.kwargs["port"] == 9480
        assert serve.call_count == 1
        assert web.exits == [1]  # serve returning is still fatal (F4)

    def test_port_in_use_is_retried_until_free(self, monkeypatch, web):
        monkeypatch.delenv("DDC_WEB_PORT", raising=False)
        in_use = OSError(errno.EADDRINUSE, "Address in use")
        serve = MagicMock(side_effect=[in_use, in_use, None])
        monkeypatch.setattr(run_module, "serve", serve)
        run_module.start_web_server()
        assert serve.call_count == 3
        assert serve.call_args.kwargs["port"] == 9374
        assert web.sleeps == [run_module.WEB_BIND_RETRY_DELAY] * 2

    def test_other_bind_errors_are_not_retried(self, monkeypatch, web):
        serve = MagicMock(side_effect=OSError(errno.EACCES, "Permission denied"))
        monkeypatch.setattr(run_module, "serve", serve)
        run_module.start_web_server()
        assert serve.call_count == 1
        assert web.exits == [1]

    def test_documented(self):
        assert "DDC_WEB_PORT" in _read("README.md")
        assert 'Target="DDC_WEB_PORT"' in _read("templates/DockerDiscordControl.xml")


# --------------------------------------------------------------------------- #
# R3-4                                                                         #
# --------------------------------------------------------------------------- #

class TestR34UnwritableLogs:
    def _logger(self, name):
        logger = logging.getLogger(name)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        return logger

    def test_logs_path_blocked_by_a_file(self, tmp_path, caplog):
        blocked = tmp_path / "logs"
        blocked.write_text("not a directory")
        logger = self._logger("test.g3.logs.file")
        with caplog.at_level(logging.WARNING, logger=logger.name):
            bootstrap_runtime.ensure_log_files(logger, blocked)  # must not raise
        assert not any(isinstance(h, logging.FileHandler) for h in logger.handlers)
        assert "File logging disabled" in caplog.text

    @pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores file modes")
    def test_read_only_logs_dir(self, tmp_path):
        logs = tmp_path / "logs"
        logs.mkdir()
        logs.chmod(0o500)
        try:
            logger = self._logger("test.g3.logs.ro")
            bootstrap_runtime.ensure_log_files(logger, logs)  # must not raise
            assert not any(isinstance(h, logging.FileHandler) for h in logger.handlers)
        finally:
            logs.chmod(0o700)

    def test_writable_dir_still_gets_both_handlers(self, tmp_path):
        logger = self._logger("test.g3.logs.ok")
        try:
            bootstrap_runtime.ensure_log_files(logger, tmp_path)
            files = {Path(h.baseFilename).name for h in logger.handlers if isinstance(h, logging.FileHandler)}
            assert files == {"discord.log", "bot_error.log"}
        finally:
            self._logger("test.g3.logs.ok")


# --------------------------------------------------------------------------- #
# R3-6 / R3-7                                                                  #
# --------------------------------------------------------------------------- #

def test_r36_psutil_capped_below_8():
    for rel in ("requirements.prod.txt", "requirements.txt"):
        assert re.search(r"^psutil>=7\.0\.0,<8\.0\.0", _read(rel), re.M), rel


class TestR37Version:
    def _image_version(self):
        match = re.search(r'^ENV DDC_VERSION="(\d+\.\d+\.\d+)"', _read("Dockerfile"), re.M)
        assert match, "Dockerfile must set ENV DDC_VERSION"
        return match.group(1)

    def test_image_version_matches_readme(self):
        readme_version = re.search(r"^# DockerDiscordControl v(\d+\.\d+\.\d+)", _read("README.md"), re.M)
        assert readme_version and readme_version.group(1) == self._image_version()

    def test_entrypoint_reads_image_version(self):
        text = _read("scripts/entrypoint.sh")
        assert re.search(r'^VERSION="\$\{DDC_VERSION:-unknown\}"', text, re.M)
        assert not re.search(r'^VERSION="\d', text, re.M)

    def test_health_reports_image_version(self, monkeypatch):
        from flask import Flask

        from app.web import routes

        monkeypatch.setattr(routes, "load_config", lambda: {"web_ui_password_hash": "x"})
        monkeypatch.setattr(routes, "get_server_config_service",
                            lambda: SimpleNamespace(get_all_servers=lambda: []))
        app = Flask(__name__)
        routes.register_routes(app)
        client = app.test_client()

        monkeypatch.setenv("DDC_VERSION", "9.8.7")
        assert client.get("/health").get_json()["version"] == "v9.8.7"
        monkeypatch.delenv("DDC_VERSION")
        assert client.get("/health").get_json()["version"] == "unknown"
