# -*- coding: utf-8 -*-
"""``create_app`` must really execute every setup step.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

THE FINDING (stage 3, check 3 - function versus call site):
``app/web/app_factory.py:create_app`` assembles the Flask application from
eleven steps. Every single one is tested. The **wiring** was not.

Proven by mutation, not inferred: four steps were removed one at a time from
``create_app``, and ``tests/test_web_factory.py`` stayed **green every
time**::

    without install_csrf_protection       -> 1 passed
    without register_i18n                 -> 1 passed
    without register_background_services  -> 1 passed
    without register_blueprints           -> 1 passed

So the CSRF protection can drop out of the setup without anything turning red.

WHY THE EXISTING TESTS DO NOT CATCH THIS:
``test_web_factory.py`` checks that a Flask instance comes back, ``/health``
answers and ``Content-Security-Policy`` is set - that covers
``install_security_handlers`` and nothing else.
``tests/unit/security/test_bundle3_security.py`` replaces ``register_blueprints``
and ``register_routes`` with its own versions via ``monkeypatch``, so it
explicitly does NOT check the real setup. ``tests/security/test_security_sast.py``
imports from ``app.web_ui`` and skips on ``ImportError``.

A MISTAKE OF MY OWN that belongs here: the survey that led to this finding
first reported EIGHT functions as "call site never tested". That was wrong -
it searched for the module name ``app_factory`` in the test text, but the call
goes through ``from app.web import create_app``. The reporter checks the wrong
name. What remains is one finding instead of eight; but that one is measured.

HOW IT IS CHECKED HERE: not "is the function importable" (that would again be
the function instead of the call site), but: **is it actually called during
the build?** Every step is replaced by a stub that records its call;
afterwards every stub must have been hit exactly once.

COUNTER-CHECK (carried out 2026-09-17) - and the most instructive part is that
THE FIRST VERSION OF THIS TEST WAS ITSELF A MIRROR TEST:

It took the expectation list from the **calls inside create_app**.
If a call drops out, it thereby also disappears from the expectation - the
test compared the file with itself and could not fail. The mutation exposed
it::

    first version, without install_csrf_protection  -> 2 passed   (blind)
    first version, without register_i18n            -> 2 passed   (blind)

The guard ``len(steps) >= 8`` did not catch this: eleven steps become ten,
the threshold holds.

Of all places, at the start of the check that is supposed to find mirror tests.

*Second version:* the expectation comes from the **imports** and is delimited
by the **signature of the origin module** - whatever takes ``app`` as its
first parameter is a setup step. Both live outside the code under test and
remain when a call is dropped.

*One intermediate step still failed:* ``TypeError: 'NoneType' object is not
iterable``. ``build_config`` was in the import list, but is called as
``build_config(os.environ, test_config)`` and its return value flows
into ``app.config.update``. It is a configuration supplier, not a step on the
app object - the signature check correctly excludes it.

*Third version, measured:* 2 green in the normal state. And it bites::

    without install_csrf_protection  -> 1 failed
    without register_i18n            -> 1 failed
    without register_blueprints      -> 1 failed

This proves what is not self-evident for this test: its red does not come
from the finding - the guarantee does hold today - but had to be produced
artificially. Without this check it would be a test that cannot fail.
"""

import ast
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
FACTORY = PROJECT / "app" / "web" / "app_factory.py"

def _expected_steps() -> list:
    """The steps create_app MUST execute - taken from the IMPORTS.

    THE FIRST VERSION WAS A MIRROR TEST, and the mutation exposed it: it
    read the list from the CALLS inside ``create_app``. If a call drops out,
    it also disappears from the expectation - the test compared the file with
    itself and could not fail. Removing ``install_csrf_protection(app)`` left
    it green.

    The imports remain when a call is dropped. They are therefore an
    expectation from OUTSIDE instead of a copy of the code under test. If a
    step is added, it is checked automatically; if its call disappears, the
    test turns red.

    Delimited: only imports from sibling modules (``from .x import y``), and
    only those that take an application object. ``initialize_gevent``
    takes a logger and is therefore an exception.
    """
    import importlib
    import inspect

    tree = ast.parse(FACTORY.read_text(encoding="utf-8"))
    factory_module = importlib.import_module("app.web.app_factory")

    step_names = []
    for node in tree.body:
        if not (isinstance(node, ast.ImportFrom) and node.level == 1):
            continue
        for alias in node.names:
            name = alias.asname or alias.name
            obj = getattr(factory_module, name, None)
            if not callable(obj):
                continue
            try:
                params = list(inspect.signature(obj).parameters)
            except (TypeError, ValueError):
                continue
            # A setup step takes the application object as its first argument.
            # That is in the signature of the ORIGIN MODULE, not in the code under
            # test - so it remains when a call drops out of create_app.
            # build_config(environ, test_config) supplies configuration and is
            # not a step on the app object; initialize_gevent takes a logger.
            if params and params[0] == "app":
                step_names.append(name)
    return sorted(set(step_names))


def _setup_steps() -> list:
    """Kept for the guard below - shows what create_app calls TODAY."""
    tree = ast.parse(FACTORY.read_text(encoding="utf-8"))
    factory = next(k for k in ast.walk(tree)
                  if isinstance(k, ast.FunctionDef) and k.name == "create_app")
    steps = []
    for node in ast.walk(factory):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and len(node.args) == 1
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "app"):
            steps.append(node.func.id)
    return sorted(set(steps))


def test_the_step_list_is_not_empty():
    """Safeguard against a blunt tool.

    If the step search reads into nothing - because the structure of
    ``create_app`` changes - the test below would be green without checking a
    single step. Exactly this kind of flaw has already made a reporter
    worthless twice today.
    """
    expected = _expected_steps()
    assert len(expected) >= 8, (
        f"Only {len(expected)} setup steps read from the imports: {expected}. "
        "Probably app_factory no longer imports them as 'from .x import y'."
    )


def test_create_app_executes_every_setup_step(monkeypatch):
    """If a step drops out of the setup, that must be noticed.

    On 2026-09-17 four steps could be removed without replacement without any
    test turning red - among them the CSRF protection.
    """
    monkeypatch.setenv("DDC_ENABLE_BACKGROUND_REFRESH", "false")
    monkeypatch.setenv("DDC_ENABLE_MECH_DECAY", "false")

    called = []
    steps = _expected_steps()

    for name in steps:
        def stub(app, _name=name):
            called.append(_name)
        # Replace on the FACTORY's module, not on the origin module: create_app
        # bound the names at import time.
        monkeypatch.setattr(f"app.web.app_factory.{name}", stub, raising=True)

    from app.web.app_factory import create_app
    create_app({"TESTING": True})

    missing = [s for s in steps if s not in called]
    assert not missing, (
        "These setup steps are in create_app but were not "
        f"executed: {missing}. Called were: {sorted(set(called))}"
    )
    duplicates = [s for s in set(called) if called.count(s) > 1]
    assert not duplicates, f"Setup steps executed twice: {duplicates}"
