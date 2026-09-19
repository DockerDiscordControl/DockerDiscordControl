# -*- coding: utf-8 -*-
"""Die Abklingzeit-Abweisung des Aufgaben-Loeschknopfs muss uebersetzt werden.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND. ``TaskDeleteButton.callback`` (``control_ui.py:1261``) weist mit
einem f-String OHNE ``_()`` ab: "Please wait ... before deleting another task."
Auf einem deutschen (franzoesischen, japanischen ...) Server erscheint diese
eine Abweisung englisch. Gemessen: Sie ist die einzige unuebersetzte
Abklingzeit-Abweisung unter cogs/.

DIE KORREKTUR folgt dem Hausmuster aus SPEC.md B10: der vorhandene,
in den Katalogen tatsaechlich uebersetzte Eintrag
"⏰ Please wait {remaining:.1f} more seconds before using this button again."
(de: "Bitte warten Sie noch ..."). Ein neuer Eintrag "... deleting another
task" braeuchte 39 Uebersetzungen, die ich nicht redlich erfinden kann - er
waere ueberall ausser in en.json ein englischer Platzhalter und haette den
Befund nur verschoben. Der Wortlaut wird dadurch allgemeiner; das ist der Preis.

WIE HIER GEPRUEFT WIRD: ``_`` im Modul wird durch eine Markierung ersetzt. Nur
ein Text, der durch ``_()`` ging, traegt sie. Das prueft den WEG, nicht eine
bestimmte Sprache - der Katalog selbst ist durch die Paritaetsvertraege
bewacht.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.control_ui import TaskDeleteButton
from services.infrastructure.spam_protection_service import SpamProtectionService

SPAM_PFAD = "services.infrastructure.spam_protection_service.get_spam_protection_service"
NUTZER = 8844


def _markiert(text):
    return f"«{text}»"


@pytest.mark.asyncio
async def test_die_abweisung_geht_durch_die_uebersetzung(tmp_path):
    dienst = SpamProtectionService(config_dir=str(tmp_path))
    dienst.add_user_cooldown(NUTZER, "task_delete")
    interaktion = MagicMock()
    interaktion.user.id = NUTZER
    interaktion.response.send_message = AsyncMock()
    knopf = TaskDeleteButton(MagicMock(), "t1", "Aufgabe", 0)

    with patch(SPAM_PFAD, return_value=dienst), patch("cogs.control_ui._", _markiert):
        await knopf.callback(interaktion)

    interaktion.response.send_message.assert_awaited_once()
    meldung = interaktion.response.send_message.await_args.args[0]
    # .format() fuellt den Platzhalter auch im markierten Text - geprueft
    # werden deshalb Anfang und Ende der Markierung samt Katalogwortlaut.
    assert meldung.startswith("«⏰ Please wait ") and meldung.endswith(
        " more seconds before using this button again.»"
    ), f"Die Abweisung ging nicht durch _() mit dem Katalogeintrag: {meldung!r}"
    assert interaktion.response.send_message.await_args.kwargs.get("ephemeral") is True
