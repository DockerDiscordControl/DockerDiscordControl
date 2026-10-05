# -*- coding: utf-8 -*-
"""A status beat in which nothing went wrong writes nothing at INFO.

THE FINDING (operator, 2026-10-05, a screenshot of the container log: "is the
log cleaned up, so it cannot grow forever?"). It is bounded - Docker keeps 3 x
10 MB, discord.log 6 x 10 MB - but every quiet minute wrote six routine lines
at INFO, "Loaded server order: [...]" twice with all 37 container names, and
discord.log rotated about every three days with the real events in between.
An earlier rule (tests/spec/test_a_repeating_loop_does_not_announce_itself.py)
had kept the closing line of each cycle at INFO; the operator decided that a
quiet one goes to DEBUG as well.

THE CONTRACT: the lines below are DEBUG; the two closing lines of a beat reach
INFO only when the beat had errors (or messages not found).

HOW THIS TEST CAN FAIL: one of these lines back at INFO unconditionally.

COUNTER-CHECK (2026-10-05): red on the code before the change, all nine.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ROUTINE = {
    "services/docker_service/server_order.py": ["Loaded server order: ",
                                                "Server order file does not exist"],
    "cogs/status_handlers.py": ["[INTELLIGENT_BULK_FETCH] Fast adaptive fetch completed"],
    "cogs/overview_embeds.py": ["CACHE (collapsed): Using cached power data"],
    "app/blueprints/main_routes.py": ["WEB UI: Using cached mech status"],
    "services/web/donation_status_service.py": ["WEB UI: Using cached mech status"],
    "cogs/control_ui.py": ["All performance caches cleared"],
    "app/utils/shared_data.py": ["Loaded ACTIVE container '", "Skipped INACTIVE container '"],
}
ONLY_WHEN_SOMETHING_HAPPENED = {
    "cogs/background_loops.py": ("[STATUS_LOOP] Cache updated:", "logging.INFO if error_count else logging.DEBUG"),
    "cogs/message_updates.py": ("Direct Cog Periodic message update finished.",
                                "logging.INFO if (error_count or not_found_count) else logging.DEBUG"),
}


def _calls_with(path, text):
    source = (ROOT / path).read_text(encoding="utf-8")
    calls = re.findall(r"(\w+(?:\.\w+)*)\((?:\s*[^()]*?,)?\s*f?[\"']" + re.escape(text), source)
    assert calls, f"{path}: no log call with {text!r} - the line moved or was renamed"
    return calls, source


def test_routine_lines_are_debug():
    loud = []
    for path, texts in ROUTINE.items():
        for text in texts:
            calls, _ = _calls_with(path, text)
            loud += [f"{path}: {call}({text}...)" for call in calls if not call.endswith(".debug")]
    assert not loud, loud


def test_a_beats_closing_lines_are_info_only_when_something_happened():
    for path, (text, level) in ONLY_WHEN_SOMETHING_HAPPENED.items():
        source = (ROOT / path).read_text(encoding="utf-8")
        assert re.search(r"logger\.log\(" + re.escape(level) + r",\s*f?[\"']" + re.escape(text), source), \
            f"{path}: {text!r} is not logged at INFO only when something happened"
