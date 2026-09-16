# -*- coding: utf-8 -*-
# @deckt Z5
"""Z5 - Kein Eingriff an einem Container ohne Kanalrecht und erlaubte Aktion.

Start, Stopp und Neustart geschehen nur, wenn der Kanal die Berechtigung traegt.
Diese Zusicherung verlangt KEINE Nutzerpruefung - Autorisierung ueber den Kanal
ist gewollt (SPEC.md B1). Sie verlangt, dass die Kanalpruefung lueckenlos ist.

Der Befund: ``control_ui.py:304`` liest

    channel_has_control = is_admin_control or _get_cached_channel_permission(...)

wobei ``is_admin_control`` nur bedeutet, dass der Titel der Einbettung die
Zeichenkette "Admin Control" enthaelt (:297-301). Eine Berechtigung steckt damit
in einer **Nachricht**, nicht in der Konfiguration. Solange das Panel in einem
Control-Kanal haengt, ist das redundant - ``/control`` prueft das Recht bereits
(``docker_control.py:1947``). Zur Luecke wird es, wenn die Nachricht das Recht
ueberdauert: Panel gepostet, danach Control-Recht entzogen, Panel weiter bedienbar.

Vom Betreiber entschieden (2026-09-16): Alte Panels werden **sofort wirkungslos**.
Eine Berechtigung darf nicht in einer Nachricht stecken, die Monate alt sein kann.

Nicht betroffen sind die drei rein darstellenden Verwendungen derselben
Heuristik (:429, :1019-1025, :1072-1079) - sie erteilen kein Recht, sondern
steuern Anzeige. Das wurde vor dieser Korrektur eigens nachgeprueft.

Warum ``pending_actions`` geprueft wird und nicht der Docker-Aufruf: Letzterer
laeuft in einer Hintergrundaufgabe (``create_task``), auf die zu pruefen bruechig
waere. Der Eintrag in ``pending_actions`` wird dagegen bei :329 synchron gesetzt,
bevor irgendetwas im Hintergrund startet - wird abgelehnt, bleibt er aus.

GEGENPROBE (durchgefuehrt 2026-09-16):

Vor der Korrektur schlug ``test_admin_titel_ersetzt_das_entzogene_kanalrecht_nicht``
fehl - und zwar **staerker als vorhergesagt**. Erwartet hatte ich einen
Fehlschlag an ``pending_actions == {}``; tatsaechlich riss schon der
Stolperdraht bei :332::

    cogs/control_ui.py:332: pending_embed = _get_pending_embed(...)
    E   _TorPassiert

Das Protokoll zeigte dazu ``[ACTION_BTN] STOP action for 'nginx' triggered by
Irgendwer``: ohne Kanalrecht, allein wegen des Titels, war der Eingriff nicht
bloss vorgemerkt, sondern bereits in vollem Gange.

Nach der Korrektur 21 gruen, ``tests/unit/cogs`` unveraendert 267 gruen.

Wichtig dabei: Ein Test, der vorher ueber den Stolperdraht fiel, koennte danach
gruen sein, *weil der Draht nicht mehr reisst* - und nicht, weil die Zusicherung
haelt. Deshalb nagelt ``_ablehnung_geprueft`` den Ablehnungstext fest. Ohne das
waere ``followup.send.assert_awaited()`` auch vom Pfad bei :294 (kein Kanal)
erfuellt worden.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cogs.control_ui as cui
from cogs.control_ui import ActionButton


class _TorPassiert(Exception):
    """Stolperdraht: wird geworfen, sobald die Kanalpruefung passiert ist."""


def _interaction(*, titel: str | None):
    """Interaktion, deren Nachricht optional einen 'Admin Control'-Titel traegt."""
    inter = MagicMock()
    inter.response.send_message = AsyncMock()
    inter.response.defer = AsyncMock()
    inter.followup.send = AsyncMock()
    inter.edit_original_response = AsyncMock()
    inter.user.id = 4711
    inter.user.name = "Irgendwer"
    inter.channel.id = 300

    if titel is None:
        inter.message = None
    else:
        einbettung = SimpleNamespace(title=titel)
        inter.message = SimpleNamespace(embeds=[einbettung])
    return inter


def _knopf(aktion: str = "stop"):
    """ActionButton ohne py-cord-Konstruktor.

    Der echte ``__init__`` zieht ``discord.ui.Button`` und den statischen
    Datencache nach. Geprueft werden soll ``callback``, nicht das Geruest.
    """
    b = ActionButton.__new__(ActionButton)
    b.cog = SimpleNamespace(pending_actions={})
    b.action = aktion
    b.server_config = {"docker_name": "nginx", "display_name": "nginx",
                       "allowed_actions": ["start", "stop", "restart"]}
    b.docker_name = "nginx"
    b.display_name = "nginx"
    return b


@pytest.fixture
def umgebung(monkeypatch):
    """Spam-Schutz aus, Konfiguration vorhanden, Stolperdraht hinter dem Tor."""
    spam = MagicMock()
    spam.is_enabled.return_value = False
    monkeypatch.setattr(
        "services.infrastructure.spam_protection_service.get_spam_protection_service",
        lambda: spam,
    )
    monkeypatch.setattr(cui, "load_config", lambda: {"servers": []})

    def _stolperdraht(*_a, **_k):
        raise _TorPassiert()

    monkeypatch.setattr(cui, "_get_pending_embed", _stolperdraht)
    return spam


def _ablehnung_geprueft(inter):
    """Belege, dass wirklich der Ablehnungspfad lief - nicht irgendein followup.

    ``followup.send`` wird auch bei :294 benutzt (kein Kanal ermittelbar). Ein
    blosses ``assert_awaited()`` unterscheidet die beiden nicht und waere gruen,
    ohne dass die Kanalpruefung je gegriffen haette.
    """
    inter.followup.send.assert_awaited()
    texte = " ".join(str(a) for ruf in inter.followup.send.await_args_list
                     for a in ruf.args)
    assert "not allowed in this channel" in texte, (
        f"Es wurde etwas gesendet, aber nicht die Ablehnung: {texte!r}"
    )


def _kanalrecht(monkeypatch, *, erlaubt: bool):
    monkeypatch.setattr(
        cui, "_get_cached_channel_permission",
        lambda channel_id, key, config=None: erlaubt,
    )


async def test_admin_titel_ersetzt_das_entzogene_kanalrecht_nicht(umgebung, monkeypatch):
    """Kein Kanalrecht, aber 'Admin Control' im Titel: der Knopf muss ablehnen.

    Das ist der Fall "Panel ueberdauert das Recht": Die Nachricht haengt noch im
    Kanal, das Recht ist entzogen - und die Knoepfe duerfen nicht mehr wirken.
    """
    _kanalrecht(monkeypatch, erlaubt=False)
    knopf = _knopf()
    inter = _interaction(titel="🛠️ Admin Control: nginx")

    await knopf.callback(inter)

    assert knopf.cog.pending_actions == {}, (
        "Der Container-Eingriff wurde vorgemerkt, obwohl der Kanal kein "
        "control-Recht mehr hat - der Titel einer alten Nachricht hat die "
        "Berechtigung ersetzt"
    )
    _ablehnung_geprueft(inter)


async def test_ohne_kanalrecht_und_ohne_admin_titel_wird_abgelehnt(umgebung, monkeypatch):
    """Der Grundfall - haelt heute schon und wird hier festgenagelt."""
    _kanalrecht(monkeypatch, erlaubt=False)
    knopf = _knopf()
    inter = _interaction(titel=None)

    await knopf.callback(inter)

    assert knopf.cog.pending_actions == {}
    _ablehnung_geprueft(inter)


async def test_mit_kanalrecht_geht_es_weiter(umgebung, monkeypatch):
    """Die erlaubte Seite: mit Kanalrecht passiert der Knopf das Tor.

    Ohne diesen Fall koennte man die Pruefung auf "immer ablehnen" verschaerfen
    und die beiden Tests oben blieben gruen.
    """
    _kanalrecht(monkeypatch, erlaubt=True)
    knopf = _knopf()
    inter = _interaction(titel=None)

    with pytest.raises(_TorPassiert):
        await knopf.callback(inter)

    assert knopf.cog.pending_actions.get("nginx"), (
        "Mit Kanalrecht haette der Eingriff vorgemerkt werden muessen"
    )
