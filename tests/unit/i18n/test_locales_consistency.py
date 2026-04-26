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
    4. The Bundle 1 i18n keys exist in en.json and de.json with the
       expected substrings.
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

# Bundle 1 keys to verify
BUNDLE1_KEYS = (
    "web.logs.debug_level_restart_hint",
    "web.logs.debug_level_help",
    "web.logs.debug_level_label",
)


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


@pytest.mark.parametrize("key", BUNDLE1_KEYS)
def test_en_has_bundle1_key(key: str):
    en = _load_locale(LOCALES_DIR / "en.json")
    assert key in en, f"en.json missing Bundle 1 key: {key}"
    assert en[key].strip(), f"en.json has empty value for {key}"


@pytest.mark.parametrize("key", BUNDLE1_KEYS)
def test_de_has_bundle1_key(key: str):
    de = _load_locale(LOCALES_DIR / "de.json")
    assert key in de, f"de.json missing Bundle 1 key: {key}"
    assert de[key].strip(), f"de.json has empty value for {key}"


def test_de_restart_hint_translation_contains_german_phrase():
    de = _load_locale(LOCALES_DIR / "de.json")
    value = de["web.logs.debug_level_restart_hint"]
    assert "Container-Neustart" in value, (
        f"de.json restart_hint should mention 'Container-Neustart', got: {value!r}"
    )


def test_en_restart_hint_translation_contains_english_phrase():
    en = _load_locale(LOCALES_DIR / "en.json")
    value = en["web.logs.debug_level_restart_hint"]
    assert "container restart" in value.lower(), (
        f"en.json restart_hint should mention 'container restart', got: {value!r}"
    )


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
