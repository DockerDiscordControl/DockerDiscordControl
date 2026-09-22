# -*- coding: utf-8 -*-
# @covers Z6
"""Z6 - DDC never removes or destroys a container.

There are exactly three actions: ``start``, ``stop``, ``restart``. No ``kill``,
no ``remove``, no ``prune``.

This guarantee is the only one that already **holds** today. It is nailed down
here BEFORE anyone softens it - that is exactly the point: removing a container
cannot be undone, and a later "it would be handy if DDC could also clean up"
rework should fail on a test and not on the attentiveness of the next person.

There are two implementations, and both must satisfy the guarantee:

* ``DockerActionService._valid_actions`` (``docker_action_service.py:90-94``) -
  the path that button, schedule and web panel take.
* ``docker_action()`` (``docker_utils.py:626-631``) - the older path that only
  the automation rules still use.

The test reads the action names from both places and compares them with a list
written out here. Deliberately NOT checked is what the lambda expressions do -
that would be a mirror test of the implementation. What is checked is the
promise: these three names, no others.

COUNTER-CHECK (performed 2026-09-16) - different here than usual:

This guarantee holds today, so there is no bug that could be reverted. All four
tests were green on the first run. That is exactly what makes them suspicious -
a test that was never red could also be one that CANNOT become red. Two
precautions against that:

1. ``test_the_check_above_can_fire_at_all`` proves on the search pattern
   itself that it detects ``container.remove()``, ``containers.prune()`` and
   ``client.kill()`` and leaves harmless lines alone.
2. The first version of the source check had a real bug:
   ``if ".remove(" in line and "containers" not in line: continue`` skipped
   of all things ``container.remove()``, because "containers" does not occur
   in it. It was green and could not fail for the most important case.
   Found during review, not in a run.

Also found during review and removed: an assertion of the form
``assert ... is None or True`` - always true, of all places in the safeguard
against worthless tests.

I had predicted only medium confidence for the two middle tests
(the AST extract collects every dict literal of the function; the search
pattern could fire harmlessly elsewhere). Both held.
"""

import ast
import inspect
import re
from pathlib import Path

import pytest

ALLOWED = {"start", "stop", "restart"}

# Names whose appearance breaks the guarantee. Not exhaustive - an unknown
# fourth action is already caught by the set comparison.
FORBIDDEN = {"kill", "remove", "rm", "prune", "delete", "destroy"}


def test_action_service_knows_exactly_three_actions():
    """The main path: button, schedule, web panel."""
    from services.docker_service.docker_action_service import DockerActionService

    service = DockerActionService()
    assert set(service._valid_actions) == ALLOWED, (
        f"The action list has changed: {sorted(service._valid_actions)}. "
        f"DDC should start, stop and restart containers - not remove them."
    )


def test_legacy_path_knows_exactly_the_same_three():
    """The older path of the automation rules.

    Read from the source via AST: ``valid_actions`` is a local variable in
    ``docker_action()`` and not reachable from outside without executing the
    function - which would mean a real Docker call.
    """
    from services.docker_service import docker_utils

    source = inspect.getsource(docker_utils.docker_action)
    tree = ast.parse(source.strip())

    found_keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            for k in node.value.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    found_keys.add(k.value)

    assert found_keys == ALLOWED, (
        f"The legacy path knows different actions than the main path: "
        f"{sorted(found_keys)} instead of {sorted(ALLOWED)}. Two paths, the same "
        f"rule - they must not diverge."
    )


def test_no_destructive_docker_action_in_the_source():
    """No call that removes a container - project-wide.

    Checks the call site, not the function: the two lists above can be
    correct while ``container.remove()`` is called directly elsewhere. Exactly
    this kind of gap ("the function is checked, the call next to it is not")
    was a finding from stage 0.
    """
    root = Path(__file__).resolve().parents[2]
    suspicious = []

    # Only calls on a receiver that looks like Docker. Without this
    # restriction, harmless lines such as ``items.remove(x)`` would fire.
    #
    # The first version of this check had ``if ".remove(" in line and
    # "containers" not in line: continue`` here - and thereby skipped of all
    # things ``container.remove()``, because "containers" does not occur in it.
    # It could not fail for the most important case. Found during review,
    # not in a run: it would have been green.
    receiver = re.compile(
        r"\b(?:container|containers|client|docker_client)\.(" + "|".join(FORBIDDEN) + r")\s*\("
    )

    for folder in ("services", "cogs", "app", "utils"):
        for file in (root / folder).rglob("*.py"):
            for nr, line in enumerate(
                file.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            ):
                bare = line.strip()
                if bare.startswith("#"):
                    continue
                if receiver.search(bare):
                    suspicious.append(f"{file.relative_to(root)}:{nr}: {bare}")

    assert not suspicious, (
        "Destructive Docker calls found:\n" + "\n".join(suspicious)
    )


def test_the_check_above_can_fire_at_all():
    """Safeguard against a blunt tool.

    A search pattern that finds nothing cannot be distinguished from one that
    has nothing to find. This proves that it detects the case it is meant to
    detect - and that it leaves harmless lines alone.
    """
    pattern = re.compile(
        r"\b(?:container|containers|client|docker_client)\.(" + "|".join(FORBIDDEN) + r")\s*\("
    )

    assert pattern.search("container.remove()"), "does not detect container.remove()"
    assert pattern.search("containers.prune()"), "does not detect containers.prune()"
    assert pattern.search("self.client.kill(c)"), "does not detect client.kill()"
    assert not pattern.search("self.pending_actions.remove(name)"), "false alarm"
    assert not pattern.search("items.delete(x)"), "false alarm"
