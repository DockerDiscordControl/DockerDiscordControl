# -*- coding: utf-8 -*-
"""Every cooldown slider in the panel belongs to a button that exists.

WHAT THE SLIDERS ARE. The spam protection modal (Configuration -> Spam
Protection -> "Button Cooldowns (seconds)") holds one number per Discord
button: how long somebody must wait before pressing that button again.

THE FINDING. Three of them steered nothing:

    Overview Toggle Button   5   the ➕/➖ on the container rows
    Mech Expand              3   the ➕ on the mech in the overview
    Mech Collapse            2   the ➖ on the mech in the overview

All three buttons were removed on 2026-09-25 as unreachable. The fields
stayed, looking exactly like the nineteen that work, and nothing in the panel
says which is which. The operator asked for the "Overview Toggle Button"
field himself on 2026-09-19, when it still had a button - so the fields were
removed only after he decided, and this file is what stops the next one
arriving unnoticed.

NOTHING BREAKS EITHER WAY, which is why it needed a test rather than a crash:
an unknown key falls back to five seconds
(``spam_protection_service.get_button_cooldown``), and a stored value for a
key nobody asks for is simply never read.

THE OTHER DIRECTION is guarded by
tests/spec/test_requested_cooldown_keys_exist.py: a key live code asks for
must exist in the defaults and in the panel. That file states plainly that it
holds in ONE direction only, and that keys nobody requests are "separate
findings with a separate decision by the operator". He has now taken it.

HOW A SLIDER IS FOUND TO BE LIVE - and why it is not a list. Four shapes
reach the service, measured in the tree rather than assumed:

    is_on_cooldown(user, "info")            a literal key
    is_on_cooldown(user, self.action)       ActionButton, built with
                                            "start" / "stop" / "restart"
    is_on_cooldown(user, self.custom_id)    MechHistoryButton, whose id is
                                            f"mech_history_{channel}"
    _mech_button_braked(i, f"mech_story_…") an explicit brake name

So the scan collects the fixed text of every cooldown argument, every
``custom_id=`` and every literal handed to a pressable class when it is
built, and applies the service's own rule: ``mech_history_4242`` means the
slider ``mech_history``. A hand-kept list of live sliders would go stale
exactly like the three fields this found.

WHAT IT CANNOT SEE, said plainly so it promises no more than it delivers: a
key assembled from values that only exist at runtime. Every button in DDC
today spells its key or its id in the source.

HOW THIS TEST CAN FAIL: a slider in the panel whose name no button can
produce, or a panel and its save script that no longer offer the same fields.

COUNTER-CHECK (2026-09-25): red before - refresh, mech_expand, mech_collapse.
"""

import ast
import json
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
MARKUP = PROJECT / "app" / "templates" / "_spam_protection_modal.html"
SCRIPT = PROJECT / "app" / "static" / "js" / "spam_protection_modal.js"

COOLDOWN_CALLS = {"get_button_cooldown", "is_on_cooldown", "add_user_cooldown",
                  "get_remaining_cooldown", "_mech_button_braked"}
A_KEY = re.compile(r"[a-z][a-z_]*")

# Sliders for buttons that are not in cogs/ at all. The admin overview builds
# its ids in admin_overview.py and asks with them; they are covered by
# test_requested_cooldown_keys_exist.py from the other side.
NOT_A_DISCORD_BUTTON = set()


def _pressable_classes():
    names = set()
    for path in sorted((PROJECT / "cogs").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef) and any(
                    ast.unparse(base).split(".")[-1] in ("Button", "Select")
                    for base in node.bases):
                names.add(node.name)
    return names


def _fixed_text(node):
    """Every piece of literal text in an expression, f-strings included."""
    return [sub.value for sub in ast.walk(node)
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str)]


def _slider_names_the_code_can_produce():
    """Asked of the tree: what could ever reach get_button_cooldown."""
    classes = _pressable_classes()
    found = set()
    for path in sorted((PROJECT / "cogs").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            called = ast.unparse(node.func).split(".")[-1]
            arguments = list(node.args) if called in COOLDOWN_CALLS | classes else []
            arguments += [kw.value for kw in node.keywords if kw.arg == "custom_id"]
            for argument in arguments:
                for text in _fixed_text(argument):
                    word = text.strip().rstrip("_")
                    if not A_KEY.fullmatch(word):
                        continue
                    found.add(word)
                    # the service's own rule: mech_history_4242 -> mech_history
                    parts = word.split("_")
                    if len(parts) >= 2:
                        found.add(f"{parts[0]}_{parts[1]}")
    return found


def _fields_in_the_panel():
    return set(re.findall(r'id="button_([a-z_]+)"', MARKUP.read_text(encoding="utf-8")))


def _keys_in_the_save_script():
    """(every key the script writes, the ones that REQUIRE a field).

    Two shapes, and the difference matters. ``getElementById(x).value``
    throws when the field is absent. ``getElementById(x)?.value || 5`` is
    written on purpose for the admin overview's five, which are saved from a
    default because the hard-coded list here would otherwise drop a slider
    the read loop above had just rendered.
    """
    block = SCRIPT.read_text(encoding="utf-8")
    every = set(re.findall(r"getElementById\('button_([a-z_]+)'\)", block))
    optional = set(re.findall(r"getElementById\('button_([a-z_]+)'\)\?\.", block))
    return every, every - optional


def test_no_slider_belongs_to_a_button_that_is_gone():
    """THE FINDING: three fields for three removed buttons."""
    reachable = _slider_names_the_code_can_produce()
    orphans = sorted(field for field in _fields_in_the_panel()
                     if field not in reachable and field not in NOT_A_DISCORD_BUTTON)

    assert orphans == [], (
        "these sliders are offered in the panel and steer nothing - no button "
        f"can ask for them: {orphans}")


def test_the_scan_finds_the_sliders_that_do_work():
    """The counter-check eleven sabotages have walked past: a scan that finds
    everything reachable passes the case above while proving nothing.

    The four shapes from the header, one example each - and mech_story is the
    subtle one, reached only through an f-string handed to a helper."""
    reachable = _slider_names_the_code_can_produce()

    for live in ("info", "start", "stop", "restart", "mech_history", "mech_story"):
        assert live in reachable, f"{live} is a working slider and was not found"


def test_a_slider_for_a_button_that_never_existed_is_caught():
    """The scanner against a sabotage, on text of its own so the case cannot
    pass just because the repository happens to be clean."""
    reachable = _slider_names_the_code_can_produce()

    for invented in ("summon_kraken", "mech_teleport"):
        assert invented not in reachable, invented


def test_a_comment_about_a_removed_button_does_not_revive_it():
    """The mistake five of my own scans made today, from the other side. The
    header above names mech_expand and mech_collapse on purpose; asking the
    syntax tree for CONSTANTS means prose cannot bring a slider back."""
    source = (
        "# mech_expand used to brake here\n"
        '"""The mech_collapse slider is gone."""\n'
        "value = 1\n")
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            found.append(node)

    assert found == [], "the sabotage snippet was meant to hold no calls at all"


def test_the_panel_and_its_save_script_offer_the_same_fields():
    """The other way this goes wrong. The script writes a COMPLETE object from
    a fixed enumeration, so a field left in the markup but dropped from the
    script silently resets on every save, and a key read with a plain
    ``.value`` whose field is gone makes the save throw.

    The admin overview's five are read with ``?.value || default`` exactly so
    they can be saved WITHOUT a field, so they are held to the first rule
    only - which is what a first version of this case got wrong."""
    in_markup, (in_script, needs_a_field) = _fields_in_the_panel(), _keys_in_the_save_script()

    assert in_markup - in_script == set(), (
        f"in the panel, never saved: {sorted(in_markup - in_script)}")
    assert needs_a_field - in_markup == set(), (
        "the save reads .value of a field that is not there: "
        f"{sorted(needs_a_field - in_markup)}")


def test_the_defaults_hold_no_slider_the_panel_dropped():
    """A key left in the defaults is completed into every configuration and
    into every GET answer, so it outlives the field it belonged to."""
    from services.infrastructure.spam_protection_service import SpamProtectionService
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        defaults = SpamProtectionService(config_dir=directory)._get_default_config()

    reachable = _slider_names_the_code_can_produce()
    # admin_overview_* are built in admin_overview.py, outside the scan's reach
    # by design - they are guarded from the other side.
    stale = sorted(key for key in defaults.button_cooldowns
                   if key not in reachable and not key.startswith("admin_overview_"))

    assert stale == [], f"defaults still carry sliders nothing can ask for: {stale}"


def test_every_remaining_field_has_a_label_in_every_language():
    """A field without its text shows a bare key to the operator."""
    fields = sorted(_fields_in_the_panel())
    markup = MARKUP.read_text(encoding="utf-8")
    keys = [f"web.spam.button_{field}" for field in fields
            if f"_t('web.spam.button_{field}')" in markup]

    assert len(keys) == len(fields), (
        f"a field carries no label: {sorted(set(fields) - {k.rsplit('.', 1)[-1][len('button_'):] for k in keys})}")

    missing = []
    for catalogue in sorted((PROJECT / "locales").glob("*.json")):
        if catalogue.name == "meta.json":
            continue
        texts = json.loads(catalogue.read_text(encoding="utf-8"))
        missing += [f"{catalogue.stem}:{key}" for key in keys if not texts.get(key)]

    assert missing == [], missing
