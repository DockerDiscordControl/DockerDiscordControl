# -*- coding: utf-8 -*-
"""/serverstatus muss die Abklingzeit-Abweisung PRIVAT zustellen.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers. Die Verhaltensaenderung ist entschieden:
"Pruefen vor defer".

DER BEFUND. ``serverstatus`` stellt OEFFENTLICH zurueck (``ctx.defer()`` ohne
ephemeral) und prueft den Spamschutz erst danach. Die Abweisung geht per
followup und ersetzt damit die oeffentliche "denkt nach..."-Nachricht - der
ganze Kanal sieht "Command on cooldown". Gerade der Spamschutz erzeugte so
Kanal-Rauschen.

DIE KORREKTUR: Die Bremse laeuft VOR dem defer und weist per
``ctx.respond(..., ephemeral=True)`` ab. Der Preis, offen benannt: Vor dem
defer liegt jetzt ein Lesen der Konfigurationsdatei; bei stark ueberlastetem
Bot steigt das Risiko fuer "Unknown interaction" (10062) minimal. Der
Betreiber hat das so abgewogen.

EINE BERICHTIGUNG MEINER FRAGE: Ich hatte /donate als ebenfalls oeffentlich
genannt. Gemessen stellt /donate mit ``ctx.defer(ephemeral=True)`` zurueck;
die Abweisung per followup erbt das und war nie oeffentlich. /donate bleibt
deshalb unveraendert - die Abgrenzung unten haelt den Grund fest.

WIE HIER GEPRUEFT WIRD: Die Befehlsfunktion wird ueber ``.callback`` mit einem
Stellvertreter-Cog gerufen, dessen ``_check_spam_protection`` die ECHTE Methode
ist - gegen einen echten Dienst. Die Reihenfolge von Bremse und defer wird in
EINER gemeinsamen Mitschrift festgehalten.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.docker_control import DockerControlCog
from services.infrastructure.spam_protection_service import SpamProtectionService

SPAM_PFAD = "services.infrastructure.spam_protection_service.get_spam_protection_service"
NUTZER = 9955


class _Dienst:
    """Echter Dienst; is_on_cooldown traegt sich in die gemeinsame Mitschrift ein."""

    def __init__(self, echt, ablauf):
        self._echt = echt
        self._ablauf = ablauf

    def is_on_cooldown(self, user_id, action_type, kind="button"):
        self._ablauf.append("bremse")
        return self._echt.is_on_cooldown(user_id, action_type, kind=kind)

    def __getattr__(self, name):
        return getattr(self._echt, name)


def _aufbau(tmp_path, gesperrt):
    ablauf = []
    echt = SpamProtectionService(config_dir=str(tmp_path))
    if gesperrt:
        echt.add_user_cooldown(NUTZER, "serverstatus", kind="command")
    ctx = MagicMock()
    ctx.author.id = NUTZER
    ctx.defer = AsyncMock(side_effect=lambda *a, **k: ablauf.append("defer"))
    ctx.respond = AsyncMock()
    ctx.followup.send = AsyncMock()
    cog = MagicMock()

    async def _pruefe(c, name):
        return await DockerControlCog._check_spam_protection(cog, c, name)

    cog._check_spam_protection = _pruefe
    return _Dienst(echt, ablauf), ablauf, ctx, cog


async def _rufe(befehl, cog, ctx, dienst):
    with patch(SPAM_PFAD, return_value=dienst):
        try:
            await befehl.callback(cog, ctx)
        except TypeError as e:
            # Nur aus der Tiefe NACH Bremse und defer (Cog-Methoden an einer
            # MagicMock). Die Tests behaupten POSITIV ueber die Mitschrift.
            if "can't be awaited" not in str(e):
                raise


@pytest.mark.asyncio
async def test_die_abweisung_ist_privat(tmp_path):
    """DER BEFUND: Die Abweisung erscheint fuer den ganzen Kanal."""
    dienst, ablauf, ctx, cog = _aufbau(tmp_path, gesperrt=True)

    await _rufe(DockerControlCog.serverstatus, cog, ctx, dienst)

    ctx.followup.send.assert_not_awaited()
    ctx.defer.assert_not_awaited()
    ctx.respond.assert_awaited_once()
    assert "on cooldown" in ctx.respond.await_args.args[0]
    assert ctx.respond.await_args.kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_die_bremse_laeuft_vor_dem_defer(tmp_path):
    """DER BEFUND, Reihenfolge - auch im Normalfall, sonst waere die private
    Abweisung nur ein Zufall des Sperrfalls."""
    dienst, ablauf, ctx, cog = _aufbau(tmp_path, gesperrt=False)

    await _rufe(DockerControlCog.serverstatus, cog, ctx, dienst)

    assert ablauf[:2] == ["bremse", "defer"], (
        f"Ablauf {ablauf!r}: Die Bremse muss VOR dem defer laufen."
    )


@pytest.mark.asyncio
async def test_donate_stellt_privat_zurueck(tmp_path):
    """Abgrenzung und Grund, warum /donate unveraendert bleibt: Es stellt
    ephemeral zurueck, die followup-Abweisung erbt das. Stellte es eines Tages
    oeffentlich zurueck, waere der Befund dort wieder da."""
    dienst, ablauf, ctx, cog = _aufbau(tmp_path, gesperrt=False)

    with patch("services.donation.donation_utils.is_donations_disabled", return_value=False):
        await _rufe(DockerControlCog.donate_command, cog, ctx, dienst)

    assert ctx.defer.await_args_list[0].kwargs.get("ephemeral") is True
