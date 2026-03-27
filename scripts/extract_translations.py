#!/usr/bin/env python3
"""Extract translations from TranslationManager inline dict to JSON files.

Usage: cd /Volumes/appdata/dockerdiscordcontrol && python scripts/extract_translations.py
"""
import json
import sys
import os
import re

# We parse the Python file directly instead of importing (avoids dependency issues)
TRANSLATION_FILE = os.path.join(os.path.dirname(__file__), '..', 'cogs', 'translation_manager.py')
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'locales')


def extract_translations_from_source():
    """Parse translation_manager.py and extract all translation dicts."""
    with open(TRANSLATION_FILE, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find the _load_translations method and extract the dict
    # We'll use a simpler approach: exec the dict portion
    # Find the start of self._translations = {
    match = re.search(r'self\._translations\s*=\s*\{', content)
    if not match:
        print("ERROR: Could not find self._translations = { in source file")
        sys.exit(1)

    # Find the matching closing brace by counting braces
    start = match.start() + len('self._translations = ')
    brace_count = 0
    i = start
    in_string = False
    string_char = None
    escape_next = False
    triple_quote = False

    while i < len(content):
        ch = content[i]

        if escape_next:
            escape_next = False
            i += 1
            continue

        if ch == '\\':
            escape_next = True
            i += 1
            continue

        # Handle triple quotes
        if not in_string and i + 2 < len(content) and content[i:i+3] in ('"""', "'''"):
            in_string = True
            triple_quote = True
            string_char = content[i:i+3]
            i += 3
            continue

        if in_string and triple_quote and i + 2 < len(content) and content[i:i+3] == string_char:
            in_string = False
            triple_quote = False
            string_char = None
            i += 3
            continue

        # Handle single/double quotes
        if not in_string and ch in ('"', "'") and not (i + 2 < len(content) and content[i:i+3] in ('"""', "'''")):
            in_string = True
            string_char = ch
            i += 1
            continue

        if in_string and not triple_quote and ch == string_char:
            in_string = False
            string_char = None
            i += 1
            continue

        if not in_string:
            if ch == '{':
                brace_count += 1
            elif ch == '}':
                brace_count -= 1
                if brace_count == 0:
                    end = i + 1
                    break

        i += 1
    else:
        print("ERROR: Could not find matching closing brace")
        sys.exit(1)

    dict_source = content[start:end]

    # Clean up Python-specific syntax for eval
    # Remove comments
    lines = dict_source.split('\n')
    cleaned_lines = []
    for line in lines:
        # Remove inline comments (but not # inside strings)
        cleaned_lines.append(line)

    dict_source = '\n'.join(cleaned_lines)

    # Evaluate the dict
    try:
        translations = eval(dict_source)
    except Exception as e:
        print(f"ERROR: Could not evaluate translations dict: {e}")
        # Try line by line to find the error
        sys.exit(1)

    return translations


def build_english_from_keys(translations):
    """Build English translation file where key = value for all keys across all languages."""
    all_keys = set()
    for lang_dict in translations.values():
        all_keys.update(lang_dict.keys())

    # For English, check if there's an explicit 'en' dict
    en_dict = translations.get('en', {})

    # For any key not in en, the key itself IS the English text
    en_full = {}
    for key in sorted(all_keys):
        en_full[key] = en_dict.get(key, key)

    return en_full


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("Extracting translations from translation_manager.py...")
    translations = extract_translations_from_source()

    print(f"Found {len(translations)} languages: {list(translations.keys())}")

    # Build English (source of truth - key = value for missing entries)
    en_translations = build_english_from_keys(translations)
    print(f"English: {len(en_translations)} keys")

    # Write English
    en_path = os.path.join(OUTPUT_DIR, 'en.json')
    with open(en_path, 'w', encoding='utf-8') as f:
        json.dump(en_translations, f, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"Written: {en_path}")

    # Write each language
    for lang, lang_dict in translations.items():
        if lang == 'en':
            continue
        # Ensure all keys from English exist, fill missing with English value
        full_dict = {}
        for key in sorted(en_translations.keys()):
            full_dict[key] = lang_dict.get(key, en_translations[key])

        lang_path = os.path.join(OUTPUT_DIR, f'{lang}.json')
        with open(lang_path, 'w', encoding='utf-8') as f:
            json.dump(full_dict, f, ensure_ascii=False, indent=2, sort_keys=True)

        # Count how many are actually translated (different from English)
        translated = sum(1 for k in full_dict if full_dict[k] != en_translations.get(k, k))
        print(f"Written: {lang_path} ({translated}/{len(full_dict)} translated)")

    print("\nDone! JSON files written to locales/")


if __name__ == '__main__':
    main()
