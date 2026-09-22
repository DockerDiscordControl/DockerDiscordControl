# -*- coding: utf-8 -*-
"""A button or a modal that fails must answer. They are how DDC is used.

THE FINDING (review E24, found while reading cogs/status_info_integration.py):
review E14 wired up `application_command_error`, so a failing SLASH COMMAND
answers the user instead of hanging. Buttons and modals do not travel that way,
and nothing was listening for them either.

Measured in the shipped py-cord:

  * `ui/view.py:428`   `View._scheduled_task` wraps `item.callback(interaction)`
                       in `except Exception` and calls `self.on_error(...)`;
  * `ui/view.py:393`   the default `View.on_error` prints the traceback to
                       stderr and answers the interaction **not at all**;
  * `ui/modal.py:242`  `Modal.on_error` does the same.

DDC defines neither. So pressing Start, Stop, Restart, a mech button, Live
Logs or any task button and hitting an error left the interaction spinning
until Discord gave up with "This interaction failed" - with nothing in DDC's
log, because a bare `print()` to stderr is not the logger.

**This is larger than E14.** DDC has 8 slash commands and 25 view classes; the
buttons are the interface. `/serverstatus` posts a panel and everything after
that is a button.

Both bases answer and log, and both tests below enumerate the REPO rather than
a list, so a view or modal added tomorrow is covered today - the same reason
the background-loop test reads its loops off the class (review E17).
"""

import ast
import pathlib

import pytest

PROJECT = pathlib.Path(__file__).resolve().parents[2]
SKIP = {"tests", "scripts", ".git", "node_modules", "venv", ".venv"}


def _classes_with_base(matcher):
    """Every class in the source tree whose bases match, as (file, name, bases)."""
    found = []
    for path in sorted(PROJECT.rglob("*.py")):
        if any(part in SKIP for part in path.relative_to(PROJECT).parts):
            continue
        if path.name == "ddc_ui.py":
            continue  # the module that DEFINES the bases, and must inherit the real ones
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = [ast.unparse(b) for b in node.bases]
            if matcher(bases):
                found.append((str(path.relative_to(PROJECT)), node.name, bases))
    return found


def _is_view(bases):
    return any(b in ("View", "discord.ui.View") for b in bases)


def _is_modal(bases):
    return any(b in ("Modal", "discord.ui.Modal") for b in bases)


def test_the_shared_bases_exist_and_answer():
    from cogs.ddc_ui import DDCModal, DDCView

    for base in (DDCView, DDCModal):
        assert "on_error" in vars(base), (
            f"{base.__name__} does not define on_error, so py-cord's default - "
            f"a print() to stderr, and no answer to the user - still applies"
        )


def test_no_view_inherits_discord_ui_view_directly():
    offenders = _classes_with_base(_is_view)

    assert not offenders, (
        "these views inherit discord.ui.View directly, so a failing button in "
        "them leaves the interaction spinning until Discord gives up, with "
        "nothing in DDC's log:\n  " +
        "\n  ".join(f"{f}:{n}" for f, n, _ in offenders)
    )


def test_no_modal_inherits_discord_ui_modal_directly():
    offenders = _classes_with_base(_is_modal)

    assert not offenders, (
        "these modals inherit discord.ui.Modal directly:\n  " +
        "\n  ".join(f"{f}:{n}" for f, n, _ in offenders)
    )


@pytest.mark.asyncio
async def test_a_failing_button_answers_the_user():
    from cogs.ddc_ui import DDCView

    class _Response:
        def __init__(self):
            self.sent = []
            self._done = False

        def is_done(self):
            return self._done

        async def send_message(self, content, **_kw):
            self._done = True
            self.sent.append(content)

    class _Interaction:
        def __init__(self):
            self.response = _Response()

    view = DDCView.__new__(DDCView)
    interaction = _Interaction()
    item = type("Item", (), {"custom_id": "stop_alpha", "label": "Stop"})()

    await DDCView.on_error(view, ValueError("boom"), item, interaction)

    assert interaction.response.sent, (
        "the button failed and the user was told nothing - the interaction "
        "spins until Discord says 'This interaction failed'"
    )


@pytest.mark.asyncio
async def test_a_failing_button_does_not_paste_the_exception():
    """Same rule as E14: answer, but do not hand Discord the repr."""
    from cogs.ddc_ui import DDCView

    class _Response:
        def __init__(self):
            self.sent = []

        def is_done(self):
            return False

        async def send_message(self, content, **_kw):
            self.sent.append(content)

    interaction = type("I", (), {"response": _Response()})()
    view = DDCView.__new__(DDCView)
    item = type("Item", (), {"custom_id": "x", "label": "x"})()

    await DDCView.on_error(view, ValueError("a secret from inside the process"),
                           item, interaction)

    assert "secret from inside" not in " ".join(interaction.response.sent)


@pytest.mark.asyncio
async def test_a_failing_button_is_logged_by_ddc_not_printed():
    import logging

    from cogs.ddc_ui import DDCView

    class _Response:
        def is_done(self):
            return True

    class _Followup:
        async def send(self, *_a, **_kw):
            return None

    interaction = type("I", (), {"response": _Response(), "followup": _Followup()})()
    view = DDCView.__new__(DDCView)
    item = type("Item", (), {"custom_id": "stop_alpha", "label": "Stop"})()

    import _pytest.logging  # noqa: F401  (caplog needs the plugin loaded)
    logger = logging.getLogger("ddc.ddc_ui")
    records = []
    handler = logging.Handler()
    handler.emit = records.append
    logger.addHandler(handler)
    try:
        await DDCView.on_error(view, ValueError("boom"), item, interaction)
    finally:
        logger.removeHandler(handler)

    messages = [r.getMessage() for r in records if r.levelno >= logging.ERROR]
    assert messages, "nothing reached DDC's logger; py-cord's print() is not a log"
    assert "stop_alpha" in " ".join(messages), (
        f"the notice does not say WHICH button failed: {messages!r}"
    )
