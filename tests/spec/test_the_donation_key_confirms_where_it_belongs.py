# -*- coding: utf-8 -*-
"""Entering a donation key confirms inside its own card, not somewhere else.

THE FINDING (design pass of the panel, 2026-09-23; verified here before
fixing): typing a valid key into "Donation System Control" is supposed to put
a green alert at the top of that card and a "Premium active" badge in its
header. The code that does it reaches for the elements like this:

    const cardBody = document.querySelector('.card-body');        # line 493
    const header   = document.querySelector('.card-header h6');   # line 502

Neither is scoped to anything. `document.querySelector` answers with the FIRST
match in the whole document, and this modal is included at config.html:1906 -
after every settings section. The first `.card-body` in document order belongs
to `_language_timezone_settings.html:156`, the hidden `#ctTestResult` box of
the channel-translation test; the first `.card-header h6` belongs to
`_spam_protection_modal.html:18`, because the spam modal is included at 1903,
three lines earlier.

So the confirmation is inserted into a hidden div in the Language section, and
the badge onto the spam-protection card. The operator types a valid key, sees
nothing happen, and has no way to tell whether the key was accepted.

It is worse than a one-off: `if (!statusAlert)` guards the insertion, so once
the element exists somewhere - anywhere - the code stops trying. The
misplacement is permanent for that page load.

WHAT CHANGES: the two targets get ids of their own and are addressed by id.
Not `modal.querySelector('.card-body')` either - this modal has four cards,
and the donation one is the fourth.

HOW THIS TEST CAN FAIL: it reads the modal's script for an unscoped
querySelector on a class that occurs many times in the page, and checks that
whatever it addresses instead actually exists in the same template. Reaching
for a bare `.card-body` again is red.

COUNTER-CHECK (2026-09-23): red before - both lines were there as quoted.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODAL = ROOT / "app" / "templates" / "_advanced_settings_modal.html"
TEMPLATES = ROOT / "app" / "templates"


def _without_comments(text):
    """A sentence about a rule is not the rule - my own comments have defeated
    my own assertions repeatedly today."""
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


def test_it_does_not_reach_for_the_first_card_in_the_document():
    """THE FINDING: it did, and the first one is in another section entirely."""
    modal = _without_comments(MODAL.read_text(encoding="utf-8"))

    assert "document.querySelector('.card-body')" not in modal, (
        "the donation confirmation is inserted into whatever .card-body comes "
        "first in the document, which is not this modal")
    assert "document.querySelector('.card-header h6')" not in modal, (
        "the premium badge is put on whatever .card-header h6 comes first")


def test_the_targets_it_uses_exist_in_this_template():
    """Counter-check: addressing an id that is not there fails the same way,
    silently, because both insertions are behind an `if`."""
    modal = MODAL.read_text(encoding="utf-8")

    for element_id in ("donationCardBody", "donationCardHeader"):
        assert f'id="{element_id}"' in modal, f"{element_id} is addressed but never rendered"
        assert f"getElementById('{element_id}')" in modal or \
               f'getElementById("{element_id}")' in modal


def test_those_ids_are_unique_across_the_whole_page():
    """Counter-check on the fix itself: an id that repeats would put the
    confirmation back in the lottery this came from."""
    seen = {}
    for path in sorted(TEMPLATES.rglob("*.html")):
        for element_id in re.findall(r'id="(donationCard\w+)"',
                                     path.read_text(encoding="utf-8")):
            seen.setdefault(element_id, []).append(path.name)

    repeated = {k: v for k, v in seen.items() if len(v) > 1}
    assert repeated == {}, repeated


def test_the_first_card_body_on_the_page_is_still_somebody_elses():
    """The mechanism, pinned so the fix is not mistaken for luck.

    If the include order ever changed so that this modal came first, the old
    code would start working by accident and nobody would know why. This says
    the page is still arranged the way that made the bug.
    """
    page = (TEMPLATES / "config.html").read_text(encoding="utf-8")

    language = page.index("_language_timezone_settings.html")
    advanced = page.index("_advanced_settings_modal.html")

    assert language < advanced, (
        "the include order changed - re-read this test before trusting it")
    assert 'class="card-body' in (TEMPLATES / "_language_timezone_settings.html").read_text(
        encoding="utf-8")
