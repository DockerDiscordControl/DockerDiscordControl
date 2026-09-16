# -*- coding: utf-8 -*-
# @deckt Z7
"""Z7 - Eine Konfiguration ueberlebt jeden Schreibvorgang.

Jeder Schreibvorgang auf Konfigurations- oder Zustandsdateien ist atomar
(Temp-Datei + Umbenennen). Ein Absturz mitten im Schreiben laesst die alte Datei
unversehrt.

Diese Datei beginnt mit ``next_seq()`` (``services/mech/progress_service.py:256``).
Von den vier nicht-atomaren Stellen der Bestandsaufnahme ist das die
schwerwiegendste: sie liest, erhoeht und schreibt denselben Zaehler - und dieser
Zaehler nummeriert das Spendenbuch, dessen Unversehrtheit Z1 zusichert. Ein
Abbruch hinterlaesst dort nicht bloss eine kaputte Datei, sondern kann eine
Sequenznummer doppelt vergeben.

Die uebrigen drei Stellen (``_deactivate_container``,
``persist_member_count_snapshot``, ``save_server_order``) folgen als eigene
Durchgaenge - absteigend nach Schaden, nicht nach Bequemlichkeit.

Zur Sperre, zur Abgrenzung: ``next_seq()`` laeuft nachweislich unter ``LOCK``
(``progress_service.py:1027`` umschliesst :1044, :1066, :1071). Die Sperre
schuetzt gegen Verschraenkung, NICHT gegen Absturz - auch unter Sperre
hinterlaesst ein Abbruch mitten im Schreiben eine abgeschnittene Datei. Dieser
Test deckt den Absturz ab, nicht die Nebenlaeufigkeit.

GEGENPROBE (durchgefuehrt 2026-09-16):

Vor der Korrektur schlug ``test_abgebrochener_schreibvorgang...`` an seiner
eigenen Zusicherung fehl - und das Ergebnis war schlimmer als erwartet::

    assert '' == '5'

Die Datei war nicht halb geschrieben, sondern **leer**: ``open(..., "w")`` kuerzt
sie bereits beim Oeffnen, bevor ein einziges Byte geschrieben wird. ``next_seq()``
haette danach ``int("" or 0)`` gelesen und wieder bei 1 begonnen - mitten in einem
Ereignislog, in dem die Nummern 1 bis 5 bereits vergeben sind.

Der Waechter ``fehler.getroffen`` schlug NICHT an und ``pytest.raises(OSError)``
hielt: der Fehler kam also wirklich an und wurde nicht verschluckt. Das war der
Zweck dieser beiden Absicherungen - sie trennen "Zusicherung gebrochen" von
"Test hat gar nicht gegriffen".

Nach der Korrektur 18 gruen; die Gruppen mech/donation/integration/extended
blieben unveraendert gruen (447 / 52 / 5 / 731).

Ehrlich zur Aussagekraft der drei Tests: ``test_keine_temp_reste_nach_erfolg``
war vorher trivial gruen, weil die alte Fassung ueberhaupt keine Temp-Datei
anlegte. Er prueft erst seit der Korrektur etwas und faellt, wenn das Aufraeumen
fehlt. ``test_erfolgreicher_schreibvorgang_erhoeht_weiterhin`` war vorher wie
nachher gruen - er existiert nur, damit man die Sperre nicht auf "schreibt nie"
verschaerfen kann.
"""

import os

import pytest

import services.mech.progress_service as ps


class _SchreibfehlerBeimSchreiben:
    """Laesst Dateien oeffnen, aber jeden Schreibvorgang scheitern.

    Faengt ``builtins.open`` UND ``os.fdopen`` ab. Beides ist noetig, und zwar
    absichtlich implementierungsunabhaengig: die heutige Fassung schreibt ueber
    ``open(...)``, eine atomare Fassung ueber ``mkstemp`` + ``os.fdopen``. Wer
    nur ``builtins.open`` abfaengt, baut einen Test, der nach der Korrektur
    stillschweigend nichts mehr prueft - genau das ist
    ``tests/unit/extended/test_docker_infra_gaps.py:1112`` passiert.
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


@pytest.fixture
def zaehler(tmp_path, monkeypatch):
    """Sequenzzaehler mit bekanntem Stand in einer eigenen Ablage."""
    datei = tmp_path / "last_seq.txt"
    datei.write_text("5", encoding="utf-8")
    monkeypatch.setattr(ps, "SEQ_FILE", datei)
    return datei


def test_abgebrochener_schreibvorgang_laesst_den_zaehler_unversehrt(zaehler, monkeypatch):
    """Scheitert das Schreiben, steht der alte Stand noch in der Datei.

    Heute oeffnet ``next_seq()`` die Datei mit ``"w"`` - das kuerzt sie bereits
    beim Oeffnen, noch bevor irgendetwas geschrieben wurde. Der Zaehler ist dann
    weg, und mit ihm die Nummerierung des Spendenbuchs.
    """
    fehler = _SchreibfehlerBeimSchreiben(monkeypatch)

    with pytest.raises(OSError):
        ps.next_seq()

    assert fehler.getroffen, (
        "Der Schreibfehler wurde gar nicht ausgeloest - dieser Test prueft dann "
        "nichts. Vermutlich schreibt die Umsetzung ueber einen dritten Weg, der "
        "hier nicht abgefangen wird."
    )
    assert zaehler.read_text(encoding="utf-8").strip() == "5", (
        "Der Schreibvorgang ist gescheitert und hat den Zaehler dabei zerstoert - "
        "die naechste Sequenznummer beginnt wieder bei 1 und vergibt Nummern "
        "doppelt, die im Spendenbuch bereits vorkommen"
    )


def test_erfolgreicher_schreibvorgang_erhoeht_weiterhin(zaehler):
    """Die Gegenrichtung: ohne Fehler zaehlt es normal weiter.

    Ohne diesen Fall koennte man ``next_seq()`` auf "schreibt nie" verschaerfen
    und der Test oben bliebe gruen.
    """
    assert ps.next_seq() == 6
    assert zaehler.read_text(encoding="utf-8").strip() == "6"
    assert ps.next_seq() == 7


def test_keine_temp_reste_nach_erfolg(zaehler):
    """Eine atomare Umsetzung raeumt ihre Temp-Datei auf.

    Nicht kosmetisch: liegen Reste herum, sammeln sie sich in der Ablage des
    Spendenbuchs an, und ein spaeterer Leser kann sie nicht von echten Dateien
    unterscheiden.
    """
    ps.next_seq()

    reste = [p.name for p in zaehler.parent.iterdir() if p.name != zaehler.name]
    assert reste == [], f"Temp-Reste geblieben: {reste}"
