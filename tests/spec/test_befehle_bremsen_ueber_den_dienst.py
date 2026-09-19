# -*- coding: utf-8 -*-
"""Schraegstrich-Befehle muessen ueber den Spam-Dienst bremsen.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND. ``DockerControlCog._check_spam_protection``
(``docker_control.py:1721``) ist der Weg aller Schraegstrich-Befehle
(serverstatus, control, help, ping, donate, info). Er holt vom Dienst nur die
DAUER und fuehrt die Buchhaltung selbst - in einem Woerterbuch, das er VON
AUSSEN an das Dienst-Objekt heftet (``spam_manager._command_cooldowns``).

DREI FOLGEN:

1. Die BEFEHLS-Minutengrenze aus dem Panel (max_commands_per_minute) wirkt
   nicht - sie zaehlt in ``add_user_cooldown``, und dieser Weg kommt dort nie
   an. Das war die letzte der dreizehn Stellen mit eigener Buchhaltung.
2. Das angeheftete Woerterbuch wird NIE aufgeraeumt; je Nutzer und Befehl
   waechst es fuer die Lebensdauer des Prozesses.
3. Ein fremdes Attribut am Dienst ist Zustand, den der Dienst selbst nicht
   kennt - niemand, der den Dienst liest, sieht ihn.

WAS GLEICH BLEIBT, gemessen: die Dauer (``get_command_cooldown``), die Meldung
(bereits uebersetzt), der Abfuhrweg (``followup`` fuer zurueckgestellte
Befehle, sonst ``respond``).

VORAUSSETZUNG, und der Grund fuer die Reihenfolge: Erst seit Commit 8f47f7c
kann ein Befehl sich mit ``art="befehl"`` ausweisen. Vorher haette die Umstellung
Befehle und Knoepfe gleichen Namens (/info und den Info-Knopf) in einen Eimer
geworfen.

EINE ENTSCHEIDUNG, offen benannt: Ein Befehl mit Abklingzeit 0 bleibt ohne
Pause je Befehl, zaehlt aber ins Minutenfenster. "0" heisst "keine Pause fuer
diesen Befehl", nicht "von der Minutengrenze ausgenommen".

NICHT TEIL DIESES BEFUNDS: Bei zurueckgestellten Befehlen geht die
Abklingzeit-Meldung per followup OHNE ephemeral - sie ist fuer den ganzen Kanal
sichtbar. Eigene Verhaltensfrage, hier unveraendert.

WIE HIER GEPRUEFT WIRD: Die Methode benutzt ``self`` nicht; sie wird deshalb
ungebunden gerufen, statt den Cog mit seinen ueber 4.000 Zeilen zu bauen. Der
Dienst ist ein ECHTER SpamProtectionService, nur zum Mitschreiben
durchgereicht.
"""

import inspect
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.docker_control import DockerControlCog
from services.infrastructure.spam_protection_service import SpamProtectionService

SPAM_PFAD = "services.infrastructure.spam_protection_service.get_spam_protection_service"
NUTZER = 3141
JETZT = 70_000.0
PRUEFE = DockerControlCog._check_spam_protection


class _Mitschrift:
    """Reicht an den ECHTEN Dienst durch und haelt Aufrufe samt art fest."""

    def __init__(self, echt):
        self.__dict__["_echt"] = echt
        self.__dict__["gefragt"] = []
        self.__dict__["vermerkt"] = []

    def is_on_cooldown(self, user_id, action_type, art="knopf"):
        self.gefragt.append((user_id, action_type, art))
        return self._echt.is_on_cooldown(user_id, action_type, art=art)

    def add_user_cooldown(self, user_id, action_type, art="knopf"):
        self.vermerkt.append((user_id, action_type, art))
        return self._echt.add_user_cooldown(user_id, action_type, art=art)

    def __getattr__(self, name):
        return getattr(self._echt, name)

    def __setattr__(self, name, wert):
        # Heftet jemand etwas an den Dienst, landet es beim ECHTEN Dienst -
        # dort sieht der Test es.
        setattr(self._echt, name, wert)


def _dienst(tmp_path):
    return _Mitschrift(SpamProtectionService(config_dir=str(tmp_path)))


def _ctx():
    ctx = MagicMock()
    ctx.author.id = NUTZER
    ctx.respond = AsyncMock()
    ctx.followup.send = AsyncMock()
    return ctx


async def _pruefe(dienst, name):
    ctx = _ctx()
    with patch(SPAM_PFAD, return_value=dienst):
        erlaubt = await PRUEFE(MagicMock(), ctx, name)
    return erlaubt, ctx


def test_die_pruefung_existiert_und_ist_asynchron():
    """Sicherung gegen ein stumpfes Werkzeug."""
    assert inspect.iscoroutinefunction(PRUEFE)
    assert list(inspect.signature(PRUEFE).parameters) == ["self", "ctx", "command_name"]


@pytest.mark.asyncio
async def test_der_dienst_wird_als_befehl_gefragt_und_vermerkt(tmp_path):
    """DER BEFUND: Die zustandsbehafteten Methoden werden nie gerufen."""
    dienst = _dienst(tmp_path)

    erlaubt, _ = await _pruefe(dienst, "ping")

    assert erlaubt is True
    assert dienst.gefragt == [(NUTZER, "ping", "befehl")], (
        f"is_on_cooldown wurde nicht als Befehl mit 'ping' gerufen, sondern "
        f"{dienst.gefragt!r}. Der Befehlsweg bremst am Dienst vorbei."
    )
    assert dienst.vermerkt == [(NUTZER, "ping", "befehl")]


@pytest.mark.asyncio
# serverstatus seit dem 2026-09-19 "respond": Die Bremse laeuft dort VOR dem
# defer (test_serverstatus_weist_privat_ab.py). donate stellt ephemeral zurueck
# und bleibt beim followup.
@pytest.mark.parametrize("name,weg", [("ping", "respond"), ("serverstatus", "respond"),
                                      ("donate", "followup")])
async def test_ein_vermerkter_befehl_wird_abgewiesen(tmp_path, monkeypatch, name, weg):
    """DER BEFUND, Wirkung - auf dem Abfuhrweg, den dieser Befehl heute nimmt.

    Mit eingefrorener Uhr, damit die Restzeit in der Meldung exakt die Dauer
    des Befehls-Reglers ist und geprueft werden kann (sonst ueberlebte eine
    Meldung "try again in 0 seconds" jeden Test).
    """
    monkeypatch.setattr(time, "time", lambda: JETZT)
    dienst = _dienst(tmp_path)
    dauer = dienst._echt.get_command_cooldown(name)
    assert dauer > 0, f"/{name} hat keine Abklingzeit - der Test bewiese nichts."
    dienst._echt.add_user_cooldown(NUTZER, name, art="befehl")

    erlaubt, ctx = await _pruefe(dienst, name)

    assert erlaubt is False, (
        f"/{name} ist im Dienst als Befehl vermerkt und wird trotzdem "
        "durchgelassen."
    )
    sender = ctx.followup.send if weg == "followup" else ctx.respond
    sender.assert_awaited_once()
    meldung = sender.await_args.args[0]
    assert "on cooldown" in meldung
    assert f"in {dauer} seconds" in meldung, (
        f"Die Meldung nennt nicht die Restzeit {dauer} s: {meldung!r}"
    )
    if weg == "respond":
        # Nur der Befragte sieht die Abweisung. Fuer den followup-Weg gilt das
        # heute NICHT - offene Verhaltensfrage, hier bewusst nicht festgeschrieben.
        assert sender.await_args.kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_nichts_wird_von_aussen_an_den_dienst_geheftet(tmp_path):
    """DER BEFUND, zweiter Teil: keine fremde, nie aufgeraeumte Ablage."""
    dienst = _dienst(tmp_path)

    await _pruefe(dienst, "ping")

    assert not hasattr(dienst._echt, "_command_cooldowns"), (
        "Der Befehlsweg heftet weiterhin _command_cooldowns an den Dienst - "
        "ein Woerterbuch, das nie aufgeraeumt wird und das der Dienst nicht kennt."
    )


@pytest.mark.asyncio
async def test_die_befehls_minutengrenze_greift(tmp_path):
    """DER BEFUND, dritter Teil: max_commands_per_minute aus dem Panel wirkt."""
    dienst = _dienst(tmp_path)
    grenze = dienst._echt._get_default_config().max_commands_per_minute
    for i in range(grenze):
        dienst._echt.add_user_cooldown(NUTZER, f"probe_{i}", art="befehl")

    erlaubt, _ = await _pruefe(dienst, "ping")

    assert erlaubt is False, (
        f"Nach {grenze} Befehlen in derselben Minute - dem Kontingent aus "
        "max_commands_per_minute - geht /ping trotzdem durch."
    )


@pytest.mark.asyncio
async def test_abgeschaltet_bremst_nichts_und_vermerkt_nichts(tmp_path):
    """Abgrenzung: Der Betreiber kann den Schutz abschalten."""
    dienst = _dienst(tmp_path)

    with patch.object(dienst._echt, "is_enabled", return_value=False):
        erlaubt, _ = await _pruefe(dienst, "ping")

    assert erlaubt is True
    assert dienst.vermerkt == []
