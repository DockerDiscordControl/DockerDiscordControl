# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

from __future__ import annotations

from flask import Flask

from app.web import create_app


def test_create_app_returns_flask_instance(monkeypatch):
    monkeypatch.setenv("DDC_ENABLE_BACKGROUND_REFRESH", "false")
    monkeypatch.setenv("DDC_ENABLE_MECH_DECAY", "false")

    app = create_app({"TESTING": True})
    assert isinstance(app, Flask)

    client = app.test_client()
    response = client.get("/health")

    assert response.status_code in {200, 500}
    assert "Content-Security-Policy" in response.headers
