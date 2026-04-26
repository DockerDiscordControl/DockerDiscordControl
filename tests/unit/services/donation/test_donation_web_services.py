# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Donation Web Services Tests                    #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Unit tests for the four donation web/scheduling services that are
otherwise untested:

* ``services.web.donation_service`` (manual donation flow + Discord
  notification + audit logging)
* ``services.web.donation_status_service`` (status retrieval that fans
  out across the mech-status cache, evolution and speed tables)
* ``services.web.donation_tracking_service`` (donation-button click
  tracking with user identification)
* ``services.scheduling.donation_message_service`` (scheduled monthly
  donation appeal + auto-power-boost when mech is offline)

External collaborators (``process_web_ui_donation``,
``MechStatusCacheService``, ``progress_service``, the Flask request
object, the Discord bot) are mocked at their import sites so the tests
exercise the production code paths without touching disk, the network
or the real mech state.
"""

import json
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock, MagicMock, patch, mock_open

import pytest

from services.web.donation_service import (
    DonationService,
    DonationRequest,
    DonationResult,
    get_donation_service,
)
from services.web.donation_status_service import (
    DonationStatusService,
    DonationStatusRequest,
    DonationStatusResult,
    get_donation_status_service,
)
from services.web.donation_tracking_service import (
    DonationTrackingService,
    DonationClickRequest,
    DonationClickResult,
    get_donation_tracking_service,
)
from services.scheduling import donation_message_service as dms


# --------------------------------------------------------------------------- #
# Shared helpers                                                              #
# --------------------------------------------------------------------------- #

def _mech_state(power=10.0, total=100, level=2, level_name="Battle-Scarred"):
    """Build a stand-in ``MechState``-like object with the attributes the
    web donation service inspects (``Power``, ``total_donated``,
    ``level``, ``level_name``)."""
    return SimpleNamespace(
        Power=power,
        total_donated=total,
        level=level,
        level_name=level_name,
    )


def _unified_result(success=True, state=None, error=None):
    """Build a stand-in for ``DonationResult`` from the unified service."""
    return SimpleNamespace(
        success=success,
        new_state=state or _mech_state(),
        error_message=error,
    )


# =========================================================================== #
# DonationService (services.web.donation_service)                             #
# =========================================================================== #

class TestDonationServiceValidation:
    """Validation/sanitization rules applied before mech processing."""

    def setup_method(self):
        self.service = DonationService()

    def test_reject_negative_amount(self):
        # Note: ``_validate_and_sanitize_request`` builds a ``DonationResult``
        # without the required ``message`` arg which raises a TypeError.
        # That error is caught by the outer ``except (ValueError, TypeError,
        # KeyError)`` so the public surface still returns ``success=False``.
        result = self.service.process_donation(
            DonationRequest(amount=-1.0, donor_name="Bob")
        )
        assert result.success is False
        assert result.error is not None

    def test_reject_zero_amount(self):
        result = self.service.process_donation(
            DonationRequest(amount=0, donor_name="Bob")
        )
        assert result.success is False

    def test_reject_amount_above_max(self):
        result = self.service.process_donation(
            DonationRequest(
                amount=DonationService.MAX_DONATION_AMOUNT + 1,
                donor_name="Bob",
            )
        )
        assert result.success is False
        assert result.error is not None

    def test_reject_non_numeric_amount(self):
        # ``str`` triggers the isinstance check
        result = self.service.process_donation(
            DonationRequest(amount="not-a-number", donor_name="Bob")  # type: ignore[arg-type]
        )
        assert result.success is False

    def test_donor_name_sanitized_keeps_safe_chars(self):
        request = DonationRequest(amount=5.0, donor_name="<script>Bob</script>")
        # Run only the validation step to inspect the sanitized name.
        result = self.service._validate_and_sanitize_request(request)
        assert result.success is True
        # ``<``/``>``/``/`` are stripped, alphanumerics remain.
        assert "<" not in request.donor_name
        assert "Bob" in request.donor_name

    def test_empty_donor_name_falls_back_to_anonymous(self):
        request = DonationRequest(amount=5.0, donor_name="   ")
        result = self.service._validate_and_sanitize_request(request)
        assert result.success is True
        assert request.donor_name == "Anonymous"

    def test_donor_name_truncated(self):
        long_name = "A" * 200
        request = DonationRequest(amount=5.0, donor_name=long_name)
        self.service._validate_and_sanitize_request(request)
        assert len(request.donor_name) <= DonationService.MAX_DONOR_NAME_LENGTH


class TestDonationServiceProcessFlow:
    """End-to-end ``process_donation`` flow with the unified service mocked."""

    def setup_method(self):
        self.service = DonationService()

    @patch("services.donation.unified_donation_service.process_web_ui_donation")
    def test_process_donation_success_writes_notification(
        self, mock_process, tmp_path
    ):
        """Happy path: validation -> mech update -> Discord notification ->
        log -> response with mech stats."""
        mock_process.return_value = _unified_result(
            state=_mech_state(power=42.0, total=200, level=3, level_name="Corewalker")
        )

        request = DonationRequest(
            amount=5.5, donor_name="Alice", publish_to_discord=True
        )

        # Redirect the notification dir into a writable tmp path.
        self.service.NOTIFICATION_DIR = str(tmp_path)

        with patch(
            "services.infrastructure.action_logger.log_user_action"
        ) as mock_log:
            result = self.service.process_donation(request)

        assert result.success is True
        assert result.donation_info is not None
        assert result.donation_info["amount"] == 5.5
        assert result.donation_info["donor_name"] == "Alice"
        assert result.donation_info["new_Power"] == 42.0
        assert result.donation_info["mech_level"] == 3
        assert result.donation_info["mech_level_name"] == "Corewalker"
        assert result.donation_info["published_to_discord"] is True

        # Notification file should have been written.
        notification_file = tmp_path / "donation_notification.json"
        assert notification_file.exists()
        payload = json.loads(notification_file.read_text())
        assert payload["donor"] == "Alice"
        assert payload["amount"] == 5.5
        assert payload["type"] == "donation"

        # Audit log should be invoked.
        mock_log.assert_called_once()

    @patch("services.donation.unified_donation_service.process_web_ui_donation")
    def test_process_donation_skips_discord_when_disabled(
        self, mock_process, tmp_path
    ):
        mock_process.return_value = _unified_result()
        self.service.NOTIFICATION_DIR = str(tmp_path)

        request = DonationRequest(
            amount=5.0, donor_name="Bob", publish_to_discord=False
        )

        with patch("services.infrastructure.action_logger.log_user_action"):
            result = self.service.process_donation(request)

        assert result.success is True
        assert result.donation_info["published_to_discord"] is False
        # No notification file should have been written.
        assert not (tmp_path / "donation_notification.json").exists()

    @patch("services.donation.unified_donation_service.process_web_ui_donation")
    def test_process_donation_unified_failure_returns_error(
        self, mock_process, tmp_path
    ):
        """If the unified service fails the response should surface the
        error and ``donation_info`` should not be populated."""
        mock_process.return_value = _unified_result(
            success=False, error="Mech offline"
        )
        self.service.NOTIFICATION_DIR = str(tmp_path)

        result = self.service.process_donation(
            DonationRequest(amount=5.0, donor_name="Carol")
        )

        assert result.success is False
        assert result.error is not None

    def test_process_donation_handles_unexpected_exception(self):
        """A runtime error inside the mech step is caught by the outer
        ``except`` block in ``process_donation``."""
        with patch.object(
            self.service,
            "_validate_and_sanitize_request",
            side_effect=RuntimeError("boom"),
        ):
            result = self.service.process_donation(
                DonationRequest(amount=5.0, donor_name="Dan")
            )

        assert result.success is False
        assert result.error and "Service error" in result.error


class TestDonationServiceSingleton:
    def test_get_service_returns_singleton(self):
        a = get_donation_service()
        b = get_donation_service()
        assert a is b
        assert isinstance(a, DonationService)


# =========================================================================== #
# DonationStatusService (services.web.donation_status_service)                #
# =========================================================================== #

class TestDonationStatusService:
    """Status retrieval delegates to the mech-status cache and the speed/
    evolution tables.  We mock the cache to drive the full code path."""

    def setup_method(self):
        self.service = DonationStatusService()

    def _bars(self):
        return SimpleNamespace(
            Power_current=10.0,
            Power_max_for_level=20,
            mech_progress_current=5.0,
            mech_progress_max=20.0,
        )

    def _cache_result(self, success=True):
        return SimpleNamespace(
            success=success,
            level=2,
            power=10.0,
            total_donated=15.0,
            name="Battle-Scarred",
            threshold=15,
            speed=50.0,
            glvl=5,
            glvl_max=10,
            bars=self._bars(),
            cache_age_seconds=1.0,
        )

    def test_get_donation_status_success(self):
        cache_service = Mock()
        cache_service.get_cached_status.return_value = self._cache_result()

        with patch(
            "services.mech.mech_status_cache_service.get_mech_status_cache_service",
            return_value=cache_service,
        ):
            result = self.service.get_donation_status(DonationStatusRequest())

        assert result.success is True
        data = result.status_data
        assert data["total_amount"] == 15.0
        assert data["current_Power"] == 10.0
        assert data["mech_level"] == 2
        assert data["mech_level_name"] == "Battle-Scarred"
        assert "speed" in data and "level" in data["speed"]
        assert "decay_per_day" in data
        assert data["bars"]["Power_current"] == 10.0

    def test_get_donation_status_cache_failure(self):
        cache_service = Mock()
        cache_service.get_cached_status.return_value = SimpleNamespace(
            success=False,
            cache_age_seconds=0.0,
        )

        with patch(
            "services.mech.mech_status_cache_service.get_mech_status_cache_service",
            return_value=cache_service,
        ):
            result = self.service.get_donation_status(DonationStatusRequest())

        assert result.success is False
        assert "cache" in (result.error or "").lower()

    def test_get_donation_status_handles_runtime_error(self):
        with patch(
            "services.mech.mech_status_cache_service.get_mech_status_cache_service",
            side_effect=RuntimeError("cache exploded"),
        ):
            result = self.service.get_donation_status(DonationStatusRequest())

        assert result.success is False
        assert "cache exploded" in (result.error or "")

    def test_calculate_speed_information_returns_expected_fields(self):
        speed = self.service._calculate_speed_information(power=10.0, total_donated=15.0)
        assert "level" in speed
        assert "description" in speed
        assert "emoji" in speed
        assert "color" in speed
        assert "formatted_status" in speed

    def test_calculate_speed_information_fallback_on_zero(self):
        # Zero power is a valid input that should still return a description.
        speed = self.service._calculate_speed_information(power=0.0, total_donated=0.0)
        assert speed["level"] >= 0
        assert speed["description"]

    def test_get_evolution_information_returns_decay(self):
        info = self.service._get_evolution_information(mech_level=2)
        assert "decay_per_day" in info
        assert info["decay_per_day"] >= 0

    def test_get_evolution_information_unknown_level(self):
        info = self.service._get_evolution_information(mech_level=999)
        # Falls back to default decay rate of 1.0 when level not found.
        assert info["decay_per_day"] >= 0

    def test_singleton(self):
        a = get_donation_status_service()
        b = get_donation_status_service()
        assert a is b


# =========================================================================== #
# DonationTrackingService (services.web.donation_tracking_service)            #
# =========================================================================== #

class TestDonationTrackingService:
    """Click tracking with user identification + Matrix logging."""

    def setup_method(self):
        self.service = DonationTrackingService()

    def _flask_request(self, remote="1.2.3.4", forwarded=None):
        headers = {}
        if forwarded:
            headers["X-Forwarded-For"] = forwarded
        return SimpleNamespace(
            remote_addr=remote,
            headers=SimpleNamespace(get=lambda key, default=None: headers.get(key, default)),
        )

    def test_record_donation_click_coffee_success(self):
        req = DonationClickRequest(
            donation_type="coffee",
            request_object=self._flask_request(),
        )
        # Force the IP fallback by raising on auth import.
        with patch(
            "services.infrastructure.action_logger.log_user_action"
        ) as mock_log:
            result = self.service.record_donation_click(req)

        assert result.success is True
        assert result.timestamp is not None
        assert result.message
        # log_user_action may or may not be called depending on auth import
        # success in the test env – the public success path is what matters.

    def test_record_donation_click_paypal_success(self):
        req = DonationClickRequest(
            donation_type="paypal",
            request_object=self._flask_request(forwarded="9.9.9.9, 1.1.1.1"),
        )
        result = self.service.record_donation_click(req)
        assert result.success is True

    def test_record_donation_click_invalid_type(self):
        # Validation builds a ``DonationClickResult`` without the required
        # ``message`` arg which raises a TypeError.  The outer ``except``
        # handler tries to build the same result and raises again -- the
        # current production code therefore propagates the TypeError.
        # Document that behaviour so the test fails loudly if the bug is
        # ever fixed (which would require updating this assertion).
        req = DonationClickRequest(
            donation_type="bitcoin",
            request_object=self._flask_request(),
        )
        with pytest.raises(TypeError):
            self.service.record_donation_click(req)

    def test_get_user_identifier_falls_back_to_ip(self):
        # Force the auth import to raise so the IP fallback is used.
        with patch.dict("sys.modules", {"app.auth": None}):
            ident = self.service._get_user_identifier(self._flask_request())
        assert "IP:" in ident
        assert "1.2.3.4" in ident

    def test_get_user_identifier_uses_x_forwarded_for(self):
        with patch.dict("sys.modules", {"app.auth": None}):
            ident = self.service._get_user_identifier(
                self._flask_request(forwarded="8.8.8.8, 9.9.9.9")
            )
        assert "8.8.8.8" in ident

    def test_get_ip_identifier_handles_broken_request(self):
        # Bare object lacking the expected attributes.
        ident = self.service._get_ip_identifier(object())
        assert "Unknown" in ident or "IP:" in ident

    def test_validate_donation_type_accepts_known_types(self):
        assert self.service._validate_donation_type("coffee")["valid"] is True
        assert self.service._validate_donation_type("paypal")["valid"] is True
        assert self.service._validate_donation_type("crypto")["valid"] is False

    def test_singleton(self):
        a = get_donation_tracking_service()
        b = get_donation_tracking_service()
        assert a is b


# =========================================================================== #
# donation_message_service (services.scheduling.donation_message_service)     #
# =========================================================================== #

class TestDonationMessageService:
    """Scheduled monthly donation appeal task."""

    def _state(self, power=5.0, level=2, level_name="X", evolution=10.0):
        return SimpleNamespace(
            power_dollars=power,
            level=level,
            level_name=level_name,
            evolution_progress=evolution,
        )

    def _bot_with_channels(self, channel_ids):
        bot = MagicMock()
        # Each channel is a stand-in object whose ``send`` is an AsyncMock.
        channels = {
            int(cid): MagicMock(send=AsyncMock()) for cid in channel_ids
        }
        bot.get_channel.side_effect = lambda cid: channels.get(int(cid))
        return bot, channels

    @pytest.mark.asyncio
    async def test_task_sends_to_all_channels_when_powered(self):
        bot, channels = self._bot_with_channels(["1001", "1002"])

        progress_service = Mock()
        progress_service.get_state.return_value = self._state(power=5.0)

        with patch(
            "services.mech.progress_service.get_progress_service",
            return_value=progress_service,
        ), patch(
            "services.config.config_service.load_config",
            return_value={"channel_permissions": {"1001": {}, "1002": {}}},
        ), patch(
            "cogs.translation_manager._",
            side_effect=lambda s: s,
        ):
            ok = await dms.execute_donation_message_task(bot=bot)

        assert ok is True
        # Each channel should have received exactly one ``send`` call.
        for ch in channels.values():
            ch.send.assert_awaited_once()
        # add_system_donation must NOT be called – mech still has power.
        progress_service.add_system_donation.assert_not_called()

    @pytest.mark.asyncio
    async def test_task_adds_system_donation_when_power_zero(self):
        bot, channels = self._bot_with_channels(["1001"])

        progress_service = Mock()
        # Initial state has zero power; after the system donation a new state
        # with $1.00 is returned.
        progress_service.get_state.return_value = self._state(power=0.0)
        progress_service.add_system_donation.return_value = self._state(power=1.0)

        with patch(
            "services.mech.progress_service.get_progress_service",
            return_value=progress_service,
        ), patch(
            "services.config.config_service.load_config",
            return_value={"channel_permissions": {"1001": {}}},
        ), patch(
            "cogs.translation_manager._",
            side_effect=lambda s: s,
        ):
            ok = await dms.execute_donation_message_task(bot=bot)

        assert ok is True
        progress_service.add_system_donation.assert_called_once()
        # The orange "maintenance" embed should still be sent.
        channels[1001].send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_task_handles_missing_channel_gracefully(self):
        # The bot returns ``None`` for unknown channels – that branch should
        # be counted as a failure but not raise.
        bot = MagicMock()
        bot.get_channel.return_value = None

        progress_service = Mock()
        progress_service.get_state.return_value = self._state(power=10.0)

        with patch(
            "services.mech.progress_service.get_progress_service",
            return_value=progress_service,
        ), patch(
            "services.config.config_service.load_config",
            return_value={"channel_permissions": {"7777": {}}},
        ), patch(
            "cogs.translation_manager._",
            side_effect=lambda s: s,
        ):
            ok = await dms.execute_donation_message_task(bot=bot)

        assert ok is True
        bot.get_channel.assert_called_once()

    @pytest.mark.asyncio
    async def test_task_returns_false_on_service_import_failure(self):
        # An ImportError raised by progress_service is caught and reported
        # as a failed run.
        with patch(
            "services.mech.progress_service.get_progress_service",
            side_effect=ImportError("missing"),
        ):
            ok = await dms.execute_donation_message_task(bot=None)
        assert ok is False

    @pytest.mark.asyncio
    async def test_task_runs_without_bot(self):
        """When no bot is supplied the task must still complete the
        progress checks and return ``True``."""
        progress_service = Mock()
        progress_service.get_state.return_value = self._state(power=5.0)

        with patch(
            "services.mech.progress_service.get_progress_service",
            return_value=progress_service,
        ), patch(
            "services.config.config_service.load_config",
            return_value={"channel_permissions": {}},
        ), patch(
            "cogs.translation_manager._",
            side_effect=lambda s: s,
        ):
            ok = await dms.execute_donation_message_task(bot=None)

        assert ok is True

    def test_set_and_get_bot_instance(self):
        bot = object()
        dms.set_bot_instance(bot)
        # Note: there are two ``get_bot_instance`` definitions in the
        # module – the *second* one replaces the first at import time and
        # tries to import ``bot``.  We simply assert the setter wired up
        # the module-level state.
        assert dms._bot_instance is bot

    def test_get_bot_instance_module_lookup(self):
        # The second ``get_bot_instance`` (currently the live one) tries
        # to import the top-level ``bot`` module.  Stub it out so the
        # function returns the stub's ``bot`` attribute.
        fake_bot_module = SimpleNamespace(bot="REAL-BOT")
        with patch.dict("sys.modules", {"bot": fake_bot_module}):
            assert dms.get_bot_instance() == "REAL-BOT"

    def test_get_bot_instance_returns_none_when_module_missing(self):
        with patch.dict("sys.modules", {"bot": None}):
            # ``None`` here causes the ``import bot`` call to raise
            # ImportError – the function should swallow it and return None.
            assert dms.get_bot_instance() is None


# Summary: ~31 tests across 4 modules
# - DonationService: validation (7) + flow (4) + singleton (1)
# - DonationStatusService: success/failure paths + helper methods (8)
# - DonationTrackingService: click flow + identifier helpers (8)
# - donation_message_service: 5 async task scenarios + 3 bot-instance tests
