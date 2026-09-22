# -*- coding: utf-8 -*-
"""One source repository, one build, four Docker Hub names.

Until v2.4.1 every platform name (``-linux``, ``-mac``, ``-windows``) had its
own GitHub repository with its own copy of the code and its own publish
workflow. Each release meant syncing three repositories by hand, and they had
already drifted (``.dockerignore`` untracked in all three, ``logs/.gitkeep``
missing in one). The four ``latest`` tags carried four different digests.

The Docker Hub names must stay: the ``-mac`` image is pulled more often than
the main one. So the main repository now pushes the SAME build under all four
names, and the platform repositories are archived after the first release
that fills all four from here.

What this pins down, as contracts rather than as the workflow's wording:

* ``docker-publish.yml`` publishes exactly these four names - no fifth, none
  missing - and the build step pushes the tags that list produces, not a
  hard-coded list of its own.
* No other workflow in this repository can push an image. A second pushing
  workflow is exactly how two builds end up under one name again.
* The README sync writes the description of all four names from the one
  README, and no other workflow writes a Docker Hub description, and no
  short description is longer than Docker Hub keeps.
* No document in the repository links to the platform repositories, which
  get archived.

COUNTER-CHECK (carried out 2026-09-22): written before the workflows were
changed. Red for the two reasons expected - three names missing from the
publish list, three names without a description - and red for the 100
characters (the old main description had 115). Three tests were green from the
start, so each was broken on purpose and went red: a hard-coded ``tags:`` in
the build step, a ``docker/login-action`` step and a
``peter-evans/dockerhub-description`` step slipped into ``tests.yml``.
The link test was red with 21 links, all in README.md, before the README was
rewritten.

WHAT THIS DOES NOT PROVE: it reads the workflow files, not a GitHub run. That
the four names really carry one digest is only shown by the first release,
measured against the registry (Phase 1, step 6). It also cannot see the three
platform repositories, whose own workflows keep pushing until they are
archived.
"""

import re
from pathlib import Path

import yaml

PROJECT = Path(__file__).resolve().parents[2]
WORKFLOWS = PROJECT / ".github" / "workflows"
PUBLISH = "docker-publish.yml"
README_SYNC = "dockerhub-readme-sync.yml"

FOUR_NAMES = {
    "dockerdiscordcontrol/dockerdiscordcontrol",
    "dockerdiscordcontrol/dockerdiscordcontrol-linux",
    "dockerdiscordcontrol/dockerdiscordcontrol-mac",
    "dockerdiscordcontrol/dockerdiscordcontrol-windows",
}


def _load(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _steps(workflow):
    for job in (workflow.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            yield step


def _uses(step, action):
    """True if the step runs the given action, whatever version it pins."""
    return str(step.get("uses", "")).split("@")[0] == action


def _image_list(value):
    """metadata-action accepts newline- or comma-separated names."""
    return {
        part.strip()
        for line in str(value).splitlines()
        for part in line.split(",")
        if part.strip()
    }


def _pushes_an_image(step):
    """Every way a workflow step here could put an image on a registry."""
    if _uses(step, "docker/build-push-action"):
        return True
    if _uses(step, "docker/login-action"):
        return True
    run = " ".join(str(step.get("run", "")).split())
    return any(
        marker in run
        for marker in ("docker push", "docker image push", "--push", "buildx imagetools create")
    )


def test_the_scan_sees_the_workflows():
    """Guard against a blunt tool: an empty directory would pass everything."""
    names = {path.name for path in WORKFLOWS.glob("*.yml")}
    assert {PUBLISH, README_SYNC} <= names, names


def test_the_publish_workflow_names_exactly_the_four_images():
    metadata_steps = [s for s in _steps(_load(PUBLISH)) if _uses(s, "docker/metadata-action")]
    assert len(metadata_steps) == 1, (
        f"expected one metadata step in {PUBLISH}, found {len(metadata_steps)}"
    )
    images = _image_list(metadata_steps[0].get("with", {}).get("images", ""))
    assert images == FOUR_NAMES, (
        f"missing: {sorted(FOUR_NAMES - images)}, unexpected: {sorted(images - FOUR_NAMES)}"
    )


def test_the_build_pushes_the_tags_of_that_list():
    """The build must push what the metadata step produced.

    A hard-coded ``tags:`` would make the four-name list above decorative:
    the test would stay green while the build pushed one name only.
    """
    steps = list(_steps(_load(PUBLISH)))
    meta_ids = [s.get("id") for s in steps if _uses(s, "docker/metadata-action")]
    builds = [s for s in steps if _uses(s, "docker/build-push-action")]
    assert len(builds) == 1, f"expected one build step in {PUBLISH}, found {len(builds)}"
    tags = str(builds[0].get("with", {}).get("tags", "")).replace(" ", "")
    assert meta_ids and meta_ids[0] and tags == "${{steps.%s.outputs.tags}}" % meta_ids[0], (
        f"the build pushes {tags!r}, not the metadata step's tags"
    )


def test_no_other_workflow_can_push_an_image():
    findings = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if path.name == PUBLISH:
            continue
        for step in _steps(_load(path.name)):
            if _pushes_an_image(step):
                findings.append(f"{path.name}: {step.get('name') or step.get('uses') or step.get('run')}")
    assert not findings, "Only docker-publish.yml may push images:\n" + "\n".join(findings)


def test_the_push_detector_bites():
    """Proof of effect for ``_pushes_an_image``: without it the test above
    could pass because the detector sees nothing, not because nothing pushes."""
    assert _pushes_an_image({"uses": "docker/build-push-action@v6"})
    assert _pushes_an_image({"uses": "docker/login-action@v3"})
    assert _pushes_an_image({"run": "docker push dockerdiscordcontrol/x:latest"})
    assert _pushes_an_image({"run": "docker buildx build \\\n  --platform linux/amd64 \\\n  --push ."})
    assert not _pushes_an_image({"uses": "actions/checkout@v4"})
    assert not _pushes_an_image({"run": "docker build -t local ."})


def test_all_four_descriptions_come_from_the_one_readme():
    syncs = [s for s in _steps(_load(README_SYNC)) if _uses(s, "peter-evans/dockerhub-description")]
    repositories = [s.get("with", {}).get("repository") for s in syncs]
    assert sorted(repositories) == sorted(FOUR_NAMES), (
        f"{README_SYNC} writes descriptions for {sorted(repositories)}"
    )
    readmes = {s.get("with", {}).get("readme-filepath") for s in syncs}
    assert readmes == {"./README.md"}, f"descriptions come from {readmes}, not the one README"


def test_no_other_workflow_writes_a_hub_description():
    findings = [
        path.name
        for path in sorted(WORKFLOWS.glob("*.yml"))
        if path.name != README_SYNC
        and any(_uses(s, "peter-evans/dockerhub-description") for s in _steps(_load(path.name)))
    ]
    assert not findings, f"Docker Hub descriptions are also written by: {findings}"


# Docker Hub keeps at most 100 characters of a short description. Measured on
# 2026-09-22 against the Hub API: all four descriptions of that day were cut
# at exactly 100, mid-word ("... 200MB RAM. Perf", "... ARM6").
HUB_SHORT_DESCRIPTION_LIMIT = 100


def test_every_short_description_fits_docker_hub():
    syncs = [s for s in _steps(_load(README_SYNC)) if _uses(s, "peter-evans/dockerhub-description")]
    too_long = {
        s["with"]["repository"]: len(s["with"].get("short-description", ""))
        for s in syncs
        if len(s.get("with", {}).get("short-description", "")) > HUB_SHORT_DESCRIPTION_LIMIT
    }
    assert syncs and not too_long, f"Docker Hub would cut these mid-word: {too_long}"


# The three platform repositories on GitHub are archived after the first
# release that fills all four Hub names from here. A link to one of them then
# sends a reader to frozen code and to a `git clone` of a copy nobody updates.
PLATFORM_REPO_LINK = re.compile(
    r"github\.com/DockerDiscordControl/DockerDiscordControl-(Linux|Mac|Windows)",
    re.IGNORECASE,
)

# An allow-list, not a deny-list: what a reader or a page can follow. git is
# not in the test image, so this walks the tree instead of `git ls-files`.
DOCUMENT_SUFFIXES = {".md", ".html", ".htm", ".xml", ".yml", ".yaml", ".txt", ".py", ".sh", ".json", ".js"}
NOT_SHIPPED = {".git", "tests", "config", "logs", "node_modules", "__pycache__", ".pytest_cache"}


def _documents():
    for path in PROJECT.rglob("*"):
        relative = path.relative_to(PROJECT)
        if relative.parts[0] in NOT_SHIPPED or relative.parts[0].startswith("cached_"):
            continue
        if path.suffix.lower() in DOCUMENT_SUFFIXES and path.is_file():
            yield str(relative), path.read_text(encoding="utf-8", errors="replace")


def test_the_scan_sees_the_readme():
    """Guard against a blunt tool: a scan that reads nothing finds no links."""
    names = {name for name, _ in _documents()}
    assert "README.md" in names and len(names) > 100, len(names)


def test_nothing_links_to_the_platform_repositories():
    findings = [
        f"{name}:{lineno}"
        for name, text in _documents()
        for lineno, line in enumerate(text.splitlines(), 1)
        if PLATFORM_REPO_LINK.search(line)
    ]
    assert not findings, (
        f"{len(findings)} links point to platform repositories that get archived:\n"
        + "\n".join(findings)
    )
