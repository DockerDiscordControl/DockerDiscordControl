# -*- coding: utf-8 -*-
"""The mech animation test bench is gone, in all four layers or none.

THE SAME SHAPE AS THE TEMPORARY DEBUG MODE, found the same night by the same
question: which elements does a script address that the panel does not have?

Five of them belong to a test bench for the donation mech::

    test-donor-name   test-amount   test-total-donations   mech-preview   mech-stats

and no template has ever carried any of them. Three functions in
mech_panel.js read them - ``testMechAnimation``, ``testSpeedControl``,
``testSimpleMech`` - and nothing calls those three: they are not exported, not
bound to a listener, not named in any markup. Behind them stand two
authenticated routes, ``/api/test-mech-animation`` and
``/api/mech-speed-config``, whose only fetch in the whole project is inside
those unreachable functions, and two MechWebService methods with a request
type each that only those routes call.

Four layers again, and again every one of them answering. A bench for a
workshop that was never built.

WHAT IS NOT THIS. ``/mech_animation`` is the real one - the panel asks for it
on every load, which the operator's own access log shows - and it stays, with
everything under it.

ALSO REMOVED: ``donatorHeart``, one line in the live donation handler that
looks up an element no template has and then never uses the result. Harmless,
and the same claim: a name the page does not carry.

HOW THIS TEST CAN FAIL: any layer of the bench coming back, or the real mech
animation going with it.

COUNTER-CHECK (2026-09-26): red before on every layer.
"""

from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
WHERE_TO_LOOK = ("app", "services", "cogs", "utils")

THE_BENCH = ("test-donor-name", "test-amount", "test-total-donations",
             "mech-preview", "mech-stats", "donatorHeart")
ITS_FUNCTIONS = ("testMechAnimation", "testSpeedControl", "testSimpleMech")


def _sources():
    for folder in WHERE_TO_LOOK:
        for suffix in ("*.py", "*.js", "*.html"):
            for path in sorted((PROJECT / folder).rglob(suffix)):
                yield path


def test_no_script_reaches_for_a_bench_that_is_not_there():
    """LAYER ONE."""
    found = []
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        for name in THE_BENCH + ITS_FUNCTIONS:
            if name in text:
                found.append(f"{path.relative_to(PROJECT)}: {name}")

    assert found == [], "the mech test bench is still addressed:\n  " + "\n  ".join(found)


def test_no_route_answers_for_it():
    """LAYER TWO. Two authenticated endpoints whose only caller in the whole
    project sits inside a function nothing can enter."""
    routes = (PROJECT / "app" / "blueprints" / "main_routes.py").read_text(encoding="utf-8")

    for path in ("/api/test-mech-animation", "/api/mech-speed-config"):
        assert path not in routes, f"main_routes.py still answers {path}"


def test_the_service_went_with_it():
    """LAYERS THREE AND FOUR. The methods and their request types are what
    made the routes above look wanted."""
    service = (PROJECT / "services" / "web" / "mech_web_service.py").read_text(encoding="utf-8")

    for name in ("def get_test_animation", "def get_speed_config",
                 "class MechTestAnimationRequest", "class MechSpeedConfigRequest"):
        assert name not in service, f"mech_web_service still has {name}"


def test_the_real_mech_animation_is_untouched():
    """THE OPPOSITE MISTAKE, and it would be visible on the operator's own
    settings page: /mech_animation is the one the panel asks for on every
    load, and it has nothing to do with the bench."""
    routes = (PROJECT / "app" / "blueprints" / "main_routes.py").read_text(encoding="utf-8")

    assert "/mech_animation" in routes, "the real mech animation route is gone"

    service = (PROJECT / "services" / "web" / "mech_web_service.py").read_text(encoding="utf-8")

    assert "class MechWebService" in service, "the whole service went"
    assert "def get_live_animation" in service, \
        "the animation the panel really asks for is gone"

    panel = (PROJECT / "app" / "static" / "js" / "mech_panel.js").read_text(encoding="utf-8")

    assert "mech_animation" in panel, "the panel no longer asks for its animation"


def test_the_donation_handler_still_works():
    """donatorHeart was one dead line inside a LIVE handler. Taking the line
    must not take the handler."""
    panel = (PROJECT / "app" / "static" / "js" / "mech_panel.js").read_text(encoding="utf-8")

    assert "thankYouOverlay" in panel, "the thank-you overlay is gone"
    assert "/api/donation/click" in panel, "the donation click is no longer recorded"
    assert ".donation-button" in panel, "the donation buttons are no longer bound"


def test_the_scan_looks_at_the_whole_panel():
    """The counter-check: every case above passes on an empty file list."""
    files = list(_sources())

    assert len(files) > 250, len(files)
    assert any(path.name == "mech_panel.js" for path in files)
    assert any(path.name == "mech_web_service.py" for path in files)
