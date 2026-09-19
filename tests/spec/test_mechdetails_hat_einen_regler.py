# -*- coding: utf-8 -*-
"""Der Mech-Details-Knopf muss bremsen - und einen Regler im Panel haben.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers. Die VERHALTENSAENDERUNG (ungebremste Mech-Knoepfe
bremsen) ist entschieden: "Ja, auch die zehn bremsen lassen".

DER BEFUND. ``MechDetailsButton`` (``mech_details_<kanal>``) fragt den
Spam-Dienst nicht. Anders als bei den fuenf Knoepfen aus Commit 41faf4b gibt
es hier auch KEINEN Regler: kein Vorgabewert, kein Panel-Feld, kein
Katalogeintrag. Nur die Bremse einzubauen hiesse, stumm nach der
5-Sekunden-Ersatzregel zu bremsen - ein Wert, den der Betreiber nirgends sieht.
Das war genau der Befund zu admin/tasks/task_delete (Commit 727324f).

WARUM DER VORHANDENE VERTRAG ES NICHT FAENGT: test_angeforderte_
abklingschluessel_existieren.py sieht nur woertliche Schluessel; dieser Knopf
fragt ueber ``self.custom_id`` an. Das steht dort als Grenze im Kopftext.

DIE VORGABE IST 5, wie beim verwandten Verlaufsknopf (mech_history). EINE FALLE,
offen benannt: 5 ist zugleich die Ersatzregel. Eine WERT-Pruefung koennte
deshalb nicht unterscheiden, ob der Regler greift oder die Ersatzregel. Den
Regler belegen hier das ARGUMENT, der Vorgabeeintrag, das Panel-Feld und der
Speicherblock - jeweils getrennt.
"""

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.control_ui import MechDetailsButton
from services.infrastructure.spam_protection_service import SpamProtectionService

PROJEKT = Path(__file__).resolve().parents[2]
VORLAGE = PROJEKT / "app" / "templates" / "_spam_protection_modal.html"
SPAM_PFAD = "services.infrastructure.spam_protection_service.get_spam_protection_service"
NUTZER = 7733
KANAL = 99
SCHLUESSEL = f"mech_details_{KANAL}"
JETZT = 95_000.0


class _Mitschrift:
    """Reicht an den ECHTEN Dienst durch und haelt fest, was gefragt wurde."""

    def __init__(self, echt):
        self._echt = echt
        self.gefragt = []
        self.vermerkt = []

    def is_on_cooldown(self, user_id, action_type):
        self.gefragt.append((user_id, action_type))
        return self._echt.is_on_cooldown(user_id, action_type)

    def add_user_cooldown(self, user_id, action_type):
        self.vermerkt.append((user_id, action_type))
        return self._echt.add_user_cooldown(user_id, action_type)

    def __getattr__(self, name):
        return getattr(self._echt, name)


def _dienst(tmp_path):
    return _Mitschrift(SpamProtectionService(config_dir=str(tmp_path)))


async def _druecke(dienst, cog=None):
    interaktion = MagicMock()
    interaktion.user.id = NUTZER
    interaktion.user.name = "pruefer"
    interaktion.response.defer = AsyncMock()
    interaktion.response.send_message = AsyncMock()
    interaktion.response.is_done = MagicMock(return_value=False)
    interaktion.followup.send = AsyncMock()
    knopf = MechDetailsButton(cog if cog is not None else MagicMock(), KANAL)
    with patch(SPAM_PFAD, return_value=dienst):
        try:
            await knopf.callback(interaktion)
        except TypeError as e:
            # Begruendung wie in test_mechknoepfe_bremsen_ueber_den_dienst.py.
            if "can't be awaited" not in str(e):
                raise
    return interaktion


def test_der_knopf_traegt_die_erwartete_kennung():
    """Sicherung: GENAUER Wert, nicht blosse Existenz."""
    assert MechDetailsButton(MagicMock(), KANAL).custom_id == SCHLUESSEL


def test_mech_details_steht_in_den_vorgaben(tmp_path):
    """DER BEFUND, Regler erste Stufe: ohne Eintrag nur die Ersatzregel."""
    vorgaben = SpamProtectionService(config_dir=str(tmp_path))._get_default_config().button_cooldowns
    assert vorgaben.get("mech_details") == 5, (
        f"mech_details fehlt in den Vorgaben ({sorted(vorgaben)}) - der Knopf "
        "bremste nach der unsichtbaren Ersatzregel."
    )


def test_mech_details_hat_ein_panelfeld():
    """DER BEFUND, Regler zweite Stufe - mit dem Startwert der Vorgabe.

    Kein anderer Test vergleicht Panel-Startwerte je Knopf mit den Vorgaben
    (test_vorgabewerte_widersprechen_sich_nicht prueft nur die
    Minutengrenzen). Ein abweichender Startwert zeigte dem Betreiber eine Zahl,
    nach der nicht gebremst wird, bis er zum ersten Mal speichert.
    """
    assert 'id="button_mech_details" value="5"' in VORLAGE.read_text(encoding="utf-8")


def test_mech_details_ueberlebt_das_speichern():
    """DER BEFUND, Regler dritte Stufe: Der Speicherblock ist eine FESTE
    Aufzaehlung; was dort fehlt, faellt beim ersten Speichern heraus."""
    text = VORLAGE.read_text(encoding="utf-8")
    anfang = text.index("button_cooldowns: {")
    assert "button_mech_details" in text[anfang:text.index("}", anfang)]


@pytest.mark.asyncio
async def test_der_dienst_wird_gefragt_und_vermerkt(tmp_path):
    """DER BEFUND: Der Knopf fragt den Dienst nicht."""
    dienst = _dienst(tmp_path)

    await _druecke(dienst)

    assert dienst.gefragt == [(NUTZER, SCHLUESSEL)], (
        f"is_on_cooldown wurde nicht mit {SCHLUESSEL!r} gerufen, sondern "
        f"{dienst.gefragt!r}."
    )
    assert dienst.vermerkt == [(NUTZER, SCHLUESSEL)]


@pytest.mark.asyncio
async def test_der_zweite_druck_wird_abgewiesen(tmp_path, monkeypatch):
    """DER BEFUND, Wirkung - vor dem defer, nur fuer den Druckenden sichtbar,
    und danach laeuft nichts weiter."""
    monkeypatch.setattr(time, "time", lambda: JETZT)
    dienst = _dienst(tmp_path)
    dienst._echt.add_user_cooldown(NUTZER, SCHLUESSEL)
    cog = MagicMock()

    interaktion = await _druecke(dienst, cog)

    sender = interaktion.response.send_message
    sender.assert_awaited_once()
    meldung = sender.await_args.args[0]
    assert "before using this button again" in meldung, meldung
    assert "wait 5.0 more" in meldung, meldung
    assert sender.await_args.kwargs.get("ephemeral") is True
    interaktion.response.defer.assert_not_awaited()
    assert cog.mock_calls == []


@pytest.mark.asyncio
async def test_abgeschalteter_spamschutz_bremst_nichts(tmp_path):
    """Abgrenzung: abgeschaltet heisst weder fragen noch vermerken."""
    dienst = _dienst(tmp_path)

    with patch.object(dienst._echt, "is_enabled", return_value=False):
        await _druecke(dienst)

    assert dienst.gefragt == [] and dienst.vermerkt == []


def test_das_panelfeld_hat_eine_beschriftung():
    """DER BEFUND, Regler vierte Stufe: Die Beschriftung muss im Katalog stehen.

    Die Katalog-Paritaet (test_pkg_d2_frontend_csrf_i18n.py) prueft nur, dass
    alle Sprachen DIESELBEN Schluessel haben; ihr Suchmuster fuer Vorlagen
    schliesst Jinjas ``_t(...)`` aus. Fehlte der Schluessel ueberall gleich,
    zeigte das Panel den rohen Schluessel - und kein Test merkte es.
    """
    import json
    vorlage = VORLAGE.read_text(encoding="utf-8")
    assert "_t('web.spam.button_mech_details')" in vorlage
    katalog = json.loads((PROJEKT / "locales" / "en.json").read_text(encoding="utf-8"))
    assert katalog.get("web.spam.button_mech_details") == "Mech Details"
