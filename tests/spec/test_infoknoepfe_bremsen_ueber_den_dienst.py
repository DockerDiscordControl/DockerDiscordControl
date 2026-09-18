# -*- coding: utf-8 -*-
"""Die drei Info-Knoepfe muessen ueber den Spam-Dienst bremsen - mit EIGENEM Eimer.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

DER BEFUND. Drei Knoepfe in ``status_info_integration.py`` holen vom Dienst nur
die DAUER und fuehren die Buchhaltung selbst, im Woerterbuch des Cogs::

    ProtectedInfoEditButton  :167  button_protected_edit_<nutzer>  Dauer aus "info"
    EditInfoButton           :237  button_info_<nutzer>            Dauer aus "info"
    ProtectedInfoButton      :1022 button_protected_<nutzer>       Dauer aus "info"

``is_on_cooldown`` und ``add_user_cooldown`` werden nie gerufen. Damit wirkt die
MINUTENGRENZE aus dem Panel fuer diese drei nicht - sie zaehlt in
``add_user_cooldown``, und dort kommen sie nie an.

WAS SICH FUER DEN NUTZER NICHT AENDERN DARF, und das ist der heikle Teil: Die
drei haben heute DREI GETRENNTE Eimer, holen ihre Dauer aber gemeinsam unter
``"info"``. Wuerde man sie einfach auf ``is_on_cooldown(uid, "info")``
umstellen, verschmoelzen drei Sperren zu einer - wer die Info oeffnet, koennte
danach sekundenlang die Info nicht bearbeiten. Das waere eine spuerbare
Verschaerfung, die niemand beschlossen hat.

Deshalb bekommt jeder Knopf seinen EIGENEN Aktionsnamen, und die drei Namen
brauchen einen Eintrag in den Vorgaben mit dem Wert **3** - genau dem, was
``"info"`` heute liefert. Ohne Eintrag fielen sie auf die 5-Sekunden-
Ersatzregel (``get_button_cooldown:186``) und waeren LANGSAMER als heute::

    protected_info_edit  3
    edit_info            3
    protected_info       3

VIER FALLEN DER VORRICHTUNG, vorab benannt:

1. Der Cog darf KEIN blankes ``MagicMock`` sein - der heutige Code fragt
   ``hasattr(self.cog, '_button_cooldowns')``, und ein MagicMock bejaht das
   immer. Der Knopf wuerde nie abweisen, der Test pruefte die Attrappe.
2. ``response.send_message`` wird von der Abfuhr (:174/:244/:1029) UND vom
   Fehlerpfad (:206/:276/:1062) benutzt. Ein blosses ``assert_awaited_once``
   waere also auch durch einen Fehler in der Tiefe erfuellt. Deshalb zusaetzlich
   der WORTLAUT und die Feststellung, dass ``send_modal`` NICHT gerufen wurde -
   das ist der Erfolgsweg (:200/:270/:1056).
3. Alle drei Rueckrufe enden auf ``except Exception``; Fehler aus der Tiefe
   werden verschluckt. Ein Test, der nur das Ausbleiben von Fehlern prueft,
   waere hohl gruen. Hier wird ausschliesslich POSITIV behauptet.
4. Der Dienst ist ein ECHTER ``SpamProtectionService`` auf ``tmp_path``, nur zum
   Mitschreiben durchgereicht - eine reine Attrappe lieferte jede Zahl.

ABGRENZUNG: Ersetzt wird auf dem MODULPFAD, weil der Import erst IN der Methode
geschieht. Und dieser Test sagt nichts ueber die neun weiteren Stellen, die
ebenfalls eigene Buchhaltung fuehren - eigene Befunde.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.status_info_integration import (
    EditInfoButton,
    ProtectedInfoButton,
    ProtectedInfoEditButton,
)
from services.infrastructure.spam_protection_service import SpamProtectionService

SPAM_PFAD = "services.infrastructure.spam_protection_service.get_spam_protection_service"
NUTZER = 9317
BEHAELTER = {"docker_name": "pruef", "name": "Pruefcontainer"}

# Klasse -> erwarteter Aktionsname. Bewusst je ein eigener Name: Die drei
# fuehren heute getrennte Eimer, und das muss so bleiben.
KNOEPFE = [
    (ProtectedInfoEditButton, "protected_info_edit"),
    (EditInfoButton, "edit_info"),
    (ProtectedInfoButton, "protected_info"),
]


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


def _cog():
    """Cog mit ECHTEM Woerterbuch - siehe Falle 1 im Kopftext."""
    cog = MagicMock()
    cog._button_cooldowns = {}
    return cog


def _interaktion():
    interaktion = MagicMock()
    interaktion.user.id = NUTZER
    interaktion.channel.id = 3
    interaktion.response.send_message = AsyncMock()
    interaktion.response.send_modal = AsyncMock()
    interaktion.response.defer = AsyncMock()
    interaktion.followup.send = AsyncMock()
    return interaktion


def _baue(klasse, cog):
    return klasse(cog, BEHAELTER, {})


async def _druecke(knopf, dienst):
    interaktion = _interaktion()
    with patch(SPAM_PFAD, return_value=dienst):
        await knopf.callback(interaktion)
    return interaktion


def test_die_drei_knoepfe_lassen_sich_bauen():
    """Sicherung gegen ein stumpfes Werkzeug - vor und nach der Korrektur gruen."""
    for klasse, _name in KNOEPFE:
        knopf = _baue(klasse, _cog())
        assert knopf.container_name == "pruef", f"{klasse.__name__} baut nicht"


def test_die_drei_namen_haben_den_heutigen_wert(tmp_path):
    """Zweite Sicherung, und die wichtigere: KEINE stille Verlangsamung.

    Die drei neuen Namen muessen 3 liefern - den heutigen Wert von "info".
    Fehlt ein Eintrag, greift die Ersatzregel mit 5, und die Knoepfe waeren
    langsamer als vorher, ohne dass es jemand beschlossen hat.
    """
    dienst = SpamProtectionService(config_dir=str(tmp_path))

    assert dienst.get_button_cooldown("info") == 3, "Bezugswert hat sich geaendert"
    assert dienst.get_button_cooldown("gibt_es_nicht") == 5, "Ersatzregel hat sich geaendert"
    for _klasse, name in KNOEPFE:
        assert dienst.get_button_cooldown(name) == 3, (
            f"{name!r} liefert {dienst.get_button_cooldown(name)} statt 3 - der "
            "Knopf waere nach der Umstellung langsamer als heute."
        )


@pytest.mark.parametrize("klasse,name", KNOEPFE, ids=lambda x: getattr(x, "__name__", x))
@pytest.mark.asyncio
async def test_der_dienst_wird_gefragt_und_vermerkt(tmp_path, klasse, name):
    """DER BEFUND: Die zustandsbehafteten Methoden werden nie gerufen."""
    dienst = _dienst(tmp_path)
    knopf = _baue(klasse, _cog())

    await _druecke(knopf, dienst)

    assert dienst.gefragt == [(NUTZER, name)], (
        f"{klasse.__name__}: is_on_cooldown wurde nicht mit {name!r} gerufen, "
        f"sondern {dienst.gefragt!r}. Der Knopf bremst am Dienst vorbei und "
        "zahlt nicht in die Minutengrenze ein."
    )
    assert dienst.vermerkt == [(NUTZER, name)], (
        f"{klasse.__name__}: Der angenommene Druck wurde nicht vermerkt "
        f"({dienst.vermerkt!r})."
    )


@pytest.mark.parametrize("klasse,name", KNOEPFE, ids=lambda x: getattr(x, "__name__", x))
@pytest.mark.asyncio
async def test_der_zweite_druck_wird_abgewiesen(tmp_path, klasse, name):
    """DER BEFUND, Wirkung: Was im Dienst steht, muss den Knopf bremsen."""
    dienst = _dienst(tmp_path)
    knopf = _baue(klasse, _cog())
    dienst.add_user_cooldown(NUTZER, name)
    dienst.vermerkt.clear()

    interaktion = await _druecke(knopf, dienst)

    interaktion.response.send_modal.assert_not_awaited()
    interaktion.response.send_message.assert_awaited_once()
    args = interaktion.response.send_message.await_args.args
    assert args, "Die Abfuhr traegt keinen Text - so ruft der Fehlerpfad, nicht die Bremse."
    assert "before using this button again" in args[0], (
        f"Gesendet wurde nicht die Abklingzeit-Abfuhr: {args[0]!r}"
    )
    assert interaktion.response.send_message.await_args.kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_die_drei_sperren_sich_nicht_gegenseitig(tmp_path):
    """DER HEIKLE TEIL: getrennte Eimer, wie heute.

    Ohne diesen Test waere eine Korrektur gruen, die alle drei auf denselben
    Schluessel legt - und damit drei Sperren zu einer verschmilzt.
    """
    dienst = _dienst(tmp_path)
    dienst.add_user_cooldown(NUTZER, "protected_info_edit")

    knopf = _baue(EditInfoButton, _cog())
    interaktion = await _druecke(knopf, dienst)

    interaktion.response.send_modal.assert_awaited_once()
    interaktion.response.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_die_eigene_buchhaltung_am_cog_entfaellt(tmp_path):
    """Eine Ablage statt zweier - sonst wird die naechste Korrektur nur an
    einer der beiden Stellen gemacht."""
    dienst = _dienst(tmp_path)
    cog = _cog()
    knopf = _baue(ProtectedInfoEditButton, cog)

    await _druecke(knopf, dienst)

    assert cog._button_cooldowns == {}, (
        f"Der Knopf schreibt weiterhin in cog._button_cooldowns "
        f"({cog._button_cooldowns!r}) - dieselbe Information an zwei Orten."
    )
