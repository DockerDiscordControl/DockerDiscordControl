# -*- coding: utf-8 -*-
"""A script that writes a settings field says so, or the warning never comes.

HOW THE PANEL KNOWS IT IS DIRTY. ``#config-form`` carries one delegated
listener for ``input`` and ``change``; anything the operator types or picks
inside the form bubbles up to it and raises "You have unsaved changes".

WHAT IT CANNOT SEE. Assigning ``element.value`` from JavaScript fires NO
event. A script that fills a form field therefore changes the configuration
without the panel noticing, and the banner stays away.

THE FINDING (2026-09-25). ``saveContainerInfo`` in config-ui.js writes twelve
of the form's hidden fields - a container's info text, its protected content
and password, and the four player-count override fields - straight into the
markup and announced nothing. The operator configured a container, saw no
banner, and had no reason to think anything needed saving. Pressing Save for
an unrelated reason would have taken the settings along; leaving the page
would have dropped them without a word.

IT MATTERS MORE THAN IT LOOKS. The operator asked on the same day whether the
banner is reliable enough to replace the big "Save configuration" button. A
FALSE ALARM is a nuisance; this is the other kind - the change that never
announces itself - and while one of those exists, the big button is the only
thing standing between him and silent data loss.

THE ANNOUNCEMENT ALREADY EXISTED. ``markConfigurationChanged()`` dispatches a
bubbling ``change`` from the container list, which is inside the form, so the
delegated listener sees it. Two callers used it - reordering a row and the
"sort by stack" button - and the one that writes the most fields did not.

WHAT THIS DOES NOT CATCH, said plainly: it reads JavaScript with regular
expressions, so it sees the shape this defect had - a field found by
``querySelector('input[name=…]')`` and then assigned. A script that reaches a
field some other way is outside its sight.

HOW THIS TEST CAN FAIL: a function that assigns to a form field found by name
without announcing the change.

COUNTER-CHECK (2026-09-25): red before - saveContainerInfo, twelve writes,
no announcement.
"""

import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SCRIPTS = PROJECT / "app" / "static" / "js"

# The two ways the panel announces a change to the form.
ANNOUNCEMENTS = ("markConfigurationChanged", "showUnsavedChangesAlert")

A_FUNCTION = re.compile(r"^(?:async )?function \w+|^window\.\w+ = function", re.M)
A_NAMED_FIELD = re.compile(
    r"(?:const|let|var)\s+(\w+)\s*=\s*document\.querySelector\(`?input\[name=")


def _functions(source):
    """(name, body) for every top-level function in one script."""
    starts = [m.start() for m in A_FUNCTION.finditer(source)] + [len(source)]
    for first, second in zip(starts, starts[1:]):
        body = source[first:second]
        named = re.match(r"^(?:async )?function (\w+)|^window\.(\w+)", body)
        yield (named.group(1) or named.group(2)) if named else "?", body


def _writes_a_form_field(body):
    """Assignments INTO a field that was looked up by its form name.

    The direction is the whole point: openContainerInfoModal looks the same
    fields up and copies them INTO the dialog, which changes nothing and must
    not announce anything. So the check asks which side of the ``=`` the
    field is on, not whether the function mentions one.
    """
    fields = set(A_NAMED_FIELD.findall(body))
    return sorted(field for field in fields
                  if re.search(rf"\b{re.escape(field)}\.value\s*=[^=]", body))


def _silent_writers():
    found = []
    for path in sorted(SCRIPTS.glob("*.js")):
        for name, body in _functions(path.read_text(encoding="utf-8")):
            written = _writes_a_form_field(body)
            if written and not any(word in body for word in ANNOUNCEMENTS):
                found.append(f"{path.name}:{name} writes {', '.join(written)}")
    return found


def test_nothing_fills_a_settings_field_without_announcing_it():
    """THE FINDING: twelve fields written, no banner."""
    assert _silent_writers() == [], (
        "these change the configuration without the panel noticing, so the "
        f"unsaved-changes banner never appears: {_silent_writers()}")


def test_the_scan_sees_the_shape_the_defect_had():
    """The counter-check eleven sabotages have walked past: a scan matching
    nothing passes the case above while proving nothing."""
    sabotage = (
        "function fillItIn(container) {\n"
        "  const hostInput = document.querySelector(`input[name=\"query_host_${container}\"]`);\n"
        "  if (hostInput) hostInput.value = 'somewhere';\n"
        "}\n")
    name, body = next(iter(_functions(sabotage)))

    assert name == "fillItIn", name
    assert _writes_a_form_field(body) == ["hostInput"], _writes_a_form_field(body)


def test_reading_a_field_into_a_dialog_is_not_a_change():
    """The opposite mistake, and the one this nearly made:
    openContainerInfoModal looks up the SAME fields and copies them into the
    dialog. Flagging it would force an announcement for opening a window."""
    reader = (
        "function openIt(container) {\n"
        "  const hostInput = document.querySelector(`input[name=\"query_host_${container}\"]`);\n"
        "  const modalHost = document.getElementById('modal-query-host');\n"
        "  if (modalHost && hostInput) modalHost.value = hostInput.value || '';\n"
        "}\n")
    _name, body = next(iter(_functions(reader)))

    assert _writes_a_form_field(body) == [], _writes_a_form_field(body)


def test_the_announcement_reaches_the_form():
    """``markConfigurationChanged`` is only worth calling while it bubbles
    from something INSIDE the form - otherwise the delegated listener never
    hears it and every caller would be announcing into the void."""
    source = (SCRIPTS / "config-ui.js").read_text(encoding="utf-8")
    body = next(body for name, body in _functions(source)
                if name == "markConfigurationChanged")

    assert "bubbles: true" in body, body
    assert "docker-container-list" in body, body

    markup = (PROJECT / "app" / "templates" / "_server_selection.html").read_text(encoding="utf-8")

    assert 'id="docker-container-list"' in markup
