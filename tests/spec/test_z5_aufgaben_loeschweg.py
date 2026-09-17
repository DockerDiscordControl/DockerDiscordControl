# -*- coding: utf-8 -*-
# @deckt Z5
"""Z5, zweiter Weg - das Loeschen von Zeitauftraegen.

Z5 sagt: kein Eingriff ohne Kanalrecht, **auf jedem Weg**. Die vorhandene
Abdeckung (``test_z5_channel_permission.py``) prueft nur ``ActionButton``, also
Start/Stopp/Neustart. Der zweite Eingriffsweg - einen Zeitauftrag loeschen -
war nicht abgedeckt, und genau dort steckt die Luecke.

DIE KETTE, vollstaendig nachgelesen (2026-09-17)::

    InfoButton.callback           control_ui.py:1032 / :1086
      has_control = is_admin_control or <Kanalrecht>      <-- Titel-Heuristik
      -> ContainerInfoAdminView   control_ui.py:1058 / :1093
         -> TaskManagementButton  status_info_integration.py:55  (bedingungslos)
            -> TaskManagementView              :1337
               -> DeleteTasksButton.callback   :1422   keine Pruefung
                  -> ContainerTaskDeleteButton.callback :2567  keine Pruefung
                     -> delete_task()          :2585

Ein alter Nachrichtentitel ``Admin Control`` genuegt also, um eine Ansicht zu
bekommen, aus der Zeitauftraege geloescht werden - ohne dass auf dem ganzen Weg
ein AKTUELLES Kanalrecht geprueft wird. Das ist derselbe Fall, fuer den der
Betreiber am 2026-09-16 entschieden hat, dass alte Panels sofort wirkungslos
sein muessen; ``control_ui.py:304`` wurde dafuer bereits korrigiert.

EIN EIGENER FEHLER, der hierher gehoert: SPEC.md fuehrte ``:1019-1025`` und
``:1072-1079`` als *"schalten nur Info-Anzeige und Admin-Knoepfe"* und damit als
rein darstellend. Das war falsch - sie entscheiden ueber den Bau der Ansicht,
die den Loeschweg traegt. Der Kommentar bei ``:1053`` sagt es sogar offen:
"Don't re-check channel permission as it would ignore admin control context".

ZWEITER BEFUND, gleiche Stelle: Derselbe Eingriff verlangt auf dem einen Weg
das Recht ``schedule`` (``control_ui.py:1276``), auf dem anderen gar keines.
``status_info_integration.py`` kennt die Zeichenkette ``'schedule'`` nicht.

ABGEGRENZT, weil geprueft: Die beiden Web-Wege (``tasks_bp.py:194``,
``task_management_service.py:817``) haengen an ``@auth.login_required`` - das
Panel hat ein eigenes Rechtemodell, nicht das Kanalmodell. Sie sind kein Teil
dieses Befunds.

GEGENPROBE (durchgefuehrt 2026-09-17): 2 rot, 1 gruen - genau wie vorhergesagt,
und beide Fehlschlaege aus dem richtigen Grund.

*Erster:* Der Stapel zeigte woertlich, dass ``control_ui.py`` die Ansicht baute,
obwohl ``control: False`` in der Konfiguration stand - allein wegen des
Nachrichtentitels. *Zweiter:* ``ContainerTaskDeleteButton`` enthielt die
Zeichenkette ``'schedule'`` nirgends.

Drei Fallen waren vorher benannt und keine trat ein: ``pytest-asyncio`` laeuft,
der Stolperdraht auf ``cogs.status_info_integration.ContainerInfoAdminView``
greift trotz des funktionsinternen Imports, und der Waechter
``is_user_admin.called`` belegt, dass der Ablauf nicht vorher abbog. Der
Gegenrichtungstest war von Anfang an gruen - ohne ihn koennte man den Bau der
Ansicht ersatzlos streichen und der erste Test bliebe gruen.

Nach der Korrektur: 3 gruen. ``test_z5_channel_permission.py`` unveraendert
3 gruen, ``tests/unit/cogs`` unveraendert 267, ``tests/spec`` 57.

WAS DIE KORREKTUR AENDERT: An beiden Stellen entscheidet jetzt allein das
AKTUELLE Kanalrecht, und der zweite Loeschweg prueft ``'schedule'`` wie sein
Zwilling. Ein Panel, das gepostet wurde, als der Kanal das Recht noch hatte,
ist nach dem Entzug wirkungslos - die Entscheidung des Betreibers vom
2026-09-16, hier an zwei Stellen nachgezogen, die damals falsch als "rein
darstellend" eingestuft worden waren.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import cogs.control_ui as cui
from cogs.control_ui import InfoButton


class _AnsichtGebaut(Exception):
    """Stolperdraht: fliegt, sobald die Admin-Ansicht gebaut wird.

    Ohne ihn muesste der Test die fertige Ansicht auseinandernehmen. So genuegt
    die Frage: Wurde sie ueberhaupt gebaut? Das ist die Zusicherung.
    """


def _interaction(*, titel):
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
        inter.message = SimpleNamespace(embeds=[SimpleNamespace(title=titel)])
    return inter


def _knopf():
    """InfoButton ohne py-cord-Konstruktor - geprueft wird ``callback``."""
    b = InfoButton.__new__(InfoButton)
    b.cog = SimpleNamespace()
    b.server_config = {"docker_name": "nginx", "display_name": "nginx"}
    b.docker_name = "nginx"
    b.display_name = "nginx"
    return b


@pytest.fixture
def umgebung(monkeypatch):
    """Alles ausser der Kanalpruefung aus dem Weg raeumen.

    WICHTIG: ``is_admin`` (control_ui.py:1002) schaltet die Info-Rechtspruefung
    ab. Waere der Testnutzer versehentlich Admin, kaeme er aus dem FALSCHEN
    Grund durch und der Test waere gruen, ohne etwas zu belegen. Der
    Admin-Dienst liefert deshalb ausdruecklich "kein Admin", und der Waechter
    unten belegt, dass er auch gefragt wurde.
    """
    spam = MagicMock()
    spam.is_enabled.return_value = False
    monkeypatch.setattr(
        "services.infrastructure.spam_protection_service.get_spam_protection_service",
        lambda: spam,
    )

    admin = MagicMock()
    admin.is_user_admin.return_value = False
    monkeypatch.setattr("services.admin.admin_service.get_admin_service", lambda: admin)

    # Kanal hat 'info' (sonst endet es schon bei :1005), aber NICHT 'control'.
    monkeypatch.setattr(cui, "load_config", lambda: {
        "servers": [],
        "channel_permissions": {"300": {"commands": {"info": True, "control": False}}},
    })

    info_dienst = MagicMock()
    info_dienst.get_container_info.return_value = SimpleNamespace(
        success=True,
        data=SimpleNamespace(to_dict=lambda: {"enabled": True, "info_text": "x"}),
    )
    monkeypatch.setattr(
        "services.infrastructure.container_info_service.get_container_info_service",
        lambda: info_dienst,
    )

    def _stolperdraht(*_a, **_k):
        raise _AnsichtGebaut()

    monkeypatch.setattr(
        "cogs.status_info_integration.ContainerInfoAdminView", _stolperdraht
    )
    return admin


@pytest.mark.asyncio
async def test_alter_admin_titel_erzeugt_keine_ansicht_mit_loeschweg(umgebung, monkeypatch):
    """Ein alter 'Admin Control'-Titel ersetzt das fehlende Kanalrecht nicht.

    Die Ansicht traegt ``TaskManagementButton`` bedingungslos
    (status_info_integration.py:55) und damit den Weg zu ``delete_task()``. Wird
    sie ohne aktuelles Kanalrecht gebaut, ist Z5 auf diesem Weg gebrochen.
    """
    knopf = _knopf()
    inter = _interaction(titel="🛠️ Admin Control: nginx")

    try:
        await knopf.callback(inter)
    except _AnsichtGebaut:
        pytest.fail(
            "Die Admin-Ansicht wurde allein wegen des Nachrichtentitels gebaut - "
            "ohne Kanalrecht 'control'. Sie traegt den Aufgaben-Loeschknopf und "
            "damit einen Weg zu delete_task(). Z5 verlangt die Pruefung auf JEDEM Weg."
        )

    assert umgebung.is_user_admin.called, (
        "Der Admin-Dienst wurde nie gefragt - der Ablauf ist also vorher "
        "abgebogen und dieser Test prueft nicht, was er zu pruefen vorgibt."
    )


@pytest.mark.asyncio
async def test_mit_kanalrecht_wird_die_ansicht_gebaut(monkeypatch):
    """Die Gegenrichtung - sonst waere 'baue nie eine Ansicht' auch gruen.

    Ohne diesen Fall koennte man den Bau der Ansicht ersatzlos streichen und der
    Test oben bliebe gruen, ohne dass die Zusicherung etwas taugt.
    """
    spam = MagicMock()
    spam.is_enabled.return_value = False
    monkeypatch.setattr(
        "services.infrastructure.spam_protection_service.get_spam_protection_service",
        lambda: spam,
    )
    admin = MagicMock()
    admin.is_user_admin.return_value = False
    monkeypatch.setattr("services.admin.admin_service.get_admin_service", lambda: admin)
    monkeypatch.setattr(cui, "load_config", lambda: {
        "servers": [],
        "channel_permissions": {"300": {"commands": {"info": True, "control": True}}},
    })
    info_dienst = MagicMock()
    info_dienst.get_container_info.return_value = SimpleNamespace(
        success=True,
        data=SimpleNamespace(to_dict=lambda: {"enabled": True, "info_text": "x"}),
    )
    monkeypatch.setattr(
        "services.infrastructure.container_info_service.get_container_info_service",
        lambda: info_dienst,
    )

    def _stolperdraht(*_a, **_k):
        raise _AnsichtGebaut()

    monkeypatch.setattr(
        "cogs.status_info_integration.ContainerInfoAdminView", _stolperdraht
    )

    knopf = _knopf()
    inter = _interaction(titel=None)

    with pytest.raises(_AnsichtGebaut):
        await knopf.callback(inter)


def test_der_loeschweg_prueft_das_zeitplan_recht():
    """Beide Loeschwege muessen dasselbe Recht verlangen.

    ``control_ui.py:1276`` fragt 'schedule'. ``status_info_integration.py``
    kannte die Zeichenkette gar nicht - wer 'control' hat, aber 'schedule'
    bewusst NICHT, konnte ueber den zweiten Weg trotzdem loeschen.

    Geprueft wird der Quelltext, weil der Callback sonst nur ueber ein halbes
    Discord-Geruest erreichbar waere. Dasselbe Mittel nutzt das Projekt in
    test_z6_docker_actions.py fuer die Aufrufstellen.
    """
    from pathlib import Path
    import re

    quelle = (Path(__file__).resolve().parents[2]
              / "cogs" / "status_info_integration.py").read_text(encoding="utf-8")

    # Der Rumpf von ContainerTaskDeleteButton.callback bis zum naechsten class.
    start = quelle.index("class ContainerTaskDeleteButton")
    rest = quelle[start:]
    ende = rest.find("\nclass ", 1)
    rumpf = rest[:ende] if ende > 0 else rest

    assert "delete_task(" in rumpf, (
        "Der Loeschaufruf steckt nicht mehr in dieser Klasse - der Test sucht "
        "an der falschen Stelle und wuerde gruen bleiben, ohne etwas zu belegen."
    )
    assert re.search(r"['\"]schedule['\"]", rumpf), (
        "ContainerTaskDeleteButton loescht Zeitauftraege, ohne das Recht "
        "'schedule' zu pruefen. Der Zwilling control_ui.py:1276 prueft es - "
        "derselbe Eingriff verlangt damit je nach Weg ein anderes Recht."
    )
