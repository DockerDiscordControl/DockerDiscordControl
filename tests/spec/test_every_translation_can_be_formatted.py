# -*- coding: utf-8 -*-
"""A placeholder that a translator mistyped is a crash in a language nobody reads.

THE FINDING (review E36, while adding the live-log footers for E35): several
catalogue keys carry placeholders - ``"🔄 Auto-refreshing every {seconds}s •
{remaining} updates remaining"`` - and the code fills them with ``.format()``.
A translation that writes ``{second}``, or ``{Sekunden}``, or leaves a stray
``{`` behind, raises ``KeyError``, ``IndexError`` or ``ValueError`` **at the
moment the message is shown**, in that language only.

DDC ships forty languages. Nobody on this project reads most of them, so a
typo in ``th.json`` or ``lv.json`` would sit there until a user in Thailand or
Latvia pressed a button - and what they would get is not a broken string but
an exception, which before review E24 meant a hanging interaction.

Nothing checked this. ``test_bot_strings_exist_in_the_catalog`` asks whether
the KEY exists; it never looks at what the value says.

The check is cheap and total: every key in ``en.json`` that has a placeholder
is formatted in every one of the forty catalogues, with a dummy value for each
name the ENGLISH key declares. A translation that invents a placeholder the
English one does not have fails too, and it should - the code would never pass
it.
"""

import json
import re
import string
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
LOCALES = PROJECT / "locales"


def _placeholders(text: str):
    """The named fields this string expects, and a value each will accept.

    The value has to match the FORMAT SPEC, not just the name: `{latency:.2f}`
    and `{hour:02d}` are numeric, and handing them a string raises ValueError -
    which the first version of this test did, and then blamed the catalogue.
    """
    try:
        fields = {}
        for _lit, name, spec, _conv in string.Formatter().parse(text):
            if not name:
                continue
            spec = spec or ""
            if spec.endswith(("f", "e", "g", "%")):
                fields[name] = 1.5
            elif spec.endswith(("d", "n", "b", "o", "x", "X")):
                fields[name] = 7
            else:
                fields[name] = "X"
        return fields
    except (ValueError, KeyError):
        return None          # unbalanced braces - reported by the caller


def _catalogues():
    meta = json.loads((LOCALES / "meta.json").read_text(encoding="utf-8"))
    return {code: json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))
            for code in meta}


def test_the_english_keys_parse_at_all():
    english = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
    broken = [k for k in english if _placeholders(k) is None]
    assert not broken, f"English keys with unbalanced braces: {broken}"


def test_every_translation_formats_with_the_english_fields():
    catalogues = _catalogues()
    english = catalogues["en"]

    with_fields = {k: f for k in english if (f := _placeholders(k))}
    assert with_fields, "no key has a placeholder - the check has gone blind"

    failures = []
    for code, data in catalogues.items():
        for key, fields in with_fields.items():
            text = data.get(key)
            if text is None:
                continue                     # a missing key is a different test
            try:
                text.format(**fields)
            except (KeyError, IndexError, ValueError) as e:
                failures.append(f"{code}.json: {key[:40]!r} -> {type(e).__name__}: {e}")

    assert not failures, (
        "these translations cannot be formatted and would raise where they are "
        "shown, in that language only:\n  " + "\n  ".join(failures)
    )


def test_a_mistyped_placeholder_would_be_caught():
    """Guard against a blunt tool: prove the check can fail."""
    text = "Auto-refreshing every {second}s"      # the key says {seconds}
    try:
        text.format(seconds="X")
    except KeyError:
        return
    pytest.fail("a mistyped placeholder did not raise - the check above proves nothing")
