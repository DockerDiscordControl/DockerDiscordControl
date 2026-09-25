# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Locales Consistency Tests                       #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Tests ensuring all locale JSON files are consistent.

Checks:
    1. Every locale file is valid JSON, all keys/values are strings (or dicts).
    2. ``en.json`` is the source-of-truth: every key in another locale must
       exist in en.json.
    3. ``meta.json`` covers every locale stem (excluding ``meta`` and
       hidden ``_*`` files) and every entry has ``name`` + ``native``.
    4. Every key the panel reads exists, and is not empty, in en.json
       and de.json - the subjects read out of the markup, not listed.
    5. The :class:`I18nService` lazy-loading and helper behaviour.
    6. Locale files are non-empty (>= 50 keys).
    7. No duplicate keys inside any locale JSON file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest


# ---------------------------------------------------------------------------
# Module-level constants & helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOCALES_DIR = PROJECT_ROOT / "locales"
META_FILE = LOCALES_DIR / "meta.json"

MIN_KEYS_PER_LOCALE = 50

# THE KEYS THE PANEL ACTUALLY READS, found by reading it.
#
# This was a tuple of three names, typed out in 2025 and called "Bundle 1".
# On 2026-09-24 one of them - web.logs.debug_level_restart_hint - was removed
# on purpose: the debug switch stopped needing a restart, so the hint stopped
# being true. These four cases went red that day and nobody saw it, because
# tests/unit/i18n is not one of the groups the working routine names. A list
# goes stale exactly like the thing it guards; the markup does not.
def _keys_the_panel_reads():
    """Every catalogue key a template or a script asks for."""
    import re

    asked = set()
    for folder, suffix in ((PROJECT_ROOT / "app" / "templates", "*.html"),
                           (PROJECT_ROOT / "app" / "static" / "js", "*.js")):
        for path in sorted(folder.rglob(suffix)):
            text = path.read_text(encoding="utf-8")
            for pattern in (r"_t\(\s*'([^']+)'", r'_t\(\s*"([^"]+)"',
                            r"\bt\(\s*'([^']+)'", r'\bt\(\s*"([^"]+)"'):
                asked |= set(re.findall(pattern, text))
    # Only the panel's own namespace: the bot's texts are English sentences
    # used as their own keys, and they are not read from a template.
    return sorted(key for key in asked if key.startswith("web."))


def _all_locale_files() -> List[Path]:
    """Return every ``*.json`` file inside the locales directory."""
    return sorted(p for p in LOCALES_DIR.glob("*.json") if p.is_file())


def _content_locale_files() -> List[Path]:
    """Locale files that hold translations (excludes meta + hidden _*.json)."""
    return [
        p
        for p in _all_locale_files()
        if p.stem != "meta" and not p.stem.startswith("_")
    ]


def _load_keys_preserving_duplicates(path: Path) -> List[str]:
    """Load JSON capturing duplicate keys via ``object_pairs_hook``."""

    def _hook(pairs):  # type: ignore[no-untyped-def]
        return [k for k, _ in pairs]

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f, object_pairs_hook=_hook)


def _load_locale(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Sanity-check on the discovery itself
# ---------------------------------------------------------------------------


def test_locales_directory_exists():
    assert LOCALES_DIR.is_dir(), f"Missing locales dir: {LOCALES_DIR}"


def test_locale_files_discovered():
    files = _all_locale_files()
    # Expect 41 files (40 content + meta.json) per project context.
    assert len(files) >= 10, f"Suspiciously few locale files: {len(files)}"
    assert META_FILE.exists(), "meta.json must exist"


# ---------------------------------------------------------------------------
# 1. Every locale file is valid JSON & values are strings (or dicts)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("locale_path", _all_locale_files(), ids=lambda p: p.name)
def test_locale_file_is_valid_json(locale_path: Path):
    """Each locale file parses as JSON without crashing."""
    data = _load_locale(locale_path)
    assert isinstance(data, dict), f"{locale_path.name} root must be an object"


@pytest.mark.parametrize(
    "locale_path", _content_locale_files(), ids=lambda p: p.name
)
def test_locale_keys_and_values_are_strings(locale_path: Path):
    """All keys must be strings; values must be strings or nested dicts."""
    data = _load_locale(locale_path)
    bad: List[Tuple[str, str]] = []
    for k, v in data.items():
        if not isinstance(k, str):
            bad.append((repr(k), f"key type {type(k).__name__}"))
        elif not isinstance(v, (str, dict)):
            bad.append((k, f"value type {type(v).__name__}"))
    assert not bad, f"{locale_path.name} has non-string entries: {bad[:5]}"


# ---------------------------------------------------------------------------
# 2. en.json is the source-of-truth (other locales must be subsets)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def en_keys() -> set:
    en = _load_locale(LOCALES_DIR / "en.json")
    return set(en.keys())


@pytest.mark.parametrize(
    "locale_path",
    [p for p in _content_locale_files() if p.stem != "en"],
    ids=lambda p: p.name,
)
def test_locale_keys_are_subset_of_english(locale_path: Path, en_keys: set):
    """Every key in any non-en locale must also exist in en.json."""
    data = _load_locale(locale_path)
    other_keys = set(data.keys())
    extra = other_keys - en_keys
    assert not extra, (
        f"{locale_path.name} has keys missing from en.json: "
        f"{sorted(list(extra))[:5]}"
    )


# ---------------------------------------------------------------------------
# 3. meta.json consistency
# ---------------------------------------------------------------------------


def test_meta_file_covers_every_content_locale():
    """Each *.json content locale must have an entry in meta.json."""
    meta = _load_locale(META_FILE)
    expected_codes = {p.stem for p in _content_locale_files()}
    missing = expected_codes - set(meta.keys())
    assert not missing, f"meta.json missing entries for: {sorted(missing)}"


def test_meta_entries_have_required_fields():
    """Every meta entry must have at least 'name' and 'native'."""
    meta = _load_locale(META_FILE)
    bad: List[Tuple[str, List[str]]] = []
    for code, info in meta.items():
        if not isinstance(info, dict):
            bad.append((code, [f"not a dict: {type(info).__name__}"]))
            continue
        missing_fields = [f for f in ("name", "native") if f not in info]
        if missing_fields:
            bad.append((code, missing_fields))
    assert not bad, f"meta.json entries missing required fields: {bad}"


def test_meta_entries_only_reference_real_locale_files():
    """Every meta-entry code must have a matching <code>.json file."""
    meta = _load_locale(META_FILE)
    available = {p.stem for p in _content_locale_files()}
    orphans = set(meta.keys()) - available
    assert not orphans, f"meta.json references missing locales: {sorted(orphans)}"


# ---------------------------------------------------------------------------
# 4. Bundle 1 keys present and translated
# ---------------------------------------------------------------------------


def test_every_key_the_panel_reads_exists_in_english():
    """A key the markup asks for and the catalogue does not have renders as
    the key itself - "web.logs.debug_level_label" in the middle of the page."""
    en = _load_locale(LOCALES_DIR / "en.json")
    missing = [key for key in _keys_the_panel_reads() if key not in en]

    assert missing == [], f"en.json is missing keys the panel reads: {missing}"


def test_every_key_the_panel_reads_exists_in_german():
    """German is the one language the operator reads, and the only other one
    this project can check by eye."""
    de = _load_locale(LOCALES_DIR / "de.json")
    missing = [key for key in _keys_the_panel_reads() if key not in de]

    assert missing == [], f"de.json is missing keys the panel reads: {missing}"


def test_no_key_the_panel_reads_is_empty():
    """An empty value is a key that exists and says nothing, which on the
    page is a blank where a label belongs."""
    for name in ("en.json", "de.json"):
        catalogue = _load_locale(LOCALES_DIR / name)
        blank = [key for key in _keys_the_panel_reads()
                 if key in catalogue and not str(catalogue[key]).strip()]

        assert blank == [], f"{name} has empty values for {blank}"


def test_the_panel_was_really_read():
    """The counter-check: all three cases above pass on an empty list."""
    keys = _keys_the_panel_reads()

    assert len(keys) > 300, len(keys)
    assert "web.logs.debug_level_label" in keys, "the debug section was not read"
    assert "web.two_factor.title" in keys, "the second factor was not read"


# ---------------------------------------------------------------------------
# 5. I18nService lazy-loading behaviour
# ---------------------------------------------------------------------------


@pytest.fixture
def i18n_service():
    """Fresh I18nService instance per test (avoids singleton state bleed)."""
    from services.web.i18n_service import I18nService

    return I18nService()


def test_translate_unknown_key_falls_back_to_key_itself(i18n_service):
    out = i18n_service.translate("nonexistent.key", lang="en")
    assert out == "nonexistent.key"


def test_translate_unknown_lang_falls_back_to_english(i18n_service):
    # 'app.title' may or may not be in en.json — but request must not crash
    # and must return *something* (string).
    out = i18n_service.translate("app.title", lang="zz_invalid", name="X")
    assert isinstance(out, str)
    assert out != ""


def test_translate_unknown_lang_unknown_key_returns_key(i18n_service):
    out = i18n_service.translate("definitely.not.a.real.key", lang="zz_invalid")
    assert out == "definitely.not.a.real.key"


def test_translate_kwargs_substitution_does_not_crash_on_missing_placeholder(i18n_service):
    # Should not raise even if the value has no {name} placeholder.
    out = i18n_service.translate("nonexistent.key.kwargs", lang="en", name="X")
    assert isinstance(out, str)


def test_get_available_languages_returns_list_of_dicts(i18n_service):
    langs = i18n_service.get_available_languages()
    assert isinstance(langs, list)
    assert len(langs) >= 10
    for entry in langs:
        assert isinstance(entry, dict)
        for field in ("code", "name", "native", "rtl"):
            assert field in entry, f"missing field {field!r} in {entry}"
        assert isinstance(entry["rtl"], bool)


def test_is_rtl_arabic_is_true(i18n_service):
    assert i18n_service.is_rtl("ar") is True


def test_is_rtl_english_is_false(i18n_service):
    assert i18n_service.is_rtl("en") is False


def test_is_rtl_unknown_language_is_false(i18n_service):
    # Unknown languages should default to LTR.
    assert i18n_service.is_rtl("zz_unknown") is False


def test_get_js_translations_strips_js_prefix(i18n_service):
    js = i18n_service.get_js_translations("en")
    assert isinstance(js, dict)
    # Keys must not start with 'js.' anymore
    for k in js.keys():
        assert not k.startswith("js."), f"prefix not stripped from {k!r}"
    # And must contain at least one key (en.json has many js.* keys).
    assert len(js) > 0, "expected en.json to expose js.* translations"


def test_get_js_translations_fallback_lang_does_not_crash(i18n_service):
    # Even unknown lang must succeed (falls back to en).
    js = i18n_service.get_js_translations("zz_invalid")
    assert isinstance(js, dict)


# ---------------------------------------------------------------------------
# 6. Locale files are non-empty
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "locale_path", _content_locale_files(), ids=lambda p: p.name
)
def test_locale_file_has_minimum_keys(locale_path: Path):
    data = _load_locale(locale_path)
    assert len(data) >= MIN_KEYS_PER_LOCALE, (
        f"{locale_path.name} only has {len(data)} keys "
        f"(min: {MIN_KEYS_PER_LOCALE})"
    )


# ---------------------------------------------------------------------------
# 7. No duplicate keys inside a locale file
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("locale_path", _all_locale_files(), ids=lambda p: p.name)
def test_locale_file_has_no_duplicate_keys(locale_path: Path):
    """A duplicate key in JSON silently overrides the prior value — disallow it."""
    keys = _load_keys_preserving_duplicates(locale_path)
    seen: Dict[str, int] = {}
    duplicates: List[str] = []
    for k in keys:
        seen[k] = seen.get(k, 0) + 1
        if seen[k] == 2:
            duplicates.append(k)
    assert not duplicates, (
        f"{locale_path.name} has duplicate keys: {duplicates[:5]}"
    )
