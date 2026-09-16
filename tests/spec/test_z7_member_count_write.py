# -*- coding: utf-8 -*-
# @deckt Z7
"""Z7, Stelle 3 von 5 - die Mitgliederzahl-Momentaufnahme.

``MemberCountService.persist_member_count_snapshot``
(``services/member_count/service.py:153``) schreibt die Datei mit einem schlichten
``Path.write_text`` (:174). Ein Abbruch mitten darin laesst sie abgeschnitten
zurueck.

Warum das mehr ist als eine Zahl: Die Mitgliederzahl bestimmt die **Preise** im
Spendensystem - ``requirement_for_level_and_bin(..., member_count=...)`` leitet
daraus ab, was die naechste Stufe kostet. Eine halb geschriebene Datei ist
entweder unlesbar (dann faellt die Berechnung auf einen Standardwert zurueck)
oder enthaelt eine falsche Zahl. Beides verschiebt lautlos, wie viel Geld eine
Stufe kostet - niemand sieht es, und die Anzeige wirkt normal.

Abgrenzung zum vorhandenen Test: ``tests/test_member_count_service.py:121``
prueft, dass die vier Felder korrekt in der Datei landen. Das ist ein echter
Vertrag und bleibt unangetastet - er sagt nur nichts ueber den Absturzfall.
Hier wird ergaenzt, nicht gedoppelt.

WICHTIG zum Abfangen: Diese Stelle schreibt ueber ``Path.write_text``, nicht
ueber ``open(..., "w")``. Der in den beiden vorigen Z7-Durchgaengen bewaehrte
Helfer faengt ``builtins.open`` und ``os.fdopen`` ab - beides greift hier NICHT.
Haette ich ihn ungeprueft uebernommen, waere der Waechter angesprungen und der
Test aus dem falschen Grund gescheitert. ``Path.write_text`` wird deshalb
zusaetzlich abgefangen.

GEGENPROBE (durchgefuehrt 2026-09-16) - dieser Test war ZWEIMAL wertlos, bevor
er etwas bewies. Beide Male war er gruen:

*Fassung 1:* ``_write_text`` warf sofort, ohne die Datei anzufassen. Dann wird
nie gekuerzt, der alte Inhalt ueberlebt, und die Zusicherung unten ist erfuellt -
durch die Attrappe, nicht durch den Code. Der Abfangpunkt lag VOR dem Schaden.

*Fassung 2 (derselbe Lauf):* ``test_keine_temp_reste_nach_erfolg`` zaehlte
"alles ausser der Zieldatei" als Rest und war deshalb aus dem falschen Grund rot -
``ProgressPaths.from_base_dir`` legt in derselben Ablage auch ``events.jsonl``
und ``last_seq.txt`` an. Die Annahme aus dem vorigen Z7-Durchgang (Zieldatei
liegt allein) war ungeprueft uebernommen.

*Fassung 3:* Der Schaden wird nachgestellt statt verhindert - die Datei wird mit
"w" geoeffnet (und damit gekuerzt), DANN kommt der Fehler. Erst jetzt rot::

    assert ''   # Die Momentaufnahme ist leer

Nach der Korrektur auf ``atomic_write_json``: 3 gruen. Der vorhandene
``tests/test_member_count_service.py`` blieb unveraendert gruen (4),
``tests/unit/extended`` ebenfalls (731).

WIRKUNGSNACHWEIS per Mutation: mit einem ``atomic_write_text``, das alle Fehler
verschluckt, wird dieser Test rot; wiederhergestellt wieder gruen. Ein gruener
Test beweist nicht, dass er greift - nur die Mutation tut das.
"""

import json
import os
from pathlib import Path

import pytest

import services.member_count.service as mc_modul
from services.member_count.service import MemberCountService
from services.mech.progress_paths import ProgressPaths

URSPRUNG = {
    "count": 42,
    "last_updated": "2026-01-01T00:00:00+00:00",
    "source": "status_channels",
    "description": "Bestand vor dem Absturz",
}


class _SchreibfehlerBeimSchreiben:
    """Laesst jeden Schreibvorgang scheitern - auf allen drei Wegen.

    ``builtins.open`` und ``os.fdopen`` decken die bisherigen Stellen ab,
    ``Path.write_text`` diese hier. Eine atomare Umsetzung wuerde ueber
    ``os.fdopen`` schreiben; ohne den dritten Weg wuerde der Waechter unten
    anschlagen, statt die Zusicherung zu pruefen.
    """

    def __init__(self, monkeypatch):
        self.getroffen = False
        echtes_open, echtes_fdopen = open, os.fdopen
        echtes_write_text = Path.write_text

        def _wirft(*_a, **_k):
            raise OSError("kein Platz auf dem Geraet")

        def _praepariere(fh):
            self.getroffen = True
            fh.write = _wirft
            return fh

        def _open(datei, modus="r", *a, **kw):
            fh = echtes_open(datei, modus, *a, **kw)
            return _praepariere(fh) if ("w" in modus or "a" in modus) else fh

        def _fdopen(fd, modus="r", *a, **kw):
            fh = echtes_fdopen(fd, modus, *a, **kw)
            return _praepariere(fh) if ("w" in modus or "a" in modus) else fh

        def _write_text(selbst, *a, **kw):
            # Den Schaden NACHSTELLEN, nicht verhindern. Die erste Fassung warf
            # sofort und fasste die Datei nie an - dann wird auch nie gekuerzt,
            # der alte Inhalt ueberlebt, und die Zusicherung unten ist erfuellt:
            # durch die Attrappe, nicht durch den Code. Der Test war gruen, ohne
            # irgendetwas zu beweisen.
            #
            # Das echte ``Path.write_text`` oeffnet mit "w" und kuerzt damit beim
            # Oeffnen. Genau das wird hier getan, bevor der Schreibfehler kommt.
            self.getroffen = True
            with echtes_open(selbst, "w", encoding="utf-8"):
                pass
            raise OSError("kein Platz auf dem Geraet")

        monkeypatch.setattr("builtins.open", _open)
        monkeypatch.setattr(os, "fdopen", _fdopen)
        monkeypatch.setattr(Path, "write_text", _write_text)
        self._echtes_write_text = echtes_write_text


@pytest.fixture
def dienst(tmp_path, monkeypatch):
    """Dienst mit einer bereits gefuellten Momentaufnahme."""
    pfade = ProgressPaths.from_base_dir(tmp_path, create_missing=True)
    monkeypatch.setattr(mc_modul, "get_progress_paths", lambda: pfade)
    pfade.member_count_file.write_text(json.dumps(URSPRUNG, indent=2), encoding="utf-8")
    return MemberCountService(), pfade.member_count_file


def test_abgebrochener_schreibvorgang_laesst_die_momentaufnahme_unversehrt(dienst, monkeypatch):
    """Scheitert das Schreiben, steht der alte Stand noch vollstaendig da."""
    service, datei = dienst
    fehler = _SchreibfehlerBeimSchreiben(monkeypatch)

    with pytest.raises(OSError):
        service.persist_member_count_snapshot(
            99, source="status_channels", description="Neuer Stand"
        )

    assert fehler.getroffen, (
        "Der Schreibfehler wurde gar nicht ausgeloest - dieser Test prueft dann "
        "nichts. Vermutlich schreibt die Umsetzung ueber einen vierten Weg."
    )
    inhalt = datei.read_text(encoding="utf-8")
    assert inhalt.strip(), (
        "Die Momentaufnahme ist leer - die Mitgliederzahl bestimmt die Preise "
        "im Spendensystem, und eine unlesbare Datei verschiebt sie lautlos"
    )
    assert json.loads(inhalt) == URSPRUNG, (
        f"Die Momentaufnahme wurde beschaedigt: {inhalt!r}"
    )


def test_erfolgreiches_schreiben_ersetzt_den_stand(dienst):
    """Die Gegenrichtung: ohne Fehler wird korrekt ersetzt.

    Ohne diesen Fall koennte man die Methode auf "schreibt nie" verschaerfen und
    der Test oben bliebe gruen.
    """
    service, datei = dienst

    service.persist_member_count_snapshot(
        99, source="status_channels", description="Neuer Stand", note="Probe"
    )

    danach = json.loads(datei.read_text(encoding="utf-8"))
    assert danach["count"] == 99
    assert danach["note"] == "Probe"


def test_keine_temp_reste_nach_erfolg(dienst):
    """Eine atomare Umsetzung raeumt ihre Temp-Datei auf.

    Anders als in den beiden vorigen Z7-Durchgaengen liegt die Zieldatei hier
    NICHT allein in ihrem Verzeichnis: ``ProgressPaths.from_base_dir`` legt in
    derselben Ablage auch ``events.jsonl`` und ``last_seq.txt`` an. Die erste
    Fassung dieses Tests zaehlte "alles ausser der Zieldatei" als Rest und war
    deshalb aus dem falschen Grund rot - die Annahme aus dem vorigen Fall war
    ungeprueft uebernommen.

    Geprueft wird jetzt der Bestand vorher gegen nachher: was neu dazukommt und
    bleibt, ist ein Rest.
    """
    service, datei = dienst
    vorher = {p.name for p in datei.parent.iterdir() if p.is_file()}

    service.persist_member_count_snapshot(
        99, source="status_channels", description="Neuer Stand"
    )

    nachher = {p.name for p in datei.parent.iterdir() if p.is_file()}
    reste = sorted(nachher - vorher)
    assert reste == [], f"Temp-Reste geblieben: {reste}"
