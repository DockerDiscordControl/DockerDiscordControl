# -*- coding: utf-8 -*-
# @deckt Z7
"""Z7, Stelle 2 von 5 - die Container-Konfiguration.

``ContainerStatusService._deactivate_container`` (``container_status_service.py:118``)
schreibt die Konfigurationsdatei eines Containers mit einem schlichten
``open(..., "w")`` neu (:153). Ein Abbruch mitten darin laesst die Datei nicht
veraltet, sondern **abgeschnitten oder leer** zurueck - und das ist die vom
Nutzer gepflegte Konfiguration dieses Containers: Anzeigename, erlaubte Aktionen,
Reihenfolge, Info-Texte.

Aufgerufen wird die Methode automatisch, wenn Docker einen Container dauerhaft
als nicht vorhanden meldet. Der Nutzer loest sie also nicht aus und sieht sie
nicht - "unbemerkt schlaegt selten" in seiner teuren Form.

Warum diese Stelle vor den anderen drei kommt: Von den verbliebenen vier ist sie
die einzige, die Nutzerkonfiguration schreibt. ``member_count`` beeinflusst
Spendenziele, ``mech_reset_service`` und ``server_order`` sind wiederherstellbar
bzw. kosmetisch.

GEGENPROBE (durchgefuehrt 2026-09-16):

Vor der Korrektur schlug ``test_abgebrochener_schreibvorgang...`` an seiner
eigenen Zusicherung fehl, und wieder war das Ergebnis schlimmer als erwartet::

    assert ''

Die Konfigurationsdatei war nicht halb geschrieben, sondern **restlos leer** -
``open(..., "w")`` kuerzt sie beim Oeffnen, bevor ein Byte geschrieben wird.
Betroffen sind die vom Nutzer gepflegten Einstellungen dieses Containers.

Der Waechter ``fehler.getroffen`` schlug nicht an, und ``_deactivate_container``
meldete korrekt ``False``. Der befuerchtete Zweitbefund - ein gescheiterter
Schreibvorgang, der als Erfolg gemeldet wird (Z3) - ist also NICHT eingetreten.

Nach der Korrektur: ``tests/spec`` 33 gruen (nur die beiden absichtlichen
Z10-Fehlschlaege offen), ``tests/unit/extended`` 731 gruen,
``tests/unit/services/infrastructure`` 197 gruen.

Mitgezogen: ``tests/unit/extended/test_docker_infra_gaps.py`` steuert denselben
Fehlerpfad an. Dort steckten ZWEI Fehler, und der zweite kam erst durch Messen
ans Licht:

1. Der Test patchte nur ``builtins.open``. Seit der Schreibvorgang ueber
   ``os.fdopen`` laeuft, ging der Patch ins Leere.
2. Der naheliegende Ausweg - jedes ``open`` scheitern lassen - prueft den
   Schreibvorgang ueberhaupt nicht: ``_deactivate_container`` LIEST die Datei
   zuerst, der Lesevorgang flog, die Methode gab ``False`` zurueck, und die
   Zusicherung war erfuellt, ohne dass je geschrieben wurde.

Belegt durch Mutation: mit einem ``atomic_write_text``, das alle Fehler
verschluckt, wurde der Test hier oben rot - der dortige blieb gruen. Ein
gruener Test beweist eben nicht, dass er greift. Er scheitert jetzt nur noch bei
Schreibzugriffen, auf beiden Wegen.
"""

import json
import os

import pytest

from services.infrastructure.container_status_service import ContainerStatusService


class _SchreibfehlerBeimSchreiben:
    """Laesst Dateien oeffnen, aber jeden Schreibvorgang scheitern.

    Faengt ``builtins.open`` UND ``os.fdopen`` ab - implementierungsunabhaengig:
    die heutige Fassung schreibt ueber ``open(...)``, eine atomare ueber
    ``mkstemp`` + ``os.fdopen``. Wer nur ``builtins.open`` abfaengt, baut einen
    Test, der nach der Korrektur stillschweigend nichts mehr prueft - genau das
    ist ``tests/unit/extended/test_docker_infra_gaps.py:1112`` passiert, das
    denselben Fehlerpfad ueber ``patch("builtins.open", ...)`` ansteuert.
    """

    def __init__(self, monkeypatch):
        self.getroffen = False
        echtes_open = open
        echtes_fdopen = os.fdopen

        def _praepariere(fh):
            self.getroffen = True

            def _wirft(*_a, **_k):
                raise OSError("kein Platz auf dem Geraet")

            fh.write = _wirft
            return fh

        def _open(datei, modus="r", *a, **kw):
            fh = echtes_open(datei, modus, *a, **kw)
            return _praepariere(fh) if ("w" in modus or "a" in modus) else fh

        def _fdopen(fd, modus="r", *a, **kw):
            fh = echtes_fdopen(fd, modus, *a, **kw)
            return _praepariere(fh) if ("w" in modus or "a" in modus) else fh

        monkeypatch.setattr("builtins.open", _open)
        monkeypatch.setattr(os, "fdopen", _fdopen)


URSPRUNG = {
    "name": "nginx",
    "docker_name": "nginx",
    "active": True,
    "allowed_actions": ["start", "stop", "restart"],
    "display_name": "Webserver",
}


@pytest.fixture
def dienst(tmp_path, monkeypatch):
    """Dienst mit einer echten Container-Datei in eigener Ablage."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    ordner = tmp_path / "containers"
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "nginx.json").write_text(json.dumps(URSPRUNG, indent=2), encoding="utf-8")
    return ContainerStatusService(), ordner / "nginx.json"


def test_abgebrochener_schreibvorgang_laesst_die_konfiguration_unversehrt(dienst, monkeypatch):
    """Scheitert das Schreiben, steht die Konfiguration noch vollstaendig da."""
    service, datei = dienst
    fehler = _SchreibfehlerBeimSchreiben(monkeypatch)

    ergebnis = service._deactivate_container("nginx")

    assert fehler.getroffen, (
        "Der Schreibfehler wurde gar nicht ausgeloest - dieser Test prueft dann "
        "nichts. Vermutlich schreibt die Umsetzung ueber einen dritten Weg."
    )
    assert ergebnis is False, "Ein gescheiterter Schreibvorgang darf nicht als Erfolg gelten"

    inhalt = datei.read_text(encoding="utf-8")
    assert inhalt.strip(), (
        "Die Container-Konfiguration ist leer - ein Abbruch beim automatischen "
        "Deaktivieren hat die vom Nutzer gepflegten Einstellungen vernichtet"
    )
    assert json.loads(inhalt) == URSPRUNG, (
        f"Die Konfiguration wurde beschaedigt: {inhalt!r}"
    )


def test_erfolgreiches_deaktivieren_setzt_active_false(dienst):
    """Die Gegenrichtung: ohne Fehler wird korrekt geschrieben.

    Ohne diesen Fall koennte man ``_deactivate_container`` auf "schreibt nie"
    verschaerfen und der Test oben bliebe gruen.
    """
    service, datei = dienst

    assert service._deactivate_container("nginx") is True

    danach = json.loads(datei.read_text(encoding="utf-8"))
    assert danach["active"] is False
    assert danach["allowed_actions"] == URSPRUNG["allowed_actions"], (
        "Beim Deaktivieren gingen andere Einstellungen verloren"
    )


def test_keine_temp_reste_nach_erfolg(dienst):
    """Eine atomare Umsetzung raeumt ihre Temp-Datei auf."""
    service, datei = dienst
    service._deactivate_container("nginx")

    reste = [p.name for p in datei.parent.iterdir() if p.name != datei.name]
    assert reste == [], f"Temp-Reste geblieben: {reste}"
