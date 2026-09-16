# -*- coding: utf-8 -*-
# @deckt Z1
"""Z1 - Das Spendenbuch geht nie ohne Sicherung verloren.

Kein Vorgang leert oder ueberschreibt das Ereignislog, ohne vorher eine
wiederherstellbare Kopie anzulegen - auch dann nicht, wenn der Betreiber den
Vorgang selbst ausloest.

Warum das zaehlt: Das Ereignislog ist laut Betreiber die einzige Wahrheit der
lokalen Instanz ueber die echten Spenden. ``reset_donations`` schreibt heute
``""`` hinein (``services/donation/unified/reset.py:96``) - ohne Sicherung, ohne
Rueckfrage.

Die Konvention existiert im Projekt bereits: ``scripts/reset_donations.sh:32-44``
legt vor demselben Loeschvorgang ein ``backup_<Zeitstempel>/`` mit ``events.jsonl``
und ``snapshots/`` an und fragt zusaetzlich nach. Zwei Wege, dieselbe Aufgabe -
nur einer davon ist sorgfaeltig. Diese Tests verlangen die Sorgfalt auch vom
Dienstweg.

Die Tests fassen keine echten Daten an: ``reset_donations`` nimmt ``paths``
entgegen, sodass alles in einem Temp-Verzeichnis landet.

GEGENPROBE (durchgefuehrt 2026-09-16): Vor der Korrektur in
``services/donation/unified/reset.py`` schlugen alle drei Tests fehl, und zwar
jeder an seiner eigenen Zusicherung - nicht an einer Attrappe oder einem Import:

* ``test_reset_hinterlaesst_eine_wiederherstellbare_kopie`` -> ``assert []``
  (keine Kopie vorhanden)
* ``test_reset_bricht_ab_wenn_die_sicherung_scheitert`` ->
  ``assert '{"seq": 1, ...}' in ''`` (Log geleert, obwohl die Sicherung scheiterte)
* ``test_zweiter_reset_ueberschreibt_die_erste_sicherung_nicht`` -> ``assert set()``
  (schon die erste Sicherung fehlte)

Nach der Korrektur alle drei gruen; die Gruppen donation/integration/mech/web
blieben unveraendert gruen (52 / 5 / 447 / 358).
"""

import shutil
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services.donation.unified.reset import reset_donations
from services.mech.progress_paths import ProgressPaths

EREIGNISSE = [
    '{"seq": 1, "type": "DonationAdded", "donor": "Anna", "cents": 500}',
    '{"seq": 2, "type": "DonationAdded", "donor": "Bea", "cents": 250}',
    '{"seq": 3, "type": "LevelUp", "level": 2}',
]


@pytest.fixture
def paths(tmp_path):
    """Isolierte Ablage mit einem gefuellten Ereignislog."""
    p = ProgressPaths.from_base_dir(tmp_path / "progress")
    p.event_log.write_text("\n".join(EREIGNISSE) + "\n", encoding="utf-8")
    return p


@pytest.fixture
def dienste():
    """Attrappen fuer mech_service und event_manager.

    ``DonationResult.from_states`` liest nur ``level`` und ``Power`` per
    ``getattr``; ``emit_reset_event`` ruft nur ``emit_event``. Mehr braucht es
    nicht - und mehr soll der Test auch nicht anfassen.
    """
    mech_service = SimpleNamespace(
        get_state=lambda: SimpleNamespace(level=2, Power=7.5)
    )
    return mech_service, MagicMock()


def _wiederherstellbare_kopien(p: ProgressPaths):
    """Alle Dateien unter der Ablage, die den Inhalt des Logs bewahren.

    Bewusst breit gesucht: die Zusicherung verlangt eine wiederherstellbare
    Kopie, nicht einen bestimmten Dateinamen. Der Test schreibt der Umsetzung
    also nicht vor, wie sie zu sichern hat.
    """
    treffer = []
    for datei in p.data_dir.rglob("*"):
        if not datei.is_file() or datei == p.event_log:
            continue
        try:
            inhalt = datei.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if all(zeile in inhalt for zeile in EREIGNISSE):
            treffer.append(datei)
    return treffer


def test_reset_hinterlaesst_eine_wiederherstellbare_kopie(paths, dienste):
    """Nach dem Reset ist das Log leer - der Inhalt aber noch irgendwo lesbar."""
    mech_service, event_manager = dienste

    ergebnis = reset_donations(
        mech_service, event_manager, source="test", paths=paths
    )

    assert ergebnis.success is True
    assert paths.event_log.read_text(encoding="utf-8").strip() == "", \
        "Der Reset soll das Log tatsaechlich leeren"
    kopien = _wiederherstellbare_kopien(paths)
    assert kopien, (
        "Kein wiederherstellbarer Stand des Spendenbuchs gefunden - der Reset "
        "hat die einzige Aufzeichnung der echten Spenden vernichtet"
    )


def test_reset_bricht_ab_wenn_die_sicherung_scheitert(paths, dienste, monkeypatch):
    """Scheitert die Sicherung, bleibt das Log unangetastet.

    Eine Sicherung, die im Fehlerfall nur warnt und trotzdem loescht, erfuellt
    Z1 nicht: genau dann waeren die Daten weg.
    """
    mech_service, event_manager = dienste

    def _scheitert(*_a, **_kw):
        raise OSError("kein Platz auf dem Geraet")

    monkeypatch.setattr(shutil, "copy2", _scheitert)
    monkeypatch.setattr(shutil, "copytree", _scheitert)

    ergebnis = reset_donations(
        mech_service, event_manager, source="test", paths=paths
    )

    inhalt = paths.event_log.read_text(encoding="utf-8")
    for zeile in EREIGNISSE:
        assert zeile in inhalt, (
            "Die Sicherung scheiterte, trotzdem wurde das Spendenbuch geleert"
        )
    assert ergebnis.success is False


def test_zweiter_reset_ueberschreibt_die_erste_sicherung_nicht(paths, dienste):
    """Zwei Resets ergeben zwei wiederherstellbare Staende, nicht einen.

    Eine rollierende Sicherung (eine einzige ``.bak``) genuegt hier nicht: der
    zweite Reset wuerde die Sicherung des ersten ueberschreiben, und ein
    versehentlicher Doppelklick vernichtete alles.
    """
    mech_service, event_manager = dienste

    reset_donations(mech_service, event_manager, source="test", paths=paths)
    erste = set(_wiederherstellbare_kopien(paths))
    assert erste, "erste Sicherung fehlt bereits"

    # Neuer Inhalt, damit sich der zweite Stand vom ersten unterscheidet.
    paths.event_log.write_text(
        "\n".join(EREIGNISSE) + '\n{"seq": 4, "type": "DonationAdded"}\n',
        encoding="utf-8",
    )
    reset_donations(mech_service, event_manager, source="test", paths=paths)
    zweite = set(_wiederherstellbare_kopien(paths))

    assert erste <= zweite, "Die erste Sicherung wurde ueberschrieben"
    assert len(zweite) > len(erste), "Der zweite Reset hat nichts gesichert"
