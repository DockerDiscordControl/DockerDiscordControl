#!/usr/bin/env python3
"""Create placeholder locale files for all languages defined in meta.json.

Each file starts as a copy of en.json. The community can then contribute
actual translations for each language.

Usage: cd /Volumes/appdata/dockerdiscordcontrol && python scripts/create_placeholder_locales.py
"""
import json
import os
from pathlib import Path

LOCALES_DIR = Path(__file__).resolve().parent.parent / 'locales'


def main():
    en_path = LOCALES_DIR / 'en.json'
    meta_path = LOCALES_DIR / 'meta.json'

    with open(en_path, 'r', encoding='utf-8') as f:
        en_data = json.load(f)

    with open(meta_path, 'r', encoding='utf-8') as f:
        meta = json.load(f)

    created = 0
    skipped = 0

    for lang_code in sorted(meta.keys()):
        lang_file = LOCALES_DIR / f'{lang_code}.json'
        if lang_file.exists():
            # Don't overwrite existing translations
            skipped += 1
            continue

        # Create placeholder with English values
        with open(lang_file, 'w', encoding='utf-8') as f:
            json.dump(en_data, f, ensure_ascii=False, indent=2, sort_keys=True)

        name = meta[lang_code].get('native', lang_code)
        print(f"Created: {lang_code}.json ({name})")
        created += 1

    print(f"\nDone! Created {created} files, skipped {skipped} existing.")
    print(f"Total locale files: {len(list(LOCALES_DIR.glob('*.json'))) - 1}")  # -1 for meta.json


if __name__ == '__main__':
    main()
