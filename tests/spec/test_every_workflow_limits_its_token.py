# -*- coding: utf-8 -*-
"""Every workflow says what its GITHUB_TOKEN may do.

CodeQL #56 (actions/missing-workflow-permissions): docker-publish.yml had no
top-level `permissions:` block. Its `test` job therefore ran with the
repository's default token rights, which on older repositories include write
access to the code. That job installs dependencies from PyPI and runs the
whole suite, so it is the job least in need of them.

A job without its own block inherits the workflow's. So the rule checked here
is the one that closes the gap for every job at once: each workflow declares
`permissions:` at the top level, and a job that needs more says so itself
(as build_and_push does for the package registry).
"""

from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def _workflows():
    return sorted(WORKFLOWS.glob("*.yml"))


def test_the_scan_sees_the_workflows():
    """Guard against a blunt tool: no workflows found would pass trivially."""
    names = {path.name for path in _workflows()}
    assert {"docker-publish.yml", "tests.yml"} <= names, names


def test_every_workflow_declares_top_level_permissions():
    missing = [path.name for path in _workflows()
               if "permissions" not in (yaml.safe_load(path.read_text(encoding="utf-8")) or {})]
    assert not missing, f"no top-level permissions: block in {missing}"


def test_the_publish_gate_reads_only():
    """The job that runs third-party code gets no write right at all."""
    workflow = yaml.safe_load((WORKFLOWS / "docker-publish.yml").read_text(encoding="utf-8"))
    rights = workflow["jobs"]["test"].get("permissions", workflow.get("permissions"))

    assert isinstance(rights, dict), rights
    assert "write" not in rights.values(), rights
