#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Unit tests for cogs/enhanced_info_modal_simple.py (previously 0% covered).

Three Discord modals live here, and two of them are security relevant:

- SimplifiedContainerInfoModal - validates and sanitises what users type into the
  container info dialog, then saves it.
- ProtectedInfoModal          - stores protected content plus its password.
- PasswordValidationModal     - guards access to that protected content.

The modals are built with object.__new__: their real __init__ talks to the
container info service, the server config service and discord.ui.Modal.
"""

import logging

import pytest
from unittest.mock import AsyncMock, MagicMock

import cogs.enhanced_info_modal_simple as modal_module
from cogs.enhanced_info_modal_simple import (
    PasswordValidationModal,
    ProtectedInfoModal,
    SimplifiedContainerInfoModal,
)


def _field(value):
    """Stand-in for a discord.ui.InputText: the code only reads .value."""
    item = MagicMock()
    item.value = value
    return item


def _interaction():
    inter = MagicMock()
    inter.response.send_message = AsyncMock()
    inter.response.is_done = MagicMock(return_value=False)
    inter.followup.send = AsyncMock()
    # The code reads both interaction.user.display_name (embed footer) and
    # str(interaction.user) (audit log), so a plain string is not enough here.
    user = MagicMock()
    user.display_name = "Someone"
    user.__str__.return_value = "someone#1234"
    inter.user = user
    inter.guild.name = "Guild"
    inter.channel.name = "channel"
    return inter


def _sent_text(interaction):
    """The positional message of the last response, or '' when an embed was sent."""
    args, kwargs = interaction.response.send_message.call_args
    return args[0] if args else ""


# ---------------------------------------------------------------------------
# SimplifiedContainerInfoModal - input validation
# ---------------------------------------------------------------------------

def _info_modal(*, text="", ip="", port="", enabled="x", show_ip="", existing=None,
                save_ok=True):
    modal = object.__new__(SimplifiedContainerInfoModal)
    modal.container_name = "alpha"
    modal.display_name = "Alpha"
    modal.container_info = existing if existing is not None else {}
    modal.custom_text = _field(text)
    modal.custom_ip = _field(ip)
    modal.custom_port = _field(port)
    modal.checkbox_enabled = _field(enabled)
    modal.checkbox_show_ip = _field(show_ip)

    result = MagicMock()
    result.success = save_ok
    result.error = None if save_ok else "permission denied"
    modal.info_service = MagicMock()
    modal.info_service.save_container_info = MagicMock(return_value=result)
    # Since 2026-09-20 the callback re-reads the CURRENT info to keep the protected
    # section (review B6); the snapshot in modal.container_info is only the fallback.
    current = MagicMock()
    current.success = True
    current.data.to_dict.return_value = dict(modal.container_info)
    modal.info_service.get_container_info = MagicMock(return_value=current)
    return modal


class TestInfoModalValidation:
    async def test_text_longer_than_250_chars_is_rejected(self):
        modal = _info_modal(text="x" * 251)
        inter = _interaction()
        await modal.callback(inter)
        assert "250" in _sent_text(inter)
        modal.info_service.save_container_info.assert_not_called()

    async def test_text_of_exactly_250_chars_is_accepted(self):
        """Boundary: 250 is still allowed."""
        modal = _info_modal(text="x" * 250)
        await modal.callback(_interaction())
        modal.info_service.save_container_info.assert_called_once()

    async def test_non_numeric_port_is_rejected(self):
        modal = _info_modal(port="80a")
        inter = _interaction()
        await modal.callback(inter)
        assert "numbers" in _sent_text(inter).lower()
        modal.info_service.save_container_info.assert_not_called()

    @pytest.mark.parametrize("port", ["0", "65536", "99999"])
    async def test_port_out_of_range_is_rejected(self, port):
        modal = _info_modal(port=port)
        inter = _interaction()
        await modal.callback(inter)
        assert "65535" in _sent_text(inter)
        modal.info_service.save_container_info.assert_not_called()

    @pytest.mark.parametrize("port", ["1", "25565", "65535"])
    async def test_port_inside_range_is_accepted(self, port):
        modal = _info_modal(port=port)
        await modal.callback(_interaction())
        modal.info_service.save_container_info.assert_called_once()

    async def test_empty_port_skips_the_port_checks(self):
        modal = _info_modal(port="")
        await modal.callback(_interaction())
        modal.info_service.save_container_info.assert_called_once()


class TestInfoModalSanitising:
    async def _saved(self, modal):
        await modal.callback(_interaction())
        return modal.info_service.save_container_info.call_args.args[1]

    async def test_markup_characters_are_stripped_from_text(self):
        saved = await self._saved(_info_modal(text="ping @everyone `code` #tag"))
        assert "@" not in saved.custom_text
        assert "`" not in saved.custom_text
        assert "#" not in saved.custom_text

    async def test_html_tags_are_stripped_from_text(self):
        saved = await self._saved(_info_modal(text="hello <script>alert(1)</script> world"))
        assert "<" not in saved.custom_text and ">" not in saved.custom_text
        assert "hello" in saved.custom_text and "world" in saved.custom_text

    async def test_angle_brackets_are_stripped_from_ip(self):
        saved = await self._saved(_info_modal(ip="<10.0.0.5>"))
        assert saved.custom_ip == "10.0.0.5"


class TestInfoModalCheckboxes:
    @pytest.mark.parametrize("value", ["x", "X", "1", "yes", "y", "true", "t"])
    async def test_accepted_checkbox_values_enable(self, value):
        modal = _info_modal(enabled=value)
        await modal.callback(_interaction())
        assert modal.info_service.save_container_info.call_args.args[1].enabled is True

    @pytest.mark.parametrize("value", ["", "   ", "no", "0"])
    async def test_other_values_do_not_enable(self, value):
        modal = _info_modal(enabled=value)
        await modal.callback(_interaction())
        assert modal.info_service.save_container_info.call_args.args[1].enabled is False


class TestInfoModalSaving:
    async def test_existing_protected_fields_are_preserved(self):
        """Editing the plain info must never wipe the protected section."""
        modal = _info_modal(existing={
            "protected_enabled": True,
            "protected_content": "secret",
            "protected_password": "hunter2",
        })
        await modal.callback(_interaction())
        saved = modal.info_service.save_container_info.call_args.args[1]
        assert saved.protected_enabled is True
        assert saved.protected_content == "secret"
        assert saved.protected_password == "hunter2"

    async def test_failed_save_tells_the_user_about_permissions(self):
        modal = _info_modal(save_ok=False)
        inter = _interaction()
        await modal.callback(inter)
        assert "permissions" in _sent_text(inter).lower()

    async def test_successful_save_answers_with_an_embed(self):
        modal = _info_modal(text="all good")
        inter = _interaction()
        await modal.callback(inter)
        assert inter.response.send_message.call_args.kwargs.get("embed") is not None


# ---------------------------------------------------------------------------
# ProtectedInfoModal
# ---------------------------------------------------------------------------

def _protected_modal(*, enabled="x", content="secret", password="pw", existing_ok=False):
    modal = object.__new__(ProtectedInfoModal)
    modal.container_name = "alpha"
    modal.display_name = "Alpha"
    modal.protected_enabled = _field(enabled)
    modal.protected_content = _field(content)
    modal.protected_password = _field(password)

    existing = MagicMock()
    existing.success = existing_ok
    existing.data.to_dict.return_value = {
        "enabled": True, "show_ip": True, "custom_ip": "10.0.0.1",
        "custom_port": "25565", "custom_text": "hello",
    }
    save_result = MagicMock()
    save_result.success = True
    modal.info_service = MagicMock()
    modal.info_service.get_container_info = MagicMock(return_value=existing)
    modal.info_service.save_container_info = MagicMock(return_value=save_result)
    return modal


class TestProtectedInfoModal:
    async def test_enabled_without_content_is_rejected(self):
        modal = _protected_modal(content="")
        inter = _interaction()
        await modal.callback(inter)
        assert _sent_text(inter) != ""
        modal.info_service.save_container_info.assert_not_called()

    async def test_enabled_without_password_is_rejected(self):
        modal = _protected_modal(password="")
        inter = _interaction()
        await modal.callback(inter)
        assert _sent_text(inter) != ""
        modal.info_service.save_container_info.assert_not_called()

    async def test_disabled_needs_neither_content_nor_password(self):
        modal = _protected_modal(enabled="", content="", password="")
        await modal.callback(_interaction())
        modal.info_service.save_container_info.assert_called_once()

    async def test_existing_plain_info_is_carried_over(self):
        modal = _protected_modal(existing_ok=True)
        await modal.callback(_interaction())
        saved = modal.info_service.save_container_info.call_args.args[1]
        assert saved.custom_ip == "10.0.0.1"
        assert saved.custom_text == "hello"
        assert saved.protected_content == "secret"

    async def test_defaults_are_used_when_no_info_exists_yet(self):
        modal = _protected_modal(existing_ok=False)
        await modal.callback(_interaction())
        saved = modal.info_service.save_container_info.call_args.args[1]
        assert saved.custom_ip == ""
        assert saved.enabled is False

    async def test_protected_content_is_sanitised(self):
        modal = _protected_modal(content="key `x` <b>@here</b>")
        await modal.callback(_interaction())
        saved = modal.info_service.save_container_info.call_args.args[1]
        assert "`" not in saved.protected_content
        assert "<" not in saved.protected_content and ">" not in saved.protected_content
        assert "@" not in saved.protected_content


# ---------------------------------------------------------------------------
# PasswordValidationModal - the access guard
# ---------------------------------------------------------------------------

def _password_modal(*, entered="pw", stored="pw", content="the secret",
                    monkeypatch=None):
    modal = object.__new__(PasswordValidationModal)
    modal.container_name = "alpha"
    modal.display_name = "Alpha"
    info = {"protected_password": stored, "protected_content": content}
    modal.container_info = dict(info)
    modal.password_input = _field(entered)
    # The modal re-reads the container info when the password is submitted
    # (review E27), because a persistent view's snapshot can be up to one status
    # refresh old and a changed password has to take effect at once. So the test
    # has to supply that read too - and it supplies exactly what the snapshot
    # holds, which keeps every case below saying what it always said.
    _serve_container_info(info)
    return modal


_SERVED_INFO: dict = {}


def _serve_container_info(info):
    """Point the module's info service at `info` for the rest of the test."""
    _SERVED_INFO.clear()
    _SERVED_INFO.update(info)


class _ServedData:
    @staticmethod
    def to_dict():
        return dict(_SERVED_INFO)


class _ServedResult:
    success = True
    data = _ServedData


class _ServedService:
    @staticmethod
    def get_container_info(_name):
        return _ServedResult


@pytest.fixture(autouse=True)
def _info_service(monkeypatch):
    monkeypatch.setattr(modal_module, "get_container_info_service",
                        lambda: _ServedService)


class TestPasswordValidation:
    async def test_no_stored_password_denies_access(self):
        inter = _interaction()
        await _password_modal(stored="").callback(inter)
        assert "password is set" in _sent_text(inter).lower()

    async def test_wrong_password_is_denied(self):
        inter = _interaction()
        await _password_modal(entered="guess", stored="real").callback(inter)
        assert "incorrect password" in _sent_text(inter).lower()

    async def test_wrong_password_is_logged_as_a_failed_attempt(self, monkeypatch):
        """Failed attempts on protected content must leave a trail."""
        calls = []
        monkeypatch.setattr(modal_module, "log_user_action",
                            lambda **kw: calls.append(kw))
        await _password_modal(entered="guess", stored="real").callback(_interaction())
        assert calls and calls[0]["action"] == "PROTECTED_INFO_FAILED"

    async def test_correct_password_shows_the_content(self):
        inter = _interaction()
        await _password_modal().callback(inter)
        embed = inter.response.send_message.call_args.kwargs.get("embed")
        assert embed is not None
        assert embed.description == "the secret"

    async def test_correct_password_is_logged_as_access(self, monkeypatch):
        calls = []
        monkeypatch.setattr(modal_module, "log_user_action",
                            lambda **kw: calls.append(kw))
        await _password_modal().callback(_interaction())
        assert calls and calls[0]["action"] == "PROTECTED_INFO_ACCESS"

    async def test_correct_password_but_no_content_says_so(self):
        inter = _interaction()
        await _password_modal(content="").callback(inter)
        assert "no protected information" in _sent_text(inter).lower()

    async def test_whitespace_around_the_password_is_ignored(self):
        inter = _interaction()
        await _password_modal(entered="  pw  ", stored="pw").callback(inter)
        assert inter.response.send_message.call_args.kwargs.get("embed") is not None

    async def test_password_comparison_is_case_sensitive(self):
        inter = _interaction()
        await _password_modal(entered="PW", stored="pw").callback(inter)
        assert "incorrect password" in _sent_text(inter).lower()

    async def test_an_error_while_logging_does_not_escape(self, monkeypatch, caplog):
        def boom(**kw):
            raise RuntimeError("audit log unavailable")

        monkeypatch.setattr(modal_module, "log_user_action", boom)
        inter = _interaction()
        with caplog.at_level(logging.ERROR):
            await _password_modal().callback(inter)  # must not raise
        assert "audit log unavailable" in _sent_text(inter)
