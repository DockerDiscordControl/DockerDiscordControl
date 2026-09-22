# -*- coding: utf-8 -*-
"""
THE FINDING (review E47): `ContainerLogService` carries three async helpers -
`_get_container_logs_service_first`, `_get_docker_client_async` and
`_fetch_container_logs_async` - that nothing calls. Not the service, not a
route, not a test. The sync path replaced them, and says so in its own
docstring: "avoids asyncio/gevent conflicts".

Dead code on its own is only clutter. This lot is worse, because of what it
says. `_get_container_logs_service_first` ends

    except (AttributeError, TypeError, RuntimeError) as e:
        self.logger.error(...)
        return None

which is exactly the defect C18 removed from the sync path twenty lines above:
a Docker failure returned as None, which the caller reads as "no such
container" and reports to the operator as a 404. Whoever reconnects this -
and its name says it is the modern one - reintroduces C18 by doing so.

The guard is not "no dead code". It is: every private helper on this service
must be reachable from something the service actually offers. That can fail,
and it fails on the next helper that is written and then orphaned.
"""

import ast
import pathlib

SERVICE = pathlib.Path(__file__).resolve().parents[2] / "services/web/container_log_service.py"


def _class_node(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is gone from {SERVICE.name}")


def _self_calls(node):
    """Every `self.<name>(...)` made inside this method."""
    calls = set()
    for child in ast.walk(node):
        if (isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and isinstance(child.func.value, ast.Name)
                and child.func.value.id == "self"):
            calls.add(child.func.attr)
    return calls


def test_every_private_helper_is_reachable_from_a_public_method():
    """THE FINDING: a helper nobody calls is a helper nobody maintains, and
    this service already carries one that contradicts a fix it sits next to."""
    tree = ast.parse(SERVICE.read_text(encoding="utf-8"))
    cls = _class_node(tree, "ContainerLogService")

    methods = {
        item.name: item
        for item in cls.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    reachable = set()
    frontier = [name for name in methods if not name.startswith("_")]
    while frontier:
        name = frontier.pop()
        if name in reachable or name not in methods:
            continue
        reachable.add(name)
        frontier.extend(_self_calls(methods[name]))

    orphans = sorted(
        name for name in methods
        if name.startswith("_") and name != "__init__" and name not in reachable
    )

    assert not orphans, (
        "these helpers are not reachable from any public method of "
        f"ContainerLogService: {orphans}. Either wire them up or remove them - "
        "an orphan that still answers a Docker failure with None is C18 waiting "
        "to be reconnected."
    )
