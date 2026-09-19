# -*- coding: utf-8 -*-
"""Token-Pruefung, Token-Migration und der Token-Rueckfall muessen
``DDC_CONFIG_DIR`` folgen.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND. ``config_service`` schreibt ``bot_config.json`` und
``web_config.json`` in das Verzeichnis aus der Variable. Diese drei Wege lesen
am alten Ort (``Path(__file__).parents[N] / "config"``)::

    TokenSecurityManager.verify_token_encryption_status  token_security.py:169
    TokenSecurityManager.encrypt_existing_plaintext_token  token_security.py:72
    get_decrypted_bot_token (Rueckfall bot_config.json)   app/bot/token.py:34

Beide Methoden pruefen zuerst nur, ob die Dateien EXISTIEREN. Fehlen sie am
alten Ort, meldet der Status "kein Token" (und die Sicherheitsanzeige bewertet
eine Anlage, die es nicht gibt - Z9-Gebiet), und die Start-Migration beendet
sich mit "nichts zu tun": still und mit Erfolg, waehrend ein Klartext-Token im
echten Verzeichnis liegt.

WIE HIER GEPRUEFT WIRD: Die Dateien legt der Test im eingestellten Verzeichnis
an. ``DISCORD_BOT_TOKEN`` ist entfernt, sonst nimmt der Bot-Weg sie zuerst.
Die Verschluesselung ist ein Mitschreiber - geprueft wird, DASS und WOHIN
geschrieben wird, nicht die Kryptografie.
"""

import json
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.bot import token as bot_token
from utils.token_security import TokenSecurityManager

KLARTEXT = "klartext-token-probe"


@pytest.fixture
def verzeichnis(tmp_path, monkeypatch):
    ziel = tmp_path / "eigene_konfig"
    ziel.mkdir()
    monkeypatch.setenv("DDC_CONFIG_DIR", str(ziel))
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    (ziel / "bot_config.json").write_text(json.dumps({"bot_token": KLARTEXT}), encoding="utf-8")
    (ziel / "web_config.json").write_text(
        json.dumps({"web_ui_password_hash": "pbkdf2:sha256:1$abc$def"}), encoding="utf-8")
    return ziel


def test_der_sicherheitsstatus_sieht_das_klartext_token(verzeichnis):
    """DER BEFUND, Anzeige."""
    status = TokenSecurityManager(config_service=MagicMock()).verify_token_encryption_status()

    assert status["token_exists"] is True, (
        f"Der Status sieht das Token in DDC_CONFIG_DIR nicht: {status}"
    )
    assert status["is_encrypted"] is False
    assert status["password_hash_available"] is True


def test_die_start_migration_verschluesselt_im_verzeichnis(verzeichnis):
    """DER BEFUND, Migration: 'nichts zu tun' bei Klartext im echten Verzeichnis."""
    dienst = MagicMock()
    dienst.encrypt_token.return_value = "gAAAAA-verschluesselt"

    assert TokenSecurityManager(config_service=dienst).encrypt_existing_plaintext_token() is True

    gespeichert = json.loads((verzeichnis / "bot_config.json").read_text(encoding="utf-8"))
    assert gespeichert["bot_token"] == "gAAAAA-verschluesselt", (
        "Das Klartext-Token in DDC_CONFIG_DIR wurde nicht verschluesselt."
    )


def test_der_bot_findet_das_token_im_rueckfall(verzeichnis):
    """DER BEFUND, Bot-Start: kein Token in config.json, keine Fabrik - dann
    ist bot_config.json der letzte Weg."""
    laufzeit = SimpleNamespace(
        logger=logging.getLogger("test.konfigverzeichnis.token"),
        config={},
        dependencies=SimpleNamespace(config_service_factory=None),
    )

    assert bot_token.get_decrypted_bot_token(laufzeit) == KLARTEXT
