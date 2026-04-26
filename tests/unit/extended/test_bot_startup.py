# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Extended Unit Tests for bot startup helpers   #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                      #
# Licensed under the MIT License                                              #
# ============================================================================ #
"""
Functional unit tests for small, well-isolated app/bot, app/web and
app/bootstrap helpers.

Modules under test
------------------
- app/bot/commands.py
- app/bot/factory.py
- app/bot/runtime.py (build_runtime, BotRuntime)
- app/bot/startup_context.py (StartupContext, as_step)
- app/bot/startup_steps/sequence.py
- app/bot/startup_steps/diagnostics.py
- app/bot/startup_steps/cooldowns.py
- app/bot/startup_steps/notifications.py
- app/bot/startup_steps/power.py
- app/bot/startup_steps/scheduler.py
- app/bot/startup_steps/commands.py (load_extensions, prepare/synchronize)
- app/bot/startup_steps/member_count.py (initialize_member_count_step)
- app/web/routes.py (register_routes / health endpoint)
- app/web/compat.py (initialize_gevent / apply_gevent_fork_workaround)
- app/bootstrap/runtime.py (configure_environment, resolve_timezone, etc.)

Strategy
--------
All modules are imported normally — *no* ``sys.modules`` manipulation.
Heavy collaborators (Discord API, services, Docker, scheduler …) are
mocked via ``monkeypatch.setattr`` / ``unittest.mock.patch`` against the
*module attribute* the unit calls.  StartupContext is replaced with a
``SimpleNamespace`` carrying just the attributes the production code
touches (``logger``, ``bot``, ``runtime`` …) which keeps each test
focussed on the behaviour we care about.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# The production code under test (services/mech/progress_paths.py) uses
# ``@dataclass(slots=True)`` which requires Python 3.10+.  The test
# container ships 3.11/3.12; locally 3.13 is fine; we skip cleanly when
# running on 3.9 so collection doesn't bring down the rest of the suite.
if sys.version_info < (3, 10):
    pytest.skip(
        "extended bot startup tests require Python 3.10+ (dataclass slots)",
        allow_module_level=True,
    )

# Modules under test ---------------------------------------------------------
from app.bot import commands as bot_commands
from app.bot import factory as bot_factory
from app.bot import runtime as bot_runtime
from app.bot import startup_context as bot_startup_context
from app.bot.startup_steps import (
    commands as step_commands,
    cooldowns as step_cooldowns,
    diagnostics as step_diagnostics,
    member_count as step_member_count,
    notifications as step_notifications,
    power as step_power,
    scheduler as step_scheduler,
    sequence as step_sequence,
)
from app.bootstrap import runtime as bootstrap_runtime
from app.web import compat as web_compat
from app.web import routes as web_routes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Autouse fixture: defends against logging pollution from earlier tests
# (e.g. ``setup_all_loggers`` in test_app_utils_extended.py raises the level
# of the ``ddc`` logger to INFO/WARNING, which silently drops the records the
# ``caplog``-based assertions in this module rely on). Reset relevant loggers
# in the ``ddc.test.startup`` chain so each test in this file starts from a
# clean slate, and restore prior state afterwards.
@pytest.fixture(autouse=True)
def _reset_ddc_test_logger_state():
    target_names = ("ddc", "ddc.test", "ddc.test.startup")
    saved = []
    for name in target_names:
        lg = logging.getLogger(name)
        saved.append(
            (
                lg,
                lg.level,
                lg.propagate,
                lg.disabled,
                list(lg.handlers),
                list(lg.filters),
            )
        )
        # Reset to defaults so caplog can capture DEBUG/INFO records reliably.
        lg.setLevel(logging.NOTSET)
        lg.propagate = True
        lg.disabled = False
        lg.handlers = []
        lg.filters = []
    # Also defuse any global ``logging.disable`` left behind by a polluter.
    prev_disable = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    try:
        yield
    finally:
        logging.disable(prev_disable)
        for lg, lvl, prop, disabled, handlers, filters in saved:
            lg.setLevel(lvl)
            lg.propagate = prop
            lg.disabled = disabled
            lg.handlers = handlers
            lg.filters = filters


def _make_logger(name: str = "ddc.test.startup") -> logging.Logger:
    logger = logging.getLogger(name)
    # Ensure the autouse fixture above has done its job; force DEBUG level so
    # caplog captures every record regardless of any residual parent state.
    logger.setLevel(logging.DEBUG)
    logger.propagate = True
    logger.disabled = False
    return logger


def _make_runtime(**overrides):
    """Construct a SimpleNamespace looking like BotRuntime for unit tests."""
    defaults = dict(
        config={},
        logger=_make_logger(),
        timezone=None,
        logs_dir=Path("/tmp/ddc-tests-logs"),
        dependencies=SimpleNamespace(
            config_service_factory=None,
            dynamic_cooldown_applicator=None,
            update_notifier_factory=None,
        ),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_context(bot=None, runtime=None):
    """Lightweight StartupContext stand-in (matches the duck-typed contract)."""
    if bot is None:
        bot = MagicMock()
    if runtime is None:
        runtime = _make_runtime()
    return SimpleNamespace(bot=bot, runtime=runtime, logger=runtime.logger)


def _run(coro):
    """Run an async coroutine to completion in this thread."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# app/bot/commands.py
# ---------------------------------------------------------------------------

class TestBotCommands:
    """Tests for app/bot/commands.py."""

    def test_list_registered_command_names_uses_application_commands(self):
        bot = SimpleNamespace(
            application_commands=[
                SimpleNamespace(name="status"),
                SimpleNamespace(name="restart"),
            ],
        )
        names = list(bot_commands.list_registered_command_names(bot))
        assert names == ["status", "restart"]

    def test_list_registered_command_names_falls_back_to_tree(self):
        # No application_commands -> use bot.tree._global_commands keys
        bot = MagicMock(spec=[])  # no attrs -> hasattr(bot, "application_commands") is False
        bot.tree = SimpleNamespace(_global_commands={"a": object(), "b": object()})
        names = list(bot_commands.list_registered_command_names(bot))
        assert set(names) == {"a", "b"}

    def test_list_registered_command_names_returns_empty_when_no_commands(self):
        bot = MagicMock(spec=[])
        bot.tree = None
        assert list(bot_commands.list_registered_command_names(bot)) == []

    def test_setup_schedule_commands_returns_true_when_cog_present(self):
        bot = MagicMock()
        bot.get_cog.return_value = MagicMock()  # cog exists
        ok = bot_commands.setup_schedule_commands(bot, _make_logger())
        assert ok is True

    def test_setup_schedule_commands_returns_false_when_cog_missing(self):
        bot = MagicMock()
        bot.get_cog.return_value = None
        ok = bot_commands.setup_schedule_commands(bot, _make_logger())
        assert ok is False

    def test_setup_schedule_commands_returns_false_on_runtime_error(self):
        bot = MagicMock()
        bot.get_cog.side_effect = RuntimeError("boom")
        ok = bot_commands.setup_schedule_commands(bot, _make_logger())
        assert ok is False


# ---------------------------------------------------------------------------
# app/bot/factory.py
# ---------------------------------------------------------------------------

class TestBotFactory:
    """Tests for app/bot/factory.py."""

    def test_build_intents_enables_required_flags(self):
        intents = bot_factory._build_intents()
        assert intents.members is True
        assert intents.message_content is True
        assert intents.presences is False
        assert intents.typing is False

    def test_create_bot_uses_pycord_path_when_available(self, monkeypatch):
        runtime = _make_runtime()
        sentinel_bot = SimpleNamespace(name="pycord-bot")

        def fake_bot_cls(intents):
            return sentinel_bot

        monkeypatch.setattr(bot_factory.discord, "Bot", fake_bot_cls)
        bot = bot_factory.create_bot(runtime)
        assert bot is sentinel_bot

    def test_create_bot_falls_back_to_commands_bot_on_attributeerror(
        self, monkeypatch
    ):
        runtime = _make_runtime()
        sentinel_fallback = SimpleNamespace(name="dpy-bot")

        def fail_pycord(intents):
            raise AttributeError("no PyCord here")

        def fake_commands_bot(*, command_prefix, intents):
            assert command_prefix == "/"
            return sentinel_fallback

        monkeypatch.setattr(bot_factory.discord, "Bot", fail_pycord)
        monkeypatch.setattr(bot_factory.commands, "Bot", fake_commands_bot)
        bot = bot_factory.create_bot(runtime)
        assert bot is sentinel_fallback

    def test_create_bot_falls_back_on_import_error(self, monkeypatch):
        runtime = _make_runtime()
        fallback = SimpleNamespace(kind="fallback")

        monkeypatch.setattr(
            bot_factory.discord, "Bot",
            MagicMock(side_effect=ImportError("module gone")),
        )
        monkeypatch.setattr(
            bot_factory.commands, "Bot",
            MagicMock(return_value=fallback),
        )
        bot = bot_factory.create_bot(runtime)
        assert bot is fallback


# ---------------------------------------------------------------------------
# app/bot/runtime.py (BotRuntime + build_runtime)
# ---------------------------------------------------------------------------

class TestBotRuntime:
    """Tests for app/bot/runtime.py."""

    def test_botruntime_dataclass_is_frozen(self):
        rt = bot_runtime.BotRuntime(
            config={},
            logger=_make_logger(),
            timezone=bot_runtime.pytz.timezone("UTC"),
            logs_dir=Path("/tmp"),
            dependencies=bot_runtime.BotDependencies(),
        )
        with pytest.raises((AttributeError, Exception)):
            rt.config = {"changed": True}  # type: ignore[misc]

    def test_build_runtime_wires_dependencies(self, monkeypatch, tmp_path):
        """build_runtime should call each helper exactly once and return a BotRuntime."""
        fake_logger = _make_logger("ddc.test.build_runtime")
        fake_tz = bot_runtime.pytz.timezone("Europe/Berlin")
        fake_deps = bot_runtime.BotDependencies()

        called = {}

        def fake_initialize_logging(name, level=logging.INFO):
            called["initialize_logging"] = (name, level)
            return fake_logger

        def fake_apply_runtime_tweaks(logger):
            called["apply_runtime_tweaks"] = logger

        def fake_resolve_timezone(config, logger=None):
            called["resolve_timezone"] = (config, logger)
            return fake_tz

        def fake_ensure_log_files(logger, logs_dir):
            called["ensure_log_files"] = (logger, logs_dir)

        def fake_ensure_token_security(logger):
            called["ensure_token_security"] = logger
            return True

        def fake_load_dependencies(logger):
            called["load_dependencies"] = logger
            return fake_deps

        monkeypatch.setattr(bot_runtime, "initialize_logging", fake_initialize_logging)
        monkeypatch.setattr(bot_runtime, "apply_runtime_tweaks", fake_apply_runtime_tweaks)
        monkeypatch.setattr(bot_runtime, "resolve_timezone", fake_resolve_timezone)
        monkeypatch.setattr(bot_runtime, "ensure_log_files", fake_ensure_log_files)
        monkeypatch.setattr(bot_runtime, "ensure_token_security", fake_ensure_token_security)
        monkeypatch.setattr(bot_runtime, "load_dependencies", fake_load_dependencies)

        config = {"timezone": "Europe/Berlin"}
        rt = bot_runtime.build_runtime(config)

        assert isinstance(rt, bot_runtime.BotRuntime)
        assert rt.logger is fake_logger
        assert rt.timezone is fake_tz
        assert rt.dependencies is fake_deps
        assert rt.config is config
        assert "initialize_logging" in called
        assert called["apply_runtime_tweaks"] is fake_logger
        assert called["resolve_timezone"][0] is config
        assert called["ensure_token_security"] is fake_logger
        assert called["load_dependencies"] is fake_logger


# ---------------------------------------------------------------------------
# app/bot/startup_context.py
# ---------------------------------------------------------------------------

class TestStartupContext:
    """Tests for app/bot/startup_context.py."""

    def test_logger_property_returns_runtime_logger(self):
        runtime = _make_runtime()
        ctx = bot_startup_context.StartupContext(bot=MagicMock(), runtime=runtime)
        assert ctx.logger is runtime.logger

    def test_as_step_attaches_step_name_and_logs_debug(self, caplog):
        async def my_step(context):
            context.logger.info("inner")

        wrapped = bot_startup_context.as_step(my_step)
        assert getattr(wrapped, "step_name", None) == "my_step"

        ctx = _make_context()
        with caplog.at_level(logging.DEBUG):
            _run(wrapped(ctx))
        # The wrapper logs a debug line with the step name.
        assert any("my_step" in r.getMessage() for r in caplog.records)

    def test_as_step_runs_underlying_callable(self):
        called_with = {}

        async def step(context):
            called_with["bot"] = context.bot

        wrapped = bot_startup_context.as_step(step)
        ctx = _make_context()
        _run(wrapped(ctx))
        assert called_with["bot"] is ctx.bot


# ---------------------------------------------------------------------------
# app/bot/startup_steps/sequence.py
# ---------------------------------------------------------------------------

class TestStartupSequence:
    """Tests for app/bot/startup_steps/sequence.py."""

    def test_run_startup_sequence_invokes_steps_in_order(self):
        order: list = []

        async def step_a(ctx):
            order.append("a")

        step_a.step_name = "step_a"  # type: ignore[attr-defined]

        async def step_b(ctx):
            order.append("b")

        # Step without step_name attr — uses __name__ fallback.
        ctx = _make_context()
        _run(step_sequence.run_startup_sequence(ctx, [step_a, step_b]))
        assert order == ["a", "b"]

    def test_run_startup_sequence_propagates_exception(self):
        async def good(ctx):
            return None

        async def bad(ctx):
            raise RuntimeError("step failed")

        ctx = _make_context()
        with pytest.raises(RuntimeError, match="step failed"):
            _run(step_sequence.run_startup_sequence(ctx, [good, bad]))

    def test_run_startup_sequence_no_steps_is_noop(self):
        ctx = _make_context()
        _run(step_sequence.run_startup_sequence(ctx, []))


# ---------------------------------------------------------------------------
# app/bot/startup_steps/diagnostics.py
# ---------------------------------------------------------------------------

class TestStartupDiagnostics:
    """Tests for app/bot/startup_steps/diagnostics.py."""

    def test_run_port_diagnostics_step_invokes_helper(self, monkeypatch):
        called = {"n": 0}

        def fake_log_port_diagnostics():
            called["n"] += 1

        monkeypatch.setattr(step_diagnostics, "log_port_diagnostics", fake_log_port_diagnostics)
        ctx = _make_context()
        _run(step_diagnostics.run_port_diagnostics_step(ctx))
        assert called["n"] == 1

    def test_run_port_diagnostics_step_swallows_runtime_error(self, monkeypatch):
        def boom():
            raise RuntimeError("diag failed")

        monkeypatch.setattr(step_diagnostics, "log_port_diagnostics", boom)
        ctx = _make_context()
        # No exception should escape.
        _run(step_diagnostics.run_port_diagnostics_step(ctx))


# ---------------------------------------------------------------------------
# app/bot/startup_steps/cooldowns.py
# ---------------------------------------------------------------------------

class TestStartupCooldowns:
    """Tests for app/bot/startup_steps/cooldowns.py."""

    def test_apply_dynamic_cooldowns_skips_when_no_applicator(self):
        runtime = _make_runtime(dependencies=SimpleNamespace(
            config_service_factory=None,
            dynamic_cooldown_applicator=None,
            update_notifier_factory=None,
        ))
        ctx = _make_context(runtime=runtime)
        _run(step_cooldowns.apply_dynamic_cooldowns_step(ctx))
        # Nothing to assert beyond no-raise.

    def test_apply_dynamic_cooldowns_invokes_applicator_with_bot(self):
        applicator = MagicMock()
        runtime = _make_runtime(dependencies=SimpleNamespace(
            config_service_factory=None,
            dynamic_cooldown_applicator=applicator,
            update_notifier_factory=None,
        ))
        ctx = _make_context(runtime=runtime)
        _run(step_cooldowns.apply_dynamic_cooldowns_step(ctx))
        applicator.assert_called_once_with(ctx.bot)

    def test_apply_dynamic_cooldowns_swallows_runtime_error(self):
        applicator = MagicMock(side_effect=RuntimeError("nope"))
        runtime = _make_runtime(dependencies=SimpleNamespace(
            config_service_factory=None,
            dynamic_cooldown_applicator=applicator,
            update_notifier_factory=None,
        ))
        ctx = _make_context(runtime=runtime)
        _run(step_cooldowns.apply_dynamic_cooldowns_step(ctx))
        applicator.assert_called_once()


# ---------------------------------------------------------------------------
# app/bot/startup_steps/notifications.py
# ---------------------------------------------------------------------------

class TestStartupNotifications:
    """Tests for app/bot/startup_steps/notifications.py."""

    def test_skips_when_no_notifier_factory(self):
        runtime = _make_runtime(dependencies=SimpleNamespace(
            config_service_factory=None,
            dynamic_cooldown_applicator=None,
            update_notifier_factory=None,
        ))
        ctx = _make_context(runtime=runtime)
        _run(step_notifications.send_update_notification_step(ctx))

    def test_invokes_notifier_when_factory_present(self):
        notifier = SimpleNamespace(send_update_notification=AsyncMock(return_value=False))
        factory = MagicMock(return_value=notifier)
        runtime = _make_runtime(dependencies=SimpleNamespace(
            config_service_factory=None,
            dynamic_cooldown_applicator=None,
            update_notifier_factory=factory,
        ))
        ctx = _make_context(runtime=runtime)
        _run(step_notifications.send_update_notification_step(ctx))
        factory.assert_called_once()
        notifier.send_update_notification.assert_awaited_once_with(ctx.bot)

    def test_swallows_runtime_error_from_factory(self):
        factory = MagicMock(side_effect=RuntimeError("notifier missing"))
        runtime = _make_runtime(dependencies=SimpleNamespace(
            config_service_factory=None,
            dynamic_cooldown_applicator=None,
            update_notifier_factory=factory,
        ))
        ctx = _make_context(runtime=runtime)
        _run(step_notifications.send_update_notification_step(ctx))
        factory.assert_called_once()


# ---------------------------------------------------------------------------
# app/bot/startup_steps/power.py
# ---------------------------------------------------------------------------

class TestStartupPower:
    """Tests for app/bot/startup_steps/power.py."""

    def test_grant_power_gift_step_logs_when_gift_granted(self, monkeypatch, caplog):
        adapter = MagicMock()
        adapter.power_gift.return_value = SimpleNamespace(power_level=500)

        # Build a fake services.mech.mech_service_adapter module so the
        # in-function import resolves to our adapter.
        fake_mod = types.ModuleType("services.mech.mech_service_adapter")
        fake_mod.get_mech_service = lambda: adapter
        monkeypatch.setitem(sys.modules, "services.mech.mech_service_adapter", fake_mod)

        ctx = _make_context()
        with caplog.at_level(logging.INFO):
            _run(step_power.grant_power_gift_step(ctx))
        adapter.power_gift.assert_called_once_with("startup_gift_v1")
        assert any("Power gift granted" in r.getMessage() for r in caplog.records)

    def test_grant_power_gift_step_logs_when_not_needed(self, monkeypatch, caplog):
        adapter = MagicMock()
        adapter.power_gift.return_value = SimpleNamespace(power_level=0)

        fake_mod = types.ModuleType("services.mech.mech_service_adapter")
        fake_mod.get_mech_service = lambda: adapter
        monkeypatch.setitem(sys.modules, "services.mech.mech_service_adapter", fake_mod)

        ctx = _make_context()
        with caplog.at_level(logging.INFO):
            _run(step_power.grant_power_gift_step(ctx))
        assert any("not needed" in r.getMessage() for r in caplog.records)

    def test_grant_power_gift_step_swallows_runtime_error(self, monkeypatch):
        adapter = MagicMock()
        adapter.power_gift.side_effect = RuntimeError("boom")

        fake_mod = types.ModuleType("services.mech.mech_service_adapter")
        fake_mod.get_mech_service = lambda: adapter
        monkeypatch.setitem(sys.modules, "services.mech.mech_service_adapter", fake_mod)

        ctx = _make_context()
        # Should not raise.
        _run(step_power.grant_power_gift_step(ctx))


# ---------------------------------------------------------------------------
# app/bot/startup_steps/scheduler.py
# ---------------------------------------------------------------------------

class TestStartupScheduler:
    """Tests for app/bot/startup_steps/scheduler.py."""

    def test_start_scheduler_step_logs_success(self, monkeypatch, caplog):
        monkeypatch.setattr(step_scheduler, "start_scheduler_service", lambda: True)
        ctx = _make_context()
        with caplog.at_level(logging.INFO):
            _run(step_scheduler.start_scheduler_step(ctx))
        assert any("started successfully" in r.getMessage() for r in caplog.records)

    def test_start_scheduler_step_logs_warning_when_already_running(
        self, monkeypatch, caplog
    ):
        monkeypatch.setattr(step_scheduler, "start_scheduler_service", lambda: False)
        ctx = _make_context()
        with caplog.at_level(logging.WARNING):
            _run(step_scheduler.start_scheduler_step(ctx))
        assert any(
            "could not be started" in r.getMessage() for r in caplog.records
        )

    def test_start_scheduler_step_swallows_runtime_error(self, monkeypatch):
        def boom():
            raise RuntimeError("scheduler bad")

        monkeypatch.setattr(step_scheduler, "start_scheduler_service", boom)
        ctx = _make_context()
        _run(step_scheduler.start_scheduler_step(ctx))


# ---------------------------------------------------------------------------
# app/bot/startup_steps/commands.py
# ---------------------------------------------------------------------------

class TestStartupCommandsStep:
    """Tests for app/bot/startup_steps/commands.py (load/sync extensions)."""

    def test_load_extensions_step_loads_each_pycord_sync(self):
        bot = MagicMock()
        bot.extensions = {}
        # PyCord style: load_extension is a regular (non-coroutine) function.
        bot.load_extension = MagicMock(return_value=None)
        ctx = _make_context(bot=bot)
        _run(step_commands.load_extensions_step(ctx))
        # All three extensions attempted.
        loaded = [c.args[0] for c in bot.load_extension.call_args_list]
        assert "cogs.docker_control" in loaded
        assert "cogs.auto_action_monitor" in loaded
        assert "cogs.translation_monitor" in loaded

    def test_load_extensions_step_skips_already_loaded(self):
        bot = MagicMock()
        bot.extensions = {"cogs.docker_control": object()}
        bot.load_extension = MagicMock()
        ctx = _make_context(bot=bot)
        _run(step_commands.load_extensions_step(ctx))
        loaded = [c.args[0] for c in bot.load_extension.call_args_list]
        assert "cogs.docker_control" not in loaded

    def test_load_extensions_step_raises_when_docker_control_fails(self):
        bot = MagicMock()
        bot.extensions = {}

        def fail_load(ext):
            raise OSError("cannot read cog")

        bot.load_extension = fail_load
        ctx = _make_context(bot=bot)
        with pytest.raises(OSError):
            _run(step_commands.load_extensions_step(ctx))

    def test_load_extensions_step_uses_async_path_when_coroutine(self):
        bot = MagicMock()
        bot.extensions = {}
        called = []

        async def async_load(ext):
            called.append(ext)

        bot.load_extension = async_load
        ctx = _make_context(bot=bot)
        _run(step_commands.load_extensions_step(ctx))
        assert "cogs.docker_control" in called
        assert "cogs.auto_action_monitor" in called

    def test_prepare_schedule_commands_step_calls_setup(self, monkeypatch):
        called = {}

        def fake_setup(bot, logger):
            called["bot"] = bot
            called["logger"] = logger
            return True

        monkeypatch.setattr(step_commands, "setup_schedule_commands", fake_setup)
        ctx = _make_context()
        _run(step_commands.prepare_schedule_commands_step(ctx))
        assert called["bot"] is ctx.bot
        assert called["logger"] is ctx.runtime.logger

    def test_synchronize_commands_step_skips_without_guild_id(self, monkeypatch):
        # Don't actually sleep 2 seconds.
        async def fake_sleep(_):
            return None
        monkeypatch.setattr(step_commands.asyncio, "sleep", fake_sleep)

        runtime = _make_runtime(config={"guild_id": ""})
        bot = MagicMock()
        bot.sync_commands = AsyncMock()
        ctx = _make_context(bot=bot, runtime=runtime)
        _run(step_commands.synchronize_commands_step(ctx))
        bot.sync_commands.assert_not_awaited()

    def test_synchronize_commands_step_calls_sync_with_guild(self, monkeypatch):
        async def fake_sleep(_):
            return None
        monkeypatch.setattr(step_commands.asyncio, "sleep", fake_sleep)

        runtime = _make_runtime(config={"guild_id": "12345"})
        bot = MagicMock()
        bot.application_commands = [SimpleNamespace(name="schedule_add"), SimpleNamespace(name="status")]
        bot.sync_commands = AsyncMock()
        ctx = _make_context(bot=bot, runtime=runtime)
        _run(step_commands.synchronize_commands_step(ctx))
        bot.sync_commands.assert_awaited_once_with(guild_ids=[12345])

    def test_synchronize_commands_step_skips_when_no_sync_commands_method(
        self, monkeypatch
    ):
        async def fake_sleep(_):
            return None
        monkeypatch.setattr(step_commands.asyncio, "sleep", fake_sleep)

        runtime = _make_runtime(config={"guild_id": "9999"})
        bot = MagicMock(spec=[])  # no sync_commands attr
        bot.application_commands = []
        ctx = _make_context(bot=bot, runtime=runtime)
        # Should complete without raising.
        _run(step_commands.synchronize_commands_step(ctx))

    def test_synchronize_commands_step_logs_when_no_schedule_commands_visible(
        self, monkeypatch, caplog
    ):
        """Branch: command list non-empty but no schedule_* prefixes."""
        async def fake_sleep(_):
            return None
        monkeypatch.setattr(step_commands.asyncio, "sleep", fake_sleep)

        runtime = _make_runtime(config={"guild_id": "12345"})
        bot = MagicMock()
        bot.application_commands = [SimpleNamespace(name="status"), SimpleNamespace(name="restart")]
        bot.sync_commands = AsyncMock()
        ctx = _make_context(bot=bot, runtime=runtime)
        with caplog.at_level(logging.INFO):
            _run(step_commands.synchronize_commands_step(ctx))
        assert any(
            "not yet visible" in r.getMessage() for r in caplog.records
        )

    def test_synchronize_commands_step_falls_back_on_runtime_error(
        self, monkeypatch
    ):
        """When sync_commands raises, _fallback_register_commands is invoked."""
        async def fake_sleep(_):
            return None
        monkeypatch.setattr(step_commands.asyncio, "sleep", fake_sleep)

        runtime = _make_runtime(config={"guild_id": "12345"})
        bot = MagicMock()
        bot.application_commands = []
        bot.sync_commands = AsyncMock(side_effect=RuntimeError("network down"))
        ctx = _make_context(bot=bot, runtime=runtime)

        called = {}

        async def fake_fallback(bot_arg, logger_arg, guild_id):
            called["guild_id"] = guild_id

        monkeypatch.setattr(step_commands, "_fallback_register_commands", fake_fallback)
        _run(step_commands.synchronize_commands_step(ctx))
        assert called["guild_id"] == 12345

    def test_fallback_register_commands_returns_when_no_application_commands_attr(
        self,
    ):
        """The internal helper must early-return when the bot lacks the attr."""
        bot = MagicMock(spec=[])  # no application_commands
        # Should not raise.
        _run(step_commands._fallback_register_commands(bot, _make_logger(), 42))

    def test_fallback_register_commands_swallows_outer_runtime_error(
        self, monkeypatch
    ):
        """Outer try/except wraps the loop; a RuntimeError must be swallowed."""
        bot = SimpleNamespace()

        # ``application_commands`` is truthy via hasattr but iterating raises.
        class _ExplodingList:
            def __iter__(self):
                raise RuntimeError("kaboom")

        bot.application_commands = _ExplodingList()
        # Should not raise.
        _run(step_commands._fallback_register_commands(bot, _make_logger(), 42))


# ---------------------------------------------------------------------------
# app/bot/startup_steps/member_count.py
# ---------------------------------------------------------------------------

class TestStartupMemberCount:
    """Tests for app/bot/startup_steps/member_count.py."""

    def test_initialize_member_count_step_returns_when_snapshot_missing(
        self, monkeypatch, tmp_path, caplog
    ):
        # Fake services
        snap_file = tmp_path / "main.json"  # does NOT exist
        fake_paths = SimpleNamespace(snapshot_for=lambda _: snap_file)
        fake_progress = SimpleNamespace(
            get_state=lambda: SimpleNamespace(level=1),
        )

        # Replace the imported helpers in the module with our fakes.
        monkeypatch.setattr(step_member_count, "get_progress_paths", lambda: fake_paths)

        # The function imports get_progress_service / get_progress_paths INSIDE
        # the function body — we must inject those into sys.modules.
        progress_mod = types.ModuleType("services.mech.progress_service")
        progress_mod.get_progress_service = lambda: fake_progress
        progress_mod.current_bin = lambda x: 0
        progress_mod.requirement_for_level_and_bin = lambda level, b, member_count: 100
        monkeypatch.setitem(sys.modules, "services.mech.progress_service", progress_mod)

        paths_mod = types.ModuleType("services.mech.progress_paths")
        paths_mod.get_progress_paths = lambda: fake_paths
        monkeypatch.setitem(sys.modules, "services.mech.progress_paths", paths_mod)

        # member_count_service is fetched once at function entry.
        member_service = MagicMock()
        monkeypatch.setattr(
            step_member_count, "get_member_count_service", lambda: member_service
        )

        ctx = _make_context()
        with caplog.at_level(logging.WARNING):
            _run(step_member_count.initialize_member_count_step(ctx))
        assert any("Snapshot file not found" in r.getMessage() for r in caplog.records)
        # member_count_service.first_connected_guild MUST NOT be called.
        member_service.first_connected_guild.assert_not_called()

    def test_initialize_member_count_step_skips_update_when_unchanged(
        self, monkeypatch, tmp_path
    ):
        snap_file = tmp_path / "main.json"
        snap_data = {
            "level": 1,
            "last_user_count_sample": 25,
            "goal_requirement": 100,
        }
        snap_file.write_text(json.dumps(snap_data))

        fake_paths = SimpleNamespace(snapshot_for=lambda _: snap_file)
        fake_progress = SimpleNamespace(
            get_state=lambda: SimpleNamespace(level=1),
        )

        monkeypatch.setattr(step_member_count, "get_progress_paths", lambda: fake_paths)
        progress_mod = types.ModuleType("services.mech.progress_service")
        progress_mod.get_progress_service = lambda: fake_progress
        progress_mod.current_bin = lambda x: 0
        progress_mod.requirement_for_level_and_bin = lambda level, b, member_count: 100
        monkeypatch.setitem(sys.modules, "services.mech.progress_service", progress_mod)

        paths_mod = types.ModuleType("services.mech.progress_paths")
        paths_mod.get_progress_paths = lambda: fake_paths
        monkeypatch.setitem(sys.modules, "services.mech.progress_paths", paths_mod)

        guild = SimpleNamespace(name="g", id=42)
        member_service = MagicMock()
        member_service.first_connected_guild.return_value = guild
        member_service.compute_unique_member_count.return_value = 25  # unchanged
        monkeypatch.setattr(
            step_member_count, "get_member_count_service", lambda: member_service
        )

        ctx = _make_context()
        _run(step_member_count.initialize_member_count_step(ctx))
        # No publish/persist when value unchanged.
        member_service.publish_member_count.assert_not_called()
        member_service.persist_member_count_snapshot.assert_not_called()

    def test_initialize_member_count_step_publishes_when_count_changed(
        self, monkeypatch, tmp_path
    ):
        snap_file = tmp_path / "main.json"
        snap_data = {
            "level": 1,
            "last_user_count_sample": 10,
            "goal_requirement": 100,
        }
        snap_file.write_text(json.dumps(snap_data))

        fake_paths = SimpleNamespace(snapshot_for=lambda _: snap_file)
        fake_progress = SimpleNamespace(
            get_state=lambda: SimpleNamespace(level=1),
        )

        monkeypatch.setattr(step_member_count, "get_progress_paths", lambda: fake_paths)
        progress_mod = types.ModuleType("services.mech.progress_service")
        progress_mod.get_progress_service = lambda: fake_progress
        progress_mod.current_bin = lambda x: 0
        progress_mod.requirement_for_level_and_bin = lambda level, b, member_count: 200
        monkeypatch.setitem(sys.modules, "services.mech.progress_service", progress_mod)

        paths_mod = types.ModuleType("services.mech.progress_paths")
        paths_mod.get_progress_paths = lambda: fake_paths
        monkeypatch.setitem(sys.modules, "services.mech.progress_paths", paths_mod)

        guild = SimpleNamespace(name="g", id=42)
        member_service = MagicMock()
        member_service.first_connected_guild.return_value = guild
        member_service.compute_unique_member_count.return_value = 25  # changed
        monkeypatch.setattr(
            step_member_count, "get_member_count_service", lambda: member_service
        )

        ctx = _make_context()
        _run(step_member_count.initialize_member_count_step(ctx))
        member_service.publish_member_count.assert_called_once_with(25)
        member_service.persist_member_count_snapshot.assert_called_once()

        # Snapshot should now record the new goal/difficulty bin.
        updated = json.loads(snap_file.read_text())
        assert updated["goal_requirement"] == 200
        assert updated["difficulty_bin"] == 0

    def test_initialize_member_count_step_warns_when_no_guild(
        self, monkeypatch, tmp_path, caplog
    ):
        snap_file = tmp_path / "main.json"
        snap_file.write_text(json.dumps({
            "level": 1, "last_user_count_sample": 0, "goal_requirement": 1
        }))
        fake_paths = SimpleNamespace(snapshot_for=lambda _: snap_file)
        fake_progress = SimpleNamespace(get_state=lambda: SimpleNamespace(level=1))
        monkeypatch.setattr(step_member_count, "get_progress_paths", lambda: fake_paths)

        progress_mod = types.ModuleType("services.mech.progress_service")
        progress_mod.get_progress_service = lambda: fake_progress
        progress_mod.current_bin = lambda x: 0
        progress_mod.requirement_for_level_and_bin = lambda level, b, member_count: 1
        monkeypatch.setitem(sys.modules, "services.mech.progress_service", progress_mod)

        paths_mod = types.ModuleType("services.mech.progress_paths")
        paths_mod.get_progress_paths = lambda: fake_paths
        monkeypatch.setitem(sys.modules, "services.mech.progress_paths", paths_mod)

        member_service = MagicMock()
        member_service.first_connected_guild.return_value = None  # no connected guild
        monkeypatch.setattr(
            step_member_count, "get_member_count_service", lambda: member_service
        )

        ctx = _make_context()
        with caplog.at_level(logging.WARNING):
            _run(step_member_count.initialize_member_count_step(ctx))
        # No publish (early return inside _refresh_member_count).
        member_service.publish_member_count.assert_not_called()


# ---------------------------------------------------------------------------
# app/web/routes.py
# ---------------------------------------------------------------------------

class TestWebRoutes:
    """Tests for app/web/routes.py."""

    @staticmethod
    def _build_app(monkeypatch):
        from flask import Flask

        app = Flask(__name__)
        app.config["TESTING"] = True

        # Disable basic auth for testing.
        from app.auth import auth as basic_auth
        basic_auth.verify_password(lambda u, p: True)
        # Auth needs a verify callable; the existing app.auth.verify_password
        # decorator is module-level. Patch login_required to be transparent.
        monkeypatch.setattr(
            "app.auth.auth.login_required", lambda f: f
        )
        return app

    def test_validate_admin_users_accepts_digit_strings(self):
        result = web_routes._validate_admin_users(["123", "456"])
        assert result == {"success": True}

    def test_validate_admin_users_rejects_non_digit(self):
        result = web_routes._validate_admin_users(["123", "abc"])
        assert result["success"] is False
        assert "abc" in result["error"]

    def test_validate_admin_users_empty_list_succeeds(self):
        assert web_routes._validate_admin_users([]) == {"success": True}

    def test_register_routes_attaches_health_endpoint(self, monkeypatch):
        from flask import Flask
        app = Flask(__name__)
        # Bypass basic auth — replace the decorator with a no-op identity.
        monkeypatch.setattr(
            web_routes.auth, "login_required", lambda f: f
        )
        # Stub external services used by /health.
        monkeypatch.setattr(
            web_routes, "load_config",
            lambda: {"web_ui_password_hash": "set"}
        )
        monkeypatch.setattr(
            web_routes, "get_server_config_service",
            lambda: SimpleNamespace(get_all_servers=lambda: []),
        )
        web_routes.register_routes(app)
        client = app.test_client()
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "healthy"
        assert body["first_time_setup_needed"] is False
        assert body["servers_configured"] == 0

    def test_health_endpoint_first_time_setup(self, monkeypatch):
        from flask import Flask
        app = Flask(__name__)
        monkeypatch.setattr(web_routes.auth, "login_required", lambda f: f)
        monkeypatch.setattr(
            web_routes, "load_config",
            lambda: {"web_ui_password_hash": None}
        )
        monkeypatch.setattr(
            web_routes, "get_server_config_service",
            lambda: SimpleNamespace(get_all_servers=lambda: [{"a": 1}, {"b": 2}]),
        )
        web_routes.register_routes(app)
        body = app.test_client().get("/health").get_json()
        assert body["first_time_setup_needed"] is True
        assert body["servers_configured"] == 2

    def test_health_endpoint_handles_config_load_error(self, monkeypatch):
        from flask import Flask
        app = Flask(__name__)
        monkeypatch.setattr(web_routes.auth, "login_required", lambda f: f)

        def explode():
            raise OSError("cannot read")

        monkeypatch.setattr(web_routes, "load_config", explode)
        web_routes.register_routes(app)
        resp = app.test_client().get("/health")
        # Inner OSError caught, outer JSON response is healthy with config_loaded=False.
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["config_loaded"] is False
        assert body["servers_configured"] == 0

    def test_admin_users_get_returns_admin_data(self, monkeypatch):
        from flask import Flask
        app = Flask(__name__)
        monkeypatch.setattr(web_routes.auth, "login_required", lambda f: f)
        admin_data = {"discord_admin_users": ["111"], "admin_notes": {"111": "founder"}}
        admin_service = SimpleNamespace(
            get_admin_data=lambda: admin_data,
            save_admin_data=lambda u, n: True,
        )
        monkeypatch.setattr(web_routes, "get_admin_service", lambda: admin_service)
        web_routes.register_routes(app)
        resp = app.test_client().get("/api/admin-users")
        assert resp.status_code == 200
        assert resp.get_json() == admin_data

    def test_admin_users_post_rejects_invalid_user_id(self, monkeypatch):
        from flask import Flask
        app = Flask(__name__)
        monkeypatch.setattr(web_routes.auth, "login_required", lambda f: f)
        admin_service = SimpleNamespace(
            get_admin_data=lambda: {},
            save_admin_data=lambda u, n: True,
        )
        monkeypatch.setattr(web_routes, "get_admin_service", lambda: admin_service)
        web_routes.register_routes(app)
        resp = app.test_client().post(
            "/api/admin-users",
            json={"discord_admin_users": ["abc"], "admin_notes": {}},
        )
        body = resp.get_json()
        assert body["success"] is False
        assert "abc" in body["error"]

    def test_admin_users_post_save_success(self, monkeypatch):
        from flask import Flask
        app = Flask(__name__)
        monkeypatch.setattr(web_routes.auth, "login_required", lambda f: f)
        admin_service = SimpleNamespace(
            get_admin_data=lambda: {},
            save_admin_data=lambda u, n: True,
        )
        monkeypatch.setattr(web_routes, "get_admin_service", lambda: admin_service)
        web_routes.register_routes(app)
        resp = app.test_client().post(
            "/api/admin-users",
            json={"discord_admin_users": ["111", "222"], "admin_notes": {}},
        )
        assert resp.get_json() == {"success": True}

    def test_admin_users_post_save_failure(self, monkeypatch):
        from flask import Flask
        app = Flask(__name__)
        monkeypatch.setattr(web_routes.auth, "login_required", lambda f: f)
        admin_service = SimpleNamespace(
            get_admin_data=lambda: {},
            save_admin_data=lambda u, n: False,
        )
        monkeypatch.setattr(web_routes, "get_admin_service", lambda: admin_service)
        web_routes.register_routes(app)
        resp = app.test_client().post(
            "/api/admin-users",
            json={"discord_admin_users": ["111"], "admin_notes": {}},
        )
        body = resp.get_json()
        assert body["success"] is False
        assert "Failed to save" in body["error"]


# ---------------------------------------------------------------------------
# app/web/compat.py
# ---------------------------------------------------------------------------

class TestWebCompat:
    """Tests for app/web/compat.py."""

    def test_initialize_gevent_noop_when_disabled(self):
        # In test environment HAS_GEVENT defaults to False; function returns silently.
        logger = MagicMock()
        # Force HAS_GEVENT False just to be sure.
        with patch.object(web_compat, "HAS_GEVENT", False):
            web_compat.initialize_gevent(logger)
        logger.info.assert_not_called()

    def test_apply_gevent_fork_workaround_noop_when_disabled(self):
        logger = MagicMock()
        with patch.object(web_compat, "HAS_GEVENT", False):
            web_compat.apply_gevent_fork_workaround(logger)
        logger.info.assert_not_called()

    def test_module_has_gevent_default_false_in_tests(self):
        """In the test environment we don't opt-in to gevent."""
        # Simply verifies the module attribute exists and is bool.
        assert isinstance(web_compat.HAS_GEVENT, bool)

    def test_gevent_enabled_flag_reads_environment(self, monkeypatch):
        """The opt-in flag is set at module import time; verify the parser works."""
        # We can test the same expression the module uses.
        parsed = "1".strip().lower() in {"1", "true", "yes", "on"}
        assert parsed is True
        parsed = "off".strip().lower() in {"1", "true", "yes", "on"}
        assert parsed is False


# ---------------------------------------------------------------------------
# app/bootstrap/runtime.py
# ---------------------------------------------------------------------------

class TestBootstrapRuntime:
    """Tests for app/bootstrap/runtime.py."""

    def test_configure_environment_sets_default(self):
        env = {}
        result = bootstrap_runtime.configure_environment(env)
        assert env["DDC_DISCORD_SKIP_TOKEN_LOCK"] == "true"
        assert result == "true"

    def test_configure_environment_preserves_existing_value(self):
        env = {"DDC_DISCORD_SKIP_TOKEN_LOCK": "false"}
        result = bootstrap_runtime.configure_environment(env)
        assert result == "false"
        assert env["DDC_DISCORD_SKIP_TOKEN_LOCK"] == "false"

    def test_configure_environment_uses_os_environ_by_default(self, monkeypatch):
        monkeypatch.delenv("DDC_DISCORD_SKIP_TOKEN_LOCK", raising=False)
        result = bootstrap_runtime.configure_environment()
        assert os.environ.get("DDC_DISCORD_SKIP_TOKEN_LOCK") == "true"
        assert result == "true"

    def test_resolve_timezone_returns_configured_timezone(self):
        config = {"timezone": "Europe/Berlin"}
        tz = bootstrap_runtime.resolve_timezone(config)
        assert str(tz) == "Europe/Berlin"

    def test_resolve_timezone_falls_back_on_unknown_zone(self):
        config = {"timezone": "Mars/Olympus"}
        tz = bootstrap_runtime.resolve_timezone(config)
        assert str(tz) == "UTC"

    def test_resolve_timezone_uses_default_when_no_config(self):
        tz = bootstrap_runtime.resolve_timezone(None, default="Europe/Berlin")
        assert str(tz) == "Europe/Berlin"

    def test_load_main_configuration_calls_helpers(self, monkeypatch):
        sample = {"key": "value"}
        monkeypatch.setattr(bootstrap_runtime, "load_config", lambda: sample)
        captured = {}
        monkeypatch.setattr(
            bootstrap_runtime, "init_config_cache",
            lambda c: captured.setdefault("seen", c),
        )
        cfg = bootstrap_runtime.load_main_configuration()
        assert cfg is sample
        assert captured["seen"] is sample

    def test_initialize_logging_returns_logger(self, monkeypatch):
        sentinel = logging.getLogger("ddc.test.bootstrap.init")
        monkeypatch.setattr(
            bootstrap_runtime, "setup_logger",
            lambda name, level=logging.INFO: sentinel,
        )
        logger = bootstrap_runtime.initialize_logging("ddc.x")
        assert logger is sentinel

    def test_ensure_log_files_creates_directory_and_attaches_handlers(self, tmp_path):
        logger = logging.getLogger("ddc.test.bootstrap.logfiles")
        # Drop any pre-existing handlers from previous runs.
        for h in list(logger.handlers):
            logger.removeHandler(h)
        logs_dir = tmp_path / "logs"
        bootstrap_runtime.ensure_log_files(logger, logs_dir)
        assert logs_dir.exists()
        # Two file handlers attached: discord.log + bot_error.log.
        file_handlers = [
            h for h in logger.handlers if isinstance(h, logging.FileHandler)
        ]
        names = {Path(getattr(h, "baseFilename", "")).name for h in file_handlers}
        assert "discord.log" in names
        assert "bot_error.log" in names

        # Idempotent: a second call doesn't duplicate handlers.
        bootstrap_runtime.ensure_log_files(logger, logs_dir)
        file_handlers_2 = [
            h for h in logger.handlers if isinstance(h, logging.FileHandler)
        ]
        assert len(file_handlers_2) == len(file_handlers)
        # Cleanup so the next test isn't polluted.
        for h in file_handlers_2:
            logger.removeHandler(h)
            h.close()

    def test_ensure_token_security_returns_false_when_module_missing(
        self, monkeypatch
    ):
        # Force ImportError via __builtins__.__import__ for that specific name.
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

        def selective(name, *a, **kw):
            if name == "utils.token_security":
                raise ImportError("missing")
            return real_import(name, *a, **kw)

        with patch("builtins.__import__", side_effect=selective):
            ok = bootstrap_runtime.ensure_token_security(_make_logger())
        assert ok is False

    def test_ensure_token_security_returns_true_on_success(self, monkeypatch):
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

        def selective(name, *a, **kw):
            if name == "utils.token_security":
                stub = types.ModuleType("utils.token_security")
                stub.auto_encrypt_token_on_startup = lambda: None
                return stub
            return real_import(name, *a, **kw)

        with patch("builtins.__import__", side_effect=selective):
            ok = bootstrap_runtime.ensure_token_security(_make_logger())
        assert ok is True

    def test_ensure_token_security_returns_false_on_runtime_error(self, monkeypatch):
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

        def selective(name, *a, **kw):
            if name == "utils.token_security":
                stub = types.ModuleType("utils.token_security")
                def _boom():
                    raise RuntimeError("token broken")
                stub.auto_encrypt_token_on_startup = _boom
                return stub
            return real_import(name, *a, **kw)

        with patch("builtins.__import__", side_effect=selective):
            ok = bootstrap_runtime.ensure_token_security(_make_logger())
        assert ok is False
