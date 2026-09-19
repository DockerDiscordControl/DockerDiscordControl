# -*- coding: utf-8 -*-
# @covers Z10
"""Z10 - No image is shipped whose tests have not run green.

A published image has a complete, passed test run behind it.

Why this is a guarantee to the USER and not mere house rules: whoever
installs DDC from Unraid Community Apps gets exactly this image. If the suite
does not run, or runs through red, nobody notices - until it shows up on the
user's server. That is the maxim "unnoticed rarely strikes" in its most
expensive form.

Finding from the inventory: ``docker-publish.yml`` runs no tests at all
(checkout, QEMU, Buildx, login, metadata, build-and-push - done), and
in ``tests.yml`` the test steps end in ``|| true``, so that the step CANNOT
fail. A test running red thus has no effect on anything.

This test is RED when it is created. The fix touches the project's delivery
path and is therefore a decision of the operator, not a technical one - it is
deliberately NOT made together with this test.

What is checked is the source text of the workflow files. This is a static
test, not an executed CI: it proves what is in the file, not what GitHub makes
of it. The project already uses the same means in ``test_pkg_f_scripts.py``
for the Dockerfile and healthcheck.

COUNTER-CHECK (carried out 2026-09-16) - with a sharpening in between:

First run: both tests red. But the second only reported ``tests.yml:127``
(integration tests) - and twice, because the line search and the block search
returned the same hit. It missed the **more important** case: in the unit test
step, ``python -m pytest`` is at :73 and the associated ``|| true`` only at :80,
separated by line continuations. A line-by-line search never finds that.

Sharpened by splitting into ``- name:`` steps, and extended by ``continue-on-error:
true`` - a second way of making a test step inconsequential, which the first
version did not know about at all.

After that, four findings instead of one, and the fourth was previously unknown::

    code-quality.yml:295 'Run tests with coverage': continue-on-error: true
    tests.yml:67 'Run unit tests with coverage':    '|| true'
    tests.yml:122 'Run integration tests':          '|| true'
    tests.yml:122 'Run integration tests':          continue-on-error: true

So **three** test runs in the CI, none of which can turn red. The test
correctly left the reporting tools in code-quality.yml (radon, pylint, flake8,
mypy) alone - no false alarms.

FIX CARRIED OUT (2026-09-17), after the operator decided on the
full gate in per-group form:

``docker-publish.yml`` got its own ``test`` job, on which ``build_and_push``
depends via ``needs:``. The four safety switches are gone.

It turned out that "remove the safety switches" was not enough: the three
test invocations of the CI (``pytest tests/unit/``, ``pytest tests/``) abort
during COLLECTION - 79 and 18 errors respectively, not a single test ever ran.
So the switches did not hide red tests, but the fact that nothing was tested
at all. Without a conversion the gate would from now on have been permanently
red and thus as worthless as the previously permanent green. All three
invocations now run per group via ``tests/GROUPS.txt``;
``--import-mode=importlib`` did not help, three retrofitted ``__init__.py``
made it worse, from 18 to 54 errors (reverted).

COUNTER-CHECK: before the fix both tests above were red. Afterwards
``test_no_test_step_cannot_fail`` fired again - four times, and all
four times on **comments** that had only just been written ("No
'|| true' any more ..."). The executable code was clean. Instead of deleting
the explanations, the reporter was sharpened (``_executable_only``) and given
its own proof of effect. After that ``tests/spec``: 50 green, 0 red.

WHAT THIS DOES NOT PROVE: what is checked is the text and the YAML structure
of the workflow files, not a real GitHub run. That the ``test`` job actually
starts there and blocks ``build_and_push`` is only shown by the first push.
These tests can prove that the gate *is in place* - not that GitHub executes
it that way.
"""

import re
from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
PUBLISH = WORKFLOWS / "docker-publish.yml"
TESTS = WORKFLOWS / "tests.yml"


def test_workflow_files_exist():
    """Safeguard against a blunt tool.

    If the files are renamed, the tests below would run into nothing and be
    green without proving anything.
    """
    assert PUBLISH.is_file(), f"{PUBLISH} is missing - then the test below checks nothing"
    assert TESTS.is_file(), f"{TESTS} is missing - then the test below checks nothing"


def test_publishing_depends_on_a_test_run():
    """The workflow that publishes the image must not skip tests.

    Both usual forms are accepted: a separate test step in the same
    workflow, or a ``needs:`` on a job that runs tests.
    """
    content = PUBLISH.read_text(encoding="utf-8")

    has_own_test_run = bool(re.search(r"pytest|python -m pytest", content))
    depends_on_job = bool(re.search(r"^\s*needs:", content, re.MULTILINE))

    assert has_own_test_run or depends_on_job, (
        "docker-publish.yml neither runs tests nor depends on a job "
        "that does - images go out to users unchecked"
    )


def test_the_workflow_files_are_valid_yaml():
    """Safeguard against a blunt tool - and against myself.

    The tests here read the **text** of the workflow files. A file can
    fulfil every assertion and still be broken: if the indentation gets mixed
    up while editing, GitHub does not even load it, the job never runs, and
    the gate gates nothing - while the tests below keep reporting green.

    Noticed while building the gate itself: I had changed three workflow files
    by hand and wanted to check them locally, but PyYAML is missing on the
    development machine. A check that was not carried out is not a passed one -
    so it belongs here, where it runs along with every run.
    """
    yaml = pytest.importorskip(
        "yaml", reason="without PyYAML this check cannot prove anything"
    )
    for file in sorted(WORKFLOWS.glob("*.yml")):
        try:
            loaded = yaml.safe_load(file.read_text(encoding="utf-8"))
        except yaml.YAMLError as error:
            pytest.fail(f"{file.name} is not valid YAML: {error}")
        assert isinstance(loaded, dict) and loaded.get("jobs"), (
            f"{file.name} contains no jobs block - GitHub runs nothing from it"
        )


def test_the_gate_really_depends_on_the_test_job():
    """``needs:`` must point to a job that actually exists.

    The test further up accepts any ``needs:``. A reference to a job that does
    not exist, however, would be exactly the kind of gate nobody notices -
    GitHub rejects the run, and in doubt one only notices when a
    publication fails to appear or slips through.
    """
    yaml = pytest.importorskip(
        "yaml", reason="without PyYAML this check cannot prove anything"
    )
    content = yaml.safe_load(PUBLISH.read_text(encoding="utf-8"))
    jobs = content["jobs"]
    build = jobs.get("build_and_push")
    assert build is not None, "docker-publish.yml no longer has a build_and_push job"

    needed_jobs = build.get("needs")
    assert needed_jobs, "build_and_push depends on no job - images go out unchecked"
    needed_jobs = [needed_jobs] if isinstance(needed_jobs, str) else list(needed_jobs)

    for name in needed_jobs:
        assert name in jobs, f"build_and_push needs job '{name}', which does not exist"

    runs_pytest = any(
        "pytest" in str(step.get("run", ""))
        for name in needed_jobs
        for step in jobs[name].get("steps", [])
    )
    assert runs_pytest, (
        "The jobs build_and_push depends on do not run pytest themselves - "
        f"checked: {needed_jobs}"
    )


def _steps(content: str):
    """Split a workflow into its ``- name:`` steps.

    Necessary because a test invocation can span many lines: in tests.yml
    ``python -m pytest`` is at :73 and the associated ``|| true`` only at :80,
    separated by line continuations. A line-by-line search does not find that -
    the first version of this test therefore overlooked the unit test step of
    all things and only reported the integration test.
    """
    steps, current, start = [], [], 1
    for lineno, line in enumerate(content.splitlines(), 1):
        if re.match(r"\s*- name:", line):
            if current:
                steps.append((start, "\n".join(current)))
            current, start = [line], lineno
        else:
            current.append(line)
    if current:
        steps.append((start, "\n".join(current)))
    return steps


def _executable_only(block: str) -> str:
    """Drops WHOLE comment lines - and nothing else.

    Why this exists (2026-09-17): while building the gate the test below fired
    four times, and all four times on **comments** I had just written
    myself - sentences like "No '|| true' and no continue-on-error
    any more: this step IS the gate". The executable code was clean.

    The obvious remedy would have been to delete these comments. That would
    have removed precisely the explanation of why the safety switches are gone -
    a bad trade. Instead, the reporter now searches for meaning instead of
    text: a line starting with ``#`` is never executed by the shell and
    consequently cannot suppress anything.

    Deliberately ONLY whole comment lines: if everything from the first ``#`` on
    were cut off, a real switch could hide behind it
    (``pytest x || true  # harmless``). Exactly this case is pinned down below.
    """
    return "\n".join(z for z in block.splitlines() if not z.lstrip().startswith("#"))


def _safety_switches(block: str) -> list:
    """Which switches a step carries. An empty list means: can turn red."""
    executable = _executable_only(block)
    found = []
    if "|| true" in executable:
        found.append("'|| true'")
    if re.search(r"continue-on-error:\s*true", executable):
        found.append("continue-on-error: true")
    return found


def test_no_test_step_cannot_fail():
    """A test step that cannot turn red is not a gate.

    Two ways lead there, and both count: ``|| true`` on the invocation and
    ``continue-on-error: true`` on the step. The second was completely missing
    from the first version of this test.

    Deliberately NOT flagged: ``|| true`` on reporting tools
    (radon, pylint, flake8, mypy in code-quality.yml). It is legitimate there:
    the tools deliver a report, not a verdict. A test that reports those too
    produces false alarms and is therefore ignored - and an ignored test is
    as worthless as a green one. For the same reason, pure comment lines no
    longer count since 2026-09-17; see ``_executable_only``.
    """
    findings = []
    for file in sorted(WORKFLOWS.glob("*.yml")):
        for start_line, block in _steps(file.read_text(encoding="utf-8")):
            if "pytest" not in _executable_only(block):
                continue
            head = block.splitlines()[0].strip().removeprefix("- name:").strip()
            for switch in _safety_switches(block):
                findings.append(f"{file.name}:{start_line} '{head}': pytest with {switch}")

    assert not findings, (
        "Test steps that cannot fail:\n" + "\n".join(findings)
    )


def test_the_reporter_still_bites_after_the_sharpening():
    """Proof of effect for ``_executable_only`` - mandatory, because a
    guard looks loosened here.

    Whoever defuses a reporter so that their own code gets through must
    prove that it still catches the real case. Four cases, and the last one
    is the most important: it prevents the sharpening from being
    abused.
    """
    real_true = (
        "      - name: Run tests\n"
        "        run: |\n"
        "          python -m pytest tests/ -q || true\n"
    )
    assert _safety_switches(real_true) == ["'|| true'"], "real '|| true' not detected"

    real_coe = (
        "      - name: Run tests\n"
        "        run: python -m pytest tests/ -q\n"
        "        continue-on-error: true\n"
    )
    assert _safety_switches(real_coe) == ["continue-on-error: true"], (
        "real continue-on-error not detected"
    )

    prose_only = (
        "      - name: Run tests\n"
        "        run: |\n"
        '          # No "|| true" any more and no continue-on-error: true here.\n'
        "          python -m pytest tests/ -q\n"
    )
    assert _safety_switches(prose_only) == [], (
        "Comment wrongly reported as a safety switch - exactly the false alarm "
        "that made the sharpening necessary"
    )

    disguised = (
        "      - name: Run tests\n"
        "        run: |\n"
        "          python -m pytest tests/ -q || true  # looks harmless\n"
    )
    assert _safety_switches(disguised) == ["'|| true'"], (
        "A switch with a comment behind it was overlooked - the sharpening "
        "would then be a loophole instead of a refinement"
    )


def test_the_step_splitting_finds_multiline_invocations():
    """Safeguard against a blunt tool.

    Proves that an invocation spread over line continuations is recognised as
    ONE step - exactly the case the first version missed.
    """
    example = (
        "      - name: Run unit tests\n"
        "        run: |\n"
        "          python -m pytest tests/unit/ \\\n"
        "            --cov=services \\\n"
        "            -v || true\n"
        "      - name: Upload\n"
        "        run: echo hi\n"
    )
    steps = _steps(example)
    assert len(steps) == 2, f"Splitting yielded {len(steps)} steps instead of 2"
    first = steps[0][1]
    assert "pytest" in first and "|| true" in first, (
        "Invocation and '|| true' did not land in the same step - the splitting "
        "would overlook the unit test step again"
    )
