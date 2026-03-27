#!/usr/bin/env python3
"""Check translation coverage across all locale files.

Usage: cd /Volumes/appdata/dockerdiscordcontrol && python scripts/check_translations.py
"""
import json
import re
import sys
from pathlib import Path

LOCALES_DIR = Path(__file__).resolve().parent.parent / 'locales'
PLACEHOLDER_RE = re.compile(r'\{[^}]+\}')


def main():
    # Load English as reference
    en_path = LOCALES_DIR / 'en.json'
    if not en_path.exists():
        print("ERROR: en.json not found")
        sys.exit(1)

    with open(en_path, 'r', encoding='utf-8') as f:
        en = json.load(f)

    en_keys = set(en.keys())
    print(f"Reference: en.json ({len(en_keys)} keys)\n")

    # Load meta
    meta_path = LOCALES_DIR / 'meta.json'
    meta = {}
    if meta_path.exists():
        with open(meta_path, 'r', encoding='utf-8') as f:
            meta = json.load(f)

    issues_total = 0
    langs_checked = 0
    langs_missing_file = []

    # Check each language in meta
    for lang_code in sorted(meta.keys()):
        if lang_code == 'en':
            continue

        lang_file = LOCALES_DIR / f'{lang_code}.json'
        if not lang_file.exists():
            langs_missing_file.append(lang_code)
            continue

        langs_checked += 1
        with open(lang_file, 'r', encoding='utf-8') as f:
            try:
                lang_data = json.load(f)
            except json.JSONDecodeError as e:
                print(f"  {lang_code}: INVALID JSON - {e}")
                issues_total += 1
                continue

        lang_keys = set(lang_data.keys())
        missing = en_keys - lang_keys
        extra = lang_keys - en_keys
        untranslated = 0
        placeholder_issues = []

        for key in en_keys & lang_keys:
            # Check if value is same as English (possibly untranslated)
            if lang_data[key] == en[key] and key.startswith(('web.', 'js.')):
                untranslated += 1

            # Check placeholders are preserved
            en_placeholders = set(PLACEHOLDER_RE.findall(en[key]))
            lang_placeholders = set(PLACEHOLDER_RE.findall(lang_data[key]))
            if en_placeholders != lang_placeholders:
                placeholder_issues.append(key)

        issues = len(missing) + len(extra) + len(placeholder_issues)
        issues_total += issues

        status = "OK" if issues == 0 else "ISSUES"
        name = meta.get(lang_code, {}).get('native', lang_code)
        print(f"  {lang_code:6s} ({name:20s}): {len(lang_data):4d} keys | "
              f"missing: {len(missing):3d} | extra: {len(extra):3d} | "
              f"untranslated: {untranslated:3d} | placeholder issues: {len(placeholder_issues):2d} [{status}]")

        if missing and len(missing) <= 5:
            for k in sorted(missing)[:5]:
                print(f"         MISSING: {k}")
        if placeholder_issues and len(placeholder_issues) <= 5:
            for k in placeholder_issues[:5]:
                print(f"         PLACEHOLDER: {k}")

    print(f"\n--- Summary ---")
    print(f"Languages checked: {langs_checked}")
    if langs_missing_file:
        print(f"Missing files ({len(langs_missing_file)}): {', '.join(langs_missing_file)}")
    print(f"Total issues: {issues_total}")

    return 0 if issues_total == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
