# -*- coding: utf-8 -*-
"""A private helper is called by the code it sits in, or it is gone.

THE RULE, WIDENED FROM ITS SHAPE (2026-09-24).
test_no_scheduling_helper_is_unreachable.py found five helpers in
services/scheduling/schedule_helpers.py that nothing calls - among them a
``check_schedule_permissions`` that is named like a permission check and is
wired to nothing, so "the next person to use one gets a permission check that
checks no permission". That is a rule about helpers; the test that pins it
reads ONE file, because that is where the finding was.

Asked of the whole application, eight more answered:

    cogs/control_ui.py           _channel_has_control_permission    4 lines
                                 _create_mech_history_display     189
                                 _create_info_embed                36
                                 _return_embed_to_pool             15
    cogs/channel_lifecycle.py    _clean_sweep_bot_messages         18
    services/web/mech_web_service.py   _create_donation_animation  35
    services/config/config_service.py  two legacy form wrappers     6

303 lines, and the first of them is the same sentence again: a method called
"has control permission" that nothing asks. _clean_sweep_bot_messages is a
dead copy of ChannelCleanupService.clean_sweep_bot_messages, which is live and
tested - so the copy could drift from the original without a single test
noticing, in a method that deletes messages.

WHAT COUNTS AS WIRED: the name appearing anywhere else in cogs, services, app
or utils - a call, a reference, a registration. A DECORATED function is never
counted as dead: @app.before_request and friends are called by name nowhere
and by the framework always. Dunders are somebody else's protocol.

CALLED ONLY BY TESTS is a different thing and is listed by name below, not
swept: a test exercising a helper production no longer uses is a weaker smell
than dead code, and each of them needs its own decision. The list may only
shrink.

TWO TRAPS I FELL INTO WHILE MEASURING THIS, both written into the checks:
a word-boundary search for `_clean_sweep_bot_messages` does not match
`test_clean_sweep_bot_messages_uses_bot_user`, so a helper looked untested
when it was not; and the first scan called every decorated function dead.

HOW THIS TEST CAN FAIL: leaving a private helper behind when its last caller
goes.

COUNTER-CHECK (2026-09-24): red before, naming all eight.
"""

import ast
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SOURCE_DIRECTORIES = ("cogs", "services", "app", "utils")

# Private helpers with no caller in the application, kept because the tests use
# them. Each one is a decision waiting to be made, not a habit. ONLY SHRINKS.
ONLY_THE_TESTS_USE_THEM = {
    "app/blueprints/main_routes.py::_get_cached_mech_state",
    "app/utils/port_diagnostics.py::_test_if_this_is_our_host",
    "services/docker_service/client_factory.py::_reset_for_tests",
    "services/infrastructure/container_status_service.py::_deactivate_container",
    "services/mech/animation_cache_service.py::_get_walk_scale_factor",
    "services/mech/animation_cache_service.py::_smart_crop_frames",
    "services/web/mech_status_details_service.py::_get_speed_description",
}


def _sources():
    for directory in SOURCE_DIRECTORIES:
        for path in sorted((PROJECT / directory).rglob("*.py")):
            yield path, path.read_text(encoding="utf-8", errors="replace")


def _private_helpers():
    """(where, name, node) for every undecorated single-underscore definition."""
    for path, source in _sources():
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("_") or node.name.startswith("__"):
                continue
            if node.decorator_list:
                # @app.before_request, @property, @tasks.loop: called by name
                # nowhere and by the framework always.
                continue
            yield path.relative_to(PROJECT).as_posix(), node.name


def _unwired():
    application = "\n".join(source for _path, source in _sources())
    dead = []
    for where, name in _private_helpers():
        mentions = len(re.findall(r"\b" + re.escape(name) + r"\b", application))
        if mentions > 1:          # more than the definition itself
            continue
        entry = f"{where}::{name}"
        if entry in ONLY_THE_TESTS_USE_THEM:
            continue
        dead.append(entry)
    return dead


def test_the_scan_sees_the_helpers():
    """Safeguard against a blunt tool: a scan finding nothing is green."""
    found = list(_private_helpers())

    assert len(found) > 200, f"only {len(found)} private helpers found - wrong path?"


def test_no_private_helper_is_left_wired_to_nothing():
    """THE FINDING: eight of them, 303 lines, including a permission check
    nothing asks and a message-deleting copy of a live service method."""
    dead = _unwired()

    assert dead == [], (
        f"{len(dead)} private helper(s) are called by nothing - delete them, or "
        f"list them in ONLY_THE_TESTS_USE_THEM with the reason:\n  "
        + "\n  ".join(dead))


def test_the_test_only_list_still_describes_real_helpers():
    """A list that names something that is gone stops being read. Every entry
    must still be a helper, and still be one production does not call."""
    defined = {f"{where}::{name}" for where, name in _private_helpers()}
    application = "\n".join(source for _path, source in _sources())

    vanished = sorted(entry for entry in ONLY_THE_TESTS_USE_THEM if entry not in defined)
    assert vanished == [], f"listed but no longer defined: {vanished}"

    revived = sorted(
        entry for entry in ONLY_THE_TESTS_USE_THEM
        if len(re.findall(r"\b" + re.escape(entry.split("::")[1]) + r"\b", application)) > 1)
    assert revived == [], (
        f"these have a caller again - take them off the list: {revived}")
