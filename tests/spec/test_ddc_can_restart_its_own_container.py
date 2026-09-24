# -*- coding: utf-8 -*-
"""DDC can restart itself, and offers the button only when it is needed.

THE OPERATOR ASKED (2026-09-24) for a button that restarts the DDC container,
shown only when a restart is actually needed - and added that an earlier
assistant had told him this was impossible "because the systems are separated".

THEY ARE NOT SEPARATED, and it took one measurement to show it. From inside the
running container on his own server:

    HOSTNAME                     1f27843345e6
    docker inspect ... .Id       1f27843345e6...
    DOCKER_HOST                  unix:///run/ddc-proxy/docker.sock
    containers.get($HOSTNAME)    dockerdiscordcontrol, running

Docker names a container's hostname after its own short id, so the process
finds itself with no configuration. The allowlist in front of the socket
already permits POST /containers/<name>/restart for any name, so nothing had to
be opened up. DDC's entire job is to restart containers; its own is one of them.

THE ONE THING THAT NEEDS CARE IS THE ORDER. A restart kills the process that is
answering the request, so the answer has to be on its way first. The route
returns at once and a timer asks Docker a moment later. A test that let the
timer fire would be restarting the machine it runs on, so the timer is handed
in and the case checks WHAT WAS SCHEDULED instead.

WHAT IT REFUSES: a hostname that is not a container id. An operator who gave
the container a name of their own gets no button rather than a restart aimed at
whatever else answers to that name.

`protected_containers` (["ddc", "portainer"]) is not a guard against this. It
stops auto-action RULES from acting on DDC unattended, which is the opposite of
an operator pressing a button that says the bot is going down.

HOW THIS TEST CAN FAIL: a restart asked for before the answer is sent, a button
offered where it cannot work, or the route losing its login.

COUNTER-CHECK (2026-09-24): red before - there was no module, no route and no
button.
"""

import json
import re
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
BASE = PROJECT / "app" / "templates" / "_base.html"


class _Container:
    def __init__(self, name="dockerdiscordcontrol"):
        self.name = name
        self.restarted = 0

    def restart(self):
        self.restarted += 1


class _Client:
    """A docker client stand-in that knows exactly one container."""

    def __init__(self, known="1f27843345e6", container=None):
        self.container = container or _Container()
        self._known = known
        self.asked = []

    class _Containers:
        def __init__(self, outer):
            self.outer = outer

        def get(self, name):
            self.outer.asked.append(name)
            if name != self.outer._known:
                raise RuntimeError("No such container")
            return self.outer.container

    @property
    def containers(self):
        return self._Containers(self)


class _Timer:
    """A timer that never fires: it records what it was asked to do."""

    scheduled = []

    def __init__(self, delay, function):
        self.delay = delay
        self.function = function
        self.daemon = False
        self.started = False

    def start(self):
        self.started = True
        _Timer.scheduled.append(self)


@pytest.fixture(autouse=True)
def _no_timers():
    _Timer.scheduled = []
    yield
    _Timer.scheduled = []


def test_the_container_finds_itself(monkeypatch):
    """THE MEASUREMENT: Docker sets HOSTNAME to the short id."""
    from services.docker_service.self_restart import own_container_id

    monkeypatch.setenv("HOSTNAME", "1f27843345e6")

    assert own_container_id() == "1f27843345e6"


@pytest.mark.parametrize("hostname", ["", "my-nice-name", "ddc-01", "1f27843345eZ", "1f2784"])
def test_a_hostname_that_is_not_an_id_is_refused(hostname, monkeypatch):
    """A restart aimed at the wrong container is worse than no button."""
    from services.docker_service.self_restart import own_container_id

    monkeypatch.setenv("HOSTNAME", hostname)

    assert own_container_id() is None


def test_a_full_length_id_is_accepted(monkeypatch):
    from services.docker_service.self_restart import own_container_id

    monkeypatch.setenv("HOSTNAME", "1f27843345e6" + "a" * 52)

    assert own_container_id() == "1f27843345e6" + "a" * 52


def test_it_says_which_container_it_would_restart(monkeypatch):
    from services.docker_service.self_restart import describe_self

    monkeypatch.setenv("HOSTNAME", "1f27843345e6")
    ok, name = describe_self(_Client())

    assert ok is True
    assert name == "dockerdiscordcontrol"


def test_it_says_no_when_it_cannot_find_itself(monkeypatch):
    """Asked before the button is offered, so no control is shown that cannot
    work."""
    from services.docker_service.self_restart import describe_self

    monkeypatch.setenv("HOSTNAME", "1f27843345e6")
    ok, why = describe_self(_Client(known="something-else"))

    assert ok is False
    assert "RuntimeError" in why


def test_the_restart_is_scheduled_and_not_done_yet(monkeypatch):
    """THE ORDER IS THE POINT: a restart kills the process answering the
    request, so the answer has to leave first."""
    from services.docker_service.self_restart import restart_myself

    monkeypatch.setenv("HOSTNAME", "1f27843345e6")
    client = _Client()
    ok, name = restart_myself(client, timer=_Timer)

    assert ok is True
    assert name == "dockerdiscordcontrol"
    assert client.container.restarted == 0, "it restarted before answering"
    assert len(_Timer.scheduled) == 1
    assert _Timer.scheduled[0].started is True
    assert 0 < _Timer.scheduled[0].delay <= 5


def test_what_was_scheduled_really_restarts(monkeypatch):
    """Counter-check: a timer that was handed an empty function would pass
    every case above."""
    from services.docker_service.self_restart import restart_myself

    monkeypatch.setenv("HOSTNAME", "1f27843345e6")
    client = _Client()
    restart_myself(client, timer=_Timer)
    _Timer.scheduled[0].function()

    assert client.container.restarted == 1


def test_nothing_is_scheduled_when_it_cannot_find_itself(monkeypatch):
    from services.docker_service.self_restart import restart_myself

    monkeypatch.setenv("HOSTNAME", "not-an-id")
    ok, _why = restart_myself(_Client(), timer=_Timer)

    assert ok is False
    assert _Timer.scheduled == []


def test_a_failing_restart_does_not_escape_the_timer(monkeypatch):
    """By then the response is gone and nobody is listening; an exception in a
    timer thread would only be printed by the interpreter at exit."""
    from services.docker_service.self_restart import restart_myself

    class _Angry(_Container):
        def restart(self):
            raise RuntimeError("daemon says no")

    monkeypatch.setenv("HOSTNAME", "1f27843345e6")
    client = _Client(container=_Angry())
    restart_myself(client, timer=_Timer)

    _Timer.scheduled[0].function()          # must not raise
    # And it really did try: once when the route checked whether it could,
    # once in the timer. Without this the case would pass on a timer handed an
    # empty function - which is what an assertion-free test looks like.
    assert client.asked == ["1f27843345e6", "1f27843345e6"], client.asked


# --- the way in ---------------------------------------------------------------

def test_the_route_exists_and_needs_a_login():
    """It takes the bot offline; it is not something a passer-by may do."""
    import ast

    source = (PROJECT / "app" / "blueprints" / "system_routes.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    restart_route = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        marks = [ast.unparse(d) for d in node.decorator_list]
        if any("restart-self" in m for m in marks):
            restart_route = marks

    assert restart_route, "no route restarts the container"
    # And it is reachable: a blueprint nobody registers is a route nobody has.
    wiring = (PROJECT / "app" / "web" / "blueprints.py").read_text(encoding="utf-8")

    assert "system_bp" in wiring, "the blueprint holding it is never registered"
    assert any("login_required" in m for m in restart_route), (
        "the restart route can be called without logging in")
    assert any("POST" in m for m in restart_route), "a restart must not be a GET"


def test_the_button_sits_in_the_notice_that_only_appears_when_needed():
    """The operator asked for it to be shown only when a restart is needed.
    The notice already answers exactly that question
    (app/static/js/restart_notice.js), so the button lives inside it rather
    than acquiring a second rule that could disagree."""
    assert "restart-now-button" in _alert_element(), "the button is not in the notice"


def _alert_element():
    """The notice as an element: from its opening <div to its closing tag.

    Slicing from the id, as the first version of this did, starts in the middle
    of the opening tag - so every remaining attribute counted as visible text
    and the case reported "restart-required-alert" as an untranslated word.
    """
    markup = BASE.read_text(encoding="utf-8")
    at = markup.index('id="restart-required-alert"')
    start = markup.rindex("<div", 0, at)
    return markup[start:markup.index("</div>", start) + len("</div>")]


def test_the_notice_is_translated():
    """Found while putting the button in it: the box was hard-coded English in
    a panel that speaks forty languages - "Info:" and "Container restart
    required for changes!", the same in Japanese as in German."""
    text = re.sub(r"<[^>]*>|{{.*?}}|{%.*?%}", " ", _alert_element())

    assert not re.search(r"[A-Za-z]{3,}", text), f"untranslated text: {text.strip()!r}"


@pytest.mark.parametrize("key", ["web.restart.needed", "web.restart.now",
                                 "web.restart.running", "web.restart.failed"])
def test_every_new_text_is_in_every_catalogue(key):
    missing = [p.name for p in sorted((PROJECT / "locales").glob("*.json"))
               if p.name != "meta.json"
               and not json.loads(p.read_text(encoding="utf-8")).get(key)]

    assert missing == [], f"{key} missing from {len(missing)}: {missing[:5]}"
