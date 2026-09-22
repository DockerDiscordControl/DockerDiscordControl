# -*- coding: utf-8 -*-
"""The server order can be sorted by Compose stack with one button (Phase 4c, part 2).

Until now the operator put the containers of one stack next to each other by
hand, row by row with + and -. The panel now shows each container's stack and
offers "Sort by stack": containers of one stack move together, to where the
stack's first member stands; containers outside a stack keep their place
among each other. Only the rows move - saving stays the operator's step.

* the ordering itself is app/static/js/stack_order.js, run in node by
  tests/js/stack_order.test.js (SKIPPED where node is missing - the
  production image the runner uses has none; the GitHub CI runners have it);
* the server table carries each row's stack (data-compose-project), shows it,
  loads the script, and offers the button only when a container is in a
  stack at all.

COUNTER-CHECK (2026-09-22): the node cases were red before the script
existed; dropping the "already sorted" guard turns the button case red (the
page would be marked changed for nothing). The template case was red before
the row attribute existed.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_the_stack_order_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/stack_order.test.js by hand")
    result = subprocess.run([node, str(ROOT / "tests" / "js" / "stack_order.test.js")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("ok     ") == 4, result.stdout


@pytest.fixture
def render(monkeypatch):
    monkeypatch.setenv("DDC_ENABLE_BACKGROUND_REFRESH", "false")
    monkeypatch.setenv("DDC_ENABLE_MECH_DECAY", "false")
    from flask import render_template

    from app.web import create_app

    app = create_app({"TESTING": True})

    def _render(containers):
        with app.test_request_context("/"):
            return render_template("_server_selection.html", all_containers=containers,
                                   configured_servers={}, container_info_data={}, docker_cache={})
    return _render


def _container(name, project):
    return {"id": name + "0123456789", "name": name, "status": "running", "image": "nginx",
            "compose_project": project}


def test_the_rows_name_their_stack_and_the_button_is_offered(render):
    html = render([_container("web", "blog"), _container("plex", None)])
    assert 'data-container-name="web" data-compose-project="blog"' in html
    assert 'data-container-name="plex" data-compose-project=""' in html
    assert 'id="sort-by-stack-btn"' in html
    assert "Stack: blog" in html


def test_the_page_loads_the_script():
    scripts = (ROOT / "app" / "templates" / "_scripts.html").read_text(encoding="utf-8")
    assert "filename='js/stack_order.js'" in scripts


def test_without_any_stack_there_is_no_button(render):
    html = render([_container("plex", None), _container("solo", None)])
    assert 'id="sort-by-stack-btn"' not in html
