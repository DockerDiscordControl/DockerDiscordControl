# -*- coding: utf-8 -*-
"""A setting from the panel takes effect on EVERY path - or nowhere.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

THE FINDING (stage 2, point 3 - the same rule in two places):
Under "Advanced Settings" the panel offers 23 keys and writes them to
``config['advanced_settings']`` (``config_form_parser_service.py:415-425``).
They are read via ``_get_advanced_setting``, which asks the configuration
FIRST and only then falls back to ``os.environ``.

NINE of these keys, however, were read **directly from the environment** in
the Discord part, in **sixteen** places - and found in two rounds, because the
first version of this detector only knew one of several access forms::

    via os.environ.get (nine places, first round)
      DDC_DOCKER_CACHE_DURATION   docker_control.py:182, :3643,
                                  container_status_service.py:108,
                                  status_cache_service.py:40
      DDC_DOCKER_MAX_CACHE_AGE    docker_control.py:2476, :2865, :3057
      DDC_DOCKER_QUERY_COOLDOWN   docker_control.py:225,
                                  docker_status/fetch_service.py:40

    via os.getenv (seven places, second round - initially OVERLOOKED by the
    detector, all in status_info_integration.py)
      DDC_LIVE_LOGS_TIMEOUT, _REFRESH_INTERVAL, _MAX_REFRESHES,
      _TAIL_LINES (2x), _ENABLED, _AUTO_START

These sixteen never saw ``advanced_settings``. Anyone who changes the value in
the panel changes it for the web part - and **not** for the Discord part. No
error message, no hint: the setting is silently ineffective there.

That it can be done differently is shown in the same house:
``cogs/status_handlers.py:341`` and ``:446`` already use
``_get_advanced_setting``. It is not an architecture problem but
inconsistency.

SCOPE - ``DDC_CONFIG_DIR`` is deliberately NOT checked: it is a startup
variable that has to exist BEFORE there is a configuration to read. It
belongs to ``os.environ``. If this test reported it, it would produce a false
alarm - and a test with false alarms gets ignored, so it is as worthless as a
green one.

CHECKED VIA AST, not via text search: ``os.environ.get('DDC_...')`` can appear
in a comment or string. Exactly this false alarm once made the Z10 detector
worthless.

COUNTER-CHECK (performed 2026-09-17): 1 red with **exactly nine** findings,
2 green - exactly as predicted, and the nine matches the manual count to the
point.

The three pitfalls named beforehand did not materialise: the panel keys were
found (otherwise the first guard would have fired), the environment search
works (the second guard proves it via ``DDC_CONFIG_DIR``, which is known to be
read directly), and the number was right.

SECOND ROUND, and it is the actual finding: while merging the duplicated
``_get_container_logs`` it was noticed that ``LiveLogView:245`` reads a panel
key via ``os.getenv`` - and this test had **reported green**. It only knew
``os.environ.get``. The tree, however, also uses ``os.getenv`` (14x),
``_os.environ.get`` and ``(os.environ if env is None else env).get``. A guard
that checks half the truth and reports completion is as worthless as a green
test.

Sharpened via the SHAPE of the call instead of an expected name
(``_reads_environment``). Afterwards red with the seven overlooked places, all
in ``status_info_integration.py``. Two of them are booleans and are read with
``value_type=bool``.

After the conversion: 3 green. Affected groups unchanged - ``cogs`` 267,
``services/infrastructure`` 197, ``services/docker_service`` 86,
``services/web`` 358, ``services/mech`` 433.

WHAT THE FIX CHANGES: the nine places read via ``utils/settings.py``, i.e.
configuration first, environment afterwards. A cache duration set in the
panel now also takes effect in the Discord part.

PULLED ALONG, so that no tenth copy arises:
``web_helpers._get_advanced_setting`` delegates to the same helper instead of
holding the rule a second time.

A NEAR MISS that belongs here because it shows the limit of a guard: while
rebuilding ``web_helpers._get_advanced_setting``, my replacement script cut
with ``s.index("\\ndef ", start+1)`` up to the next module-level ``def`` - and
in doing so deleted **79 instead of 19 lines**, including the module values
``docker_cache``, ``CACHE_CLEANUP_INTERVAL`` and ``cache_lock``. The
ast.parse check **passed**, because the result was syntactically flawless.
It was only noticed in the full run: **37 red tests** in four groups.

The lesson is not "cut more carefully" but: a syntax check says nothing about
whether the content is right. The second version takes the function
boundaries from the AST (``lineno``/``end_lineno``) instead of from a text
search and then explicitly checks that the three module values are still
there.

TWO OWN FALSE ALARMS, which also belong here: my rebuild left five
``get_setting`` imports in ``docker_control.py``, and I took that for
duplication. The mapping via AST showed: each sits in a DIFFERENT function -
exactly the style ``utils/`` uses throughout. I had held a number against an
estimated function count instead of counting. Four dead ``import os``, on the
other hand, were real and have been removed, with a guard against overeager
deletion (if the file still uses ``os``, the import must stay).
"""

import ast
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]

# Application code. scripts/ is excluded - one-off tools, same scope as
# for Z7.
DIRECTORIES = ("cogs", "services", "app", "utils")

# Startup variables: must exist before the configuration, belong to os.environ.
STARTUP_VARIABLES = {"DDC_CONFIG_DIR"}


def _panel_keys() -> set:
    """The keys the panel offers under Advanced Settings.

    Extracted from the source code instead of listed here: an enumeration in
    the test would be the next copy of the same rule - and would go stale as
    soon as the panel gets another key.
    """
    source = (PROJECT / "services" / "web" / "configuration_page_service.py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    keys = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "get_setting_value"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and node.args[0].value.startswith("DDC_")):
            keys.add(node.args[0].value)
    return keys - STARTUP_VARIABLES


def _direct_environment_reads():
    """Places that read a DDC_ key directly from os.environ."""
    hits = []
    for directory in DIRECTORIES:
        for path in sorted((PROJECT / directory).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                if not _reads_environment(node.func):
                    continue
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    hits.append((path.relative_to(PROJECT), node.lineno, first.value))
    return hits


def _reads_environment(func) -> bool:
    """Recognises EVERY spelling of environment access, not just one.

    The first version only knew ``os.environ.get``. The tree, however, also
    uses ``os.getenv`` (14x), ``_os.environ.get`` and forms like
    ``(os.environ if env is None else env).get``. Seven panel keys are read
    via ``os.getenv`` - and the test still reported green.

    A guard that checks half the truth and reports completion is as worthless
    as a green test. That is why the decision here is made by the shape of the
    call, not by an expected name.
    """
    # getenv(...) in any qualification: os.getenv, _os.getenv, getenv
    if isinstance(func, ast.Attribute) and func.attr == "getenv":
        return True
    if isinstance(func, ast.Name) and func.id == "getenv":
        return True
    # <anything with environ>.get(...)
    if isinstance(func, ast.Attribute) and func.attr == "get":
        try:
            target = ast.unparse(func.value)
        except Exception:
            return False
        return "environ" in target
    return False


def test_the_panel_offers_any_keys_at_all():
    """Safeguard against a blunt tool.

    If the key search reads into nothing - because the structure of
    ``configuration_page_service`` changes -, the test below would be green
    without proving anything.
    """
    keys = _panel_keys()
    assert len(keys) > 15, (
        f"Only {len(keys)} panel keys found: {sorted(keys)}. "
        "Probably get_setting_value is no longer called this way."
    )


def test_the_tool_finds_environment_reads():
    """Proof of effect: the detector must find what there is to find.

    Without this case the search could silently return nothing and the test
    below would be green because it sees nothing - not because nothing is there.
    """
    hits = _direct_environment_reads()
    assert hits, "Not a single os.environ.get place found - the tool does not work"
    keys = {k for _, _, k in hits}
    assert "DDC_CONFIG_DIR" in keys, (
        "DDC_CONFIG_DIR is demonstrably read directly and should show up - "
        "if it does not, the tool is searching in the wrong place."
    )


def test_panel_settings_are_not_read_past_the_configuration():
    """What the panel offers must be read via the configuration."""
    panel = _panel_keys()
    findings = [
        f"{path}:{line}  {keys}"
        for path, line, keys in _direct_environment_reads()
        if keys in panel
    ]

    assert not findings, (
        f"{len(findings)} places read a panel setting directly from the "
        "environment and thus never see what the user set in the panel. "
        "The setting works in the web part and is silently ineffective here:\n  "
        + "\n  ".join(findings)
    )
