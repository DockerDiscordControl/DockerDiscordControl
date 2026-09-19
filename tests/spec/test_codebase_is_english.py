# -*- coding: utf-8 -*-
"""The repository is English - code, comments, docstrings, tests and docs.

DDC is international open-source software (operator decision, 2026-09-19).
German text had crept in: comments and docstrings, hard-wired German texts
shown to users, German catalog source strings, the tests/spec suite and the
quality-programme documents.

A RATCHET, NOT A BAN IN ONE STEP: the translation runs area by area, one
change per area. Until it is done, ``STILL_GERMAN`` lists the German lines per
file. The contract fails when a file gets MORE German lines than listed - and
when a file has FEWER, so the list can only shrink and never lies.

WHAT IS SCANNED: every text file below ``ROOTS`` plus ``ROOT_FILES``. Excluded
are language DATA (``locales/``, the shipped German story in
``services/mech/defaults/``) and three private documents that are not part of
the repository at all - each exclusion is checked against ``.gitignore``, so an
exclusion can never silently hide a published file.

THE LIMIT OF THE DETECTOR, stated plainly: it is a heuristic. A line counts
as German when it holds at least two words from a German signal vocabulary
(ALL-CAPS words such as "MIT" or "API" do not count), or one such word plus an
umlaut. A German line made only of rarer words slips through. Measured on the
English documentation and on the English code of ``main``, it raised no false
alarm apart from "MIT License" - which is why all-caps words are ignored.
"""

import re
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
ROOTS = ("app", "cogs", "services", "utils", "scripts", "tools", "tests", "docs", ".github")
ROOT_FILES = ("README.md", "SPEC.md", "AUDIT.md", "Dockerfile", "docker-compose.yml",
              "bot.py", "run.py", "wsgi.py")
SUFFIXES = {".py", ".sh", ".js", ".html", ".css", ".yml", ".yaml", ".toml", ".ini", ".cfg",
            ".md", ".txt"}
DATA_PREFIXES = ("locales/", "services/mech/defaults/")
# Private documents, gitignored - checked below against .gitignore.
PRIVATE = ("AUDIT_2026-09.md", "ROADMAP_2026-09_perf_mech.md", "docs/DMC_PROJECT_PLAN.md")
# This file itself: its German lines are the detector's test examples.
SELF = "tests/spec/test_codebase_is_english.py"

SIGNAL = frozenset("""
der das und nicht ist wird wurde werden ein eine einen einem einer eines auch nur
noch schon weil wenn dass ueber fuer über für mit von zum zur bei nach vor aus hier
dort jetzt heute vorher bisher sonst bleibt steht liegt gibt keine kein keinen ohne
diese dieser dieses jede jeder jedes wie wo warum soll muss kann darf sind waren
hatte haben oder aber denn damit dabei seit sich wir ihr gegen unter zwischen weiter
selbst beim vom ins im dem siehe gemessen entschieden befund befunde waechter wächter
abgrenzung datei dateien verzeichnis knopf knoepfe knöpfe dienst vorgabe vorgaben
regler betreiber zusicherung eigene eigenen eigener eigenes nie immer genau ohnehin
also zuerst danach dann erst sehr ganz alle alles etwas nichts heisst heißt zeigt
gilt fehlt fehlen stand lag lagen worden sollte muesste müsste waere wäre haette
hätte koennte könnte
""".split())
UMLAUT = re.compile(r"[äöüÄÖÜß]")
WORD = re.compile(r"[A-Za-zäöüÄÖÜß]+")

# file -> number of German lines still in it. ONLY EVER SHRINK THIS.
STILL_GERMAN = {
    "AUDIT.md": 75,
    "SPEC.md": 326,
    "cogs/enhanced_info_modal_simple.py": 9,
    "docs/archive/proposals/FEATURE_IDEA_WARNING_SYSTEM.md": 10,
    "docs/archive/proposals/FEATURE_PLAN_AUTO_ACTIONS.md": 49,
    "docs/archive/proposals/HOT_RELOAD_PLAN.md": 26,
    "docs/quality/ABSCHNITTE.txt": 5,
    "docs/quality/PRUEFPLAN.txt": 3,
    "docs/quality/STUFE0_BESTANDSAUFNAHME.md": 396,
    "docs/quality/STUFE3_TESTS_DIE_NICHT_FEHLSCHLAGEN.md": 195,
    "docs/quality/STUFE4_DURCHSICHT.md": 164,
    "services/infrastructure/docker_connectivity_service.py": 8,
    "services/infrastructure/spam_protection_service.py": 6,
    "tests/GROUPS.txt": 11,
    "tests/spec/__init__.py": 3,
    "tests/spec/test_angeforderte_abklingschluessel_existieren.py": 60,
    "tests/spec/test_app_factory_verdrahtung.py": 60,
    "tests/spec/test_aufgabenloeschknopf_weist_uebersetzt_ab.py": 15,
    "tests/spec/test_befehle_bremsen_ueber_den_dienst.py": 56,
    "tests/spec/test_container_verschwindet_nicht_halb.py": 98,
    "tests/spec/test_einstellungen_wirken_ueberall.py": 81,
    "tests/spec/test_gespeicherte_konfiguration_ergaenzt_vorgaben.py": 45,
    "tests/spec/test_import_ohne_nebenwirkung.py": 65,
    "tests/spec/test_infoknoepfe_bremsen_ueber_den_dienst.py": 69,
    "tests/spec/test_keine_nackten_except.py": 54,
    "tests/spec/test_keine_zeichengleichen_zwillinge.py": 55,
    "tests/spec/test_knoepfe_bremsen_nach_knopfreglern.py": 73,
    "tests/spec/test_konfigverzeichnis_admins.py": 14,
    "tests/spec/test_konfigverzeichnis_aktive_container.py": 12,
    "tests/spec/test_konfigverzeichnis_auto_aktionen.py": 18,
    "tests/spec/test_konfigverzeichnis_container_und_kanaele.py": 25,
    "tests/spec/test_konfigverzeichnis_containerinfos_speichern.py": 17,
    "tests/spec/test_konfigverzeichnis_eine_quelle.py": 34,
    "tests/spec/test_konfigverzeichnis_einzelbesitzer.py": 27,
    "tests/spec/test_konfigverzeichnis_mech.py": 26,
    "tests/spec/test_konfigverzeichnis_spamschutz.py": 14,
    "tests/spec/test_konfigverzeichnis_spendenmeldung.py": 16,
    "tests/spec/test_konfigverzeichnis_token.py": 20,
    "tests/spec/test_lesefehler_ist_keine_neuinstallation.py": 133,
    "tests/spec/test_livelogansicht_bremst_ueber_den_dienst.py": 69,
    "tests/spec/test_mech_geschichten_mitgeliefert.py": 24,
    "tests/spec/test_mech_geschwindigkeit_mitgeliefert.py": 13,
    "tests/spec/test_mech_verfall_mitgeliefert.py": 17,
    "tests/spec/test_mechdetails_hat_einen_regler.py": 45,
    "tests/spec/test_mechknoepfe_bremsen_ueber_den_dienst.py": 72,
    "tests/spec/test_mechknoepfe_fragen_ihren_eigenen_regler.py": 42,
    "tests/spec/test_migration_verschluckt_nicht.py": 59,
    "tests/spec/test_migrationshelfer_ist_erreichbar.py": 77,
    "tests/spec/test_minutengrenzen_bremsen_wirklich.py": 84,
    "tests/spec/test_protokollknopf_bremst_ueber_den_dienst.py": 69,
    "tests/spec/test_r2_spec_coverage.py": 30,
    "tests/spec/test_serverstatus_weist_privat_ab.py": 22,
    "tests/spec/test_spendenmeldung_ueberlebt_schreibfehler.py": 94,
    "tests/spec/test_stufe4_zuschnitt.py": 41,
    "tests/spec/test_token_anzeige_verschweigt_keine_klartextkopie.py": 78,
    "tests/spec/test_umschaltknopf_hat_wieder_eine_abklingzeit.py": 70,
    "tests/spec/test_umschaltknopf_regler_im_panel.py": 24,
    "tests/spec/test_ungebremste_mechknoepfe_bremsen.py": 71,
    "tests/spec/test_vier_knoepfe_bremsen_ueber_den_dienst.py": 90,
    "tests/spec/test_vorgabewerte_widersprechen_sich_nicht.py": 60,
    "tests/spec/test_z10_ci_test_gate.py": 111,
    "tests/spec/test_z10_gruppenliste.py": 36,
    "tests/spec/test_z1_donation_ledger_backup.py": 36,
    "tests/spec/test_z2_config_isolation.py": 25,
    "tests/spec/test_z3_z8_donation_broadcast.py": 70,
    "tests/spec/test_z4_donation_idempotency.py": 65,
    "tests/spec/test_z5_aufgaben_loeschweg.py": 63,
    "tests/spec/test_z5_channel_permission.py": 51,
    "tests/spec/test_z6_docker_actions.py": 51,
    "tests/spec/test_z7_atomic_writes.py": 49,
    "tests/spec/test_z7_container_config_write.py": 47,
    "tests/spec/test_z7_mech_state_write.py": 59,
    "tests/spec/test_z7_member_count_write.py": 57,
    "tests/spec/test_z7_server_order_write.py": 61,
    "tests/spec/test_zustandsdateien_ueberleben_schreibfehler.py": 66,
    "tests/unit/audit_2026_09/test_pkg_c2_config.py": 4,
    "tests/unit/cogs/test_autocomplete_handlers.py": 1,
    "tests/unit/extended/test_docker_infra_gaps.py": 5,
    "tests/unit/utils/test_crypto_cache.py": 6,
    "tests/unit/utils/test_utils_completion.py": 4,
}


def is_german(line: str) -> bool:
    words = [w.lower() for w in WORD.findall(line) if not w.isupper()]
    hits = sum(1 for w in words if w in SIGNAL)
    return hits >= 2 or (bool(UMLAUT.search(line)) and hits >= 1)


def _files():
    candidates = [PROJECT / name for name in ROOT_FILES]
    for root in ROOTS:
        candidates.extend(p for p in (PROJECT / root).rglob("*") if p.is_file())
    for path in sorted(set(candidates)):
        if not path.is_file():
            continue
        rel = path.relative_to(PROJECT).as_posix()
        if rel.startswith(DATA_PREFIXES) or rel in PRIVATE or rel == SELF or "__pycache__" in rel:
            continue
        if path.suffix not in SUFFIXES and path.name != "Dockerfile":
            continue
        yield rel, path


def german_lines() -> dict:
    found = {}
    for rel, path in _files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        count = sum(1 for line in text.splitlines() if is_german(line))
        if count:
            found[rel] = count
    return found


@pytest.mark.parametrize("line", [
    "# Nicht self.custom_id (read_story_<stufe>) - siehe EpilogueButton.",
    "Der Knopf fragt den Dienst nicht.",
    '"""Cache für statische Container-Daten die sich nie ändern."""',
    'title = "🚨 Container-Überwachung nicht verfügbar"',
])
def test_the_detector_finds_german(line):
    """Guard against a blunt tool - one example per kind of hit."""
    assert is_german(line), line


@pytest.mark.parametrize("line", [
    "# The button asks the service for its cooldown before deferring.",
    "Live player counts are powered by opengsq (MIT License).",
    "die_roll = random.randint(1, 6)  # was the hat on the man?",
    'return get_config_dir() / "mech" / relative',
])
def test_the_detector_does_not_flag_english(line):
    assert not is_german(line), line


def test_private_exclusions_are_really_gitignored():
    """An exclusion must never hide a published file."""
    ignore = (PROJECT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for name in PRIVATE:
        assert name in ignore, f"{name} is excluded from the scan but not listed in .gitignore"


def test_no_new_german_and_the_list_does_not_lie():
    found = german_lines()
    new = {k: v for k, v in found.items() if v > STILL_GERMAN.get(k, 0)}
    done = {k: (v, found.get(k, 0)) for k, v in STILL_GERMAN.items() if found.get(k, 0) < v}
    assert not new, f"German text added (write English - DDC is international): {new}"
    assert not done, f"Fewer German lines than STILL_GERMAN says - shrink the list (listed, found): {done}"
