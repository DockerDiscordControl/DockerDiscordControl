# -*- coding: utf-8 -*-
"""Das Konfigurationsverzeichnis hat EINE Quelle: ``utils/config_paths.py``.

KEIN ``@deckt``-Marker: Das waere eine neue Zusicherung, und die sind die
Entscheidung des Betreibers.

WARUM: ``DDC_CONFIG_DIR`` ist fuer Nutzer dokumentiert. Jede Stelle, die
``<projekt>/config`` selbst herleitet, spaltet die Konfiguration, sobald die
Variable gesetzt ist - und im Testlauf (tests/conftest.py setzt sie) zielt sie
aufs ECHTE config/ (SPEC.md Z2). Sechs Stellen hatten die Regel je selbst
abgeschrieben, in drei Fassungen (mit und ohne ``strip()``, eine mit festem
``/app/config`` als Vorgabe).

EINE SPERRKLINKE, KEIN VERBOT AUF EINEN SCHLAG: Die Umstellung laeuft nach
Fachbereichen, je ein Befund mit eigenem Verhaltenstest. Bis dahin fuehrt
``NOCH_OFFEN`` die heute abweichenden Stellen je Datei. Der Vertrag schlaegt an,
wenn eine NEUE Herleitung dazukommt - UND wenn eine umgestellte noch auf der
Liste steht. Die Liste kann also nur schrumpfen, und sie luegt nicht.

DIE GRENZE DES SCANNERS, ausdruecklich: Er erkennt die Formen, die heute im
Code vorkommen (``x / "config"``, ``"/app/config"``, ``Path("config")``,
``join(..., "config")``, relative ``"config/..."``, eigene Lesungen von
``DDC_CONFIG_DIR``). Eine Herleitung in neuer Form (etwa ueber einen
zusammengesetzten Text) saehe er nicht. Kommentarzeilen ueberspringt er.
Die erste Fassung uebersah die relativen ``"config/..."``-Pfade - drei Stellen,
die erst eine zweite, breitere Suche fand.
"""

import re
from pathlib import Path

import pytest

from utils import config_paths

PROJEKT = Path(__file__).resolve().parents[2]
VERZEICHNISSE = ("cogs", "services", "app", "utils")
QUELLE = "utils/config_paths.py"

MUSTER = (
    re.compile(r"""/\s*['"]config['"]"""),               # x / "config"
    re.compile(r"""['"]/app/config"""),                   # "/app/config..."
    re.compile(r"""Path\(\s*['"]config['"]\s*\)"""),      # Path("config")
    re.compile(r"""join\([^)]*['"]config['"]"""),         # os.path.join(..., "config"
    re.compile(r"""['"]config/"""),                       # "config/x.json"
    re.compile(r"""DDC_CONFIG_DIR['"]"""),                # eigene Kopie der Regel
)

# Datei -> Zahl der heute noch abweichenden Zeilen. NUR SCHRUMPFEN LASSEN.
NOCH_OFFEN = {
    "app/bot/token.py": 1,
    "app/utils/shared_data.py": 2,
    "app/utils/web_helpers.py": 1,
    "app/web/config.py": 3,
    "services/admin/admin_service.py": 3,
    "services/automation/auto_action_config_service.py": 1,
    "services/automation/auto_action_state_service.py": 1,
    "services/config/config_service.py": 2,
    "services/docker_service/docker_utils.py": 2,
    "services/docker_service/server_order.py": 2,
    "services/donation/notification_service.py": 1,
    "services/infrastructure/container_status_service.py": 1,
    "services/infrastructure/game_query_support_service.py": 2,
    "services/infrastructure/spam_protection_service.py": 2,
    "services/infrastructure/update_notifier.py": 1,
    "services/mech/mech_evolutions.py": 2,
    "services/mech/mech_reset_service.py": 2,
    "services/mech/mech_state_manager.py": 1,
    "services/mech/mech_story_service.py": 1,
    "services/mech/progress_paths.py": 1,
    "services/mech/progress_service.py": 2,
    "services/mech/speed_levels.py": 1,
    "services/scheduling/runtime.py": 1,
    "services/translation/translation_config_service.py": 1,
    "services/web/donation_service.py": 1,
    "utils/token_security.py": 4,
}


def _trifft(zeile: str) -> bool:
    return not zeile.lstrip().startswith("#") and any(m.search(zeile) for m in MUSTER)


def _gefunden() -> dict:
    ergebnis = {}
    for verzeichnis in VERZEICHNISSE:
        for pfad in sorted((PROJEKT / verzeichnis).rglob("*.py")):
            name = pfad.relative_to(PROJEKT).as_posix()
            if name == QUELLE:
                continue
            anzahl = sum(1 for z in pfad.read_text(encoding="utf-8", errors="replace").splitlines()
                         if _trifft(z))
            if anzahl:
                ergebnis[name] = anzahl
    return ergebnis


@pytest.mark.parametrize("zeile", [
    'base = Path(__file__).parents[2] / "config"',
    "d = base_dir / 'config' / 'admins.json'",
    'NOTIFICATION_DIR = "/app/config"',
    'CONFIG_DIR = Path("config")',
    "p = os.path.join(root, 'config', 'x.json')",
    "p = Path('config/containers')",
    "env = os.environ.get('DDC_CONFIG_DIR', '')",
])
def test_der_scanner_erkennt_jede_bekannte_form(zeile):
    """Sicherung gegen ein stumpfes Werkzeug - je Form ein Beispiel."""
    assert _trifft(zeile), zeile


@pytest.mark.parametrize("zeile", [
    'containers_dir = get_config_dir() / "containers"',
    "# base_dir / 'config' in einem Kommentar",
    'config = load_config()',
])
def test_der_scanner_schlaegt_nicht_blind_an(zeile):
    assert not _trifft(zeile), zeile


def test_keine_neue_herleitung_und_die_liste_luegt_nicht():
    gefunden = _gefunden()
    neu = {k: v for k, v in gefunden.items() if v > NOCH_OFFEN.get(k, 0)}
    erledigt = {k: (v, gefunden.get(k, 0)) for k, v in NOCH_OFFEN.items() if gefunden.get(k, 0) < v}
    assert not neu, (
        "Neue eigene Herleitung des Konfigurationsverzeichnisses - bitte "
        f"utils.config_paths.get_config_dir() benutzen: {neu}"
    )
    assert not erledigt, (
        "Diese Dateien leiten weniger Pfade selbst her als NOCH_OFFEN sagt - "
        f"die Liste nachziehen (Soll, Ist): {erledigt}"
    )


def test_die_quelle_folgt_der_variablen(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    assert config_paths.get_config_dir() == tmp_path


def test_die_quelle_liest_die_variable_bei_jedem_aufruf(tmp_path, monkeypatch):
    """Nicht beim Import: Ein Dienst, der NACH einer Aenderung gebaut wird,
    muss sie sehen."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path / "a"))
    config_paths.get_config_dir()
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path / "b"))
    assert config_paths.get_config_dir() == tmp_path / "b"


@pytest.mark.parametrize("wert", ["", "   "])
def test_leer_heisst_vorgabe(monkeypatch, wert):
    """Leer oder nur Leerzeichen: die Vorgabe - wie bei fuenf der sechs alten
    Kopien (container_status_service nahm eine leere Variable woertlich)."""
    monkeypatch.setenv("DDC_CONFIG_DIR", wert)
    assert config_paths.get_config_dir() == PROJEKT / "config"


def test_ohne_variable_gilt_projekt_config(monkeypatch):
    """Im Container ist das /app/config - dasselbe wie jede alte Herleitung."""
    monkeypatch.delenv("DDC_CONFIG_DIR", raising=False)
    assert config_paths.get_config_dir() == PROJEKT / "config"
