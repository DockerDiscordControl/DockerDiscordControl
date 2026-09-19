# -*- coding: utf-8 -*-
"""The configuration directory has ONE source: ``utils/config_paths.py``.

NO ``@covers`` marker: that would be a new guarantee, and guarantees are the
operator's decision.

WHY: ``DDC_CONFIG_DIR`` is documented for users. Every place that derives
``<project>/config`` by itself splits the configuration as soon as the
variable is set - and in the test run (tests/conftest.py sets it) it points to
the REAL config/ (SPEC.md Z2). Six places had each copied the rule themselves,
in three versions (with and without ``strip()``, one with a fixed
``/app/config`` as default).

A RATCHET, NOT A BAN IN ONE GO: the conversion proceeds by subject area, each
as a finding with its own behaviour test. Until then ``STILL_OPEN`` lists the
places that deviate today, per file. The contract fires when a NEW derivation
is added - AND when a converted one is still on the list. So the list can only
shrink, and it does not lie.

THE SCANNER'S LIMIT, explicitly: it recognises the forms that occur in the
code today (``x / "config"``, ``"/app/config"``, ``Path("config")``,
``join(..., "config")``, relative ``"config/..."``, own reads of
``DDC_CONFIG_DIR``). A derivation in a new form (for instance via a composed
string) would go unseen. It skips comment lines. The first version missed the
relative ``"config/..."`` paths - three places that only a second, broader
search found.
"""

import re
from pathlib import Path

import pytest

from utils import config_paths

PROJECT = Path(__file__).resolve().parents[2]
DIRECTORIES = ("cogs", "services", "app", "utils")
SOURCE = "utils/config_paths.py"

PATTERNS = (
    re.compile(r"""/\s*['"]config['"]"""),               # x / "config"
    re.compile(r"""['"]/app/config"""),                   # "/app/config..."
    re.compile(r"""Path\(\s*['"]config['"]\s*\)"""),      # Path("config")
    re.compile(r"""join\([^)]*['"]config['"]"""),         # os.path.join(..., "config"
    re.compile(r"""['"]config/"""),                       # "config/x.json"
    re.compile(r"""DDC_CONFIG_DIR['"]"""),                # own copy of the rule
)

# File -> number of lines still deviating. EMPTY since 2026-09-19: the last
# entries were six copies of the rule (config_service, app/web/config,
# container_status_service, game_query_support_service, mech_reset_service,
# progress_service) and one log line in app/utils/web_helpers.py - all without
# user impact, but each a place where the rule could drift apart again
# (container_status_service took a variable made of spaces literally).
STILL_OPEN = {}


def _matches(line: str) -> bool:
    return not line.lstrip().startswith("#") and any(m.search(line) for m in PATTERNS)


def _found() -> dict:
    result = {}
    for directory in DIRECTORIES:
        for path in sorted((PROJECT / directory).rglob("*.py")):
            name = path.relative_to(PROJECT).as_posix()
            if name == SOURCE:
                continue
            count = sum(1 for z in path.read_text(encoding="utf-8", errors="replace").splitlines()
                        if _matches(z))
            if count:
                result[name] = count
    return result


@pytest.mark.parametrize("line", [
    'base = Path(__file__).parents[2] / "config"',
    "d = base_dir / 'config' / 'admins.json'",
    'NOTIFICATION_DIR = "/app/config"',
    'CONFIG_DIR = Path("config")',
    "p = os.path.join(root, 'config', 'x.json')",
    "p = Path('config/containers')",
    "env = os.environ.get('DDC_CONFIG_DIR', '')",
])
def test_the_scanner_recognises_every_known_form(line):
    """Safeguard against a blunt tool - one example per form."""
    assert _matches(line), line


@pytest.mark.parametrize("line", [
    'containers_dir = get_config_dir() / "containers"',
    "# base_dir / 'config' in a comment",
    'config = load_config()',
])
def test_the_scanner_does_not_fire_blindly(line):
    assert not _matches(line), line


def test_no_new_derivation_and_the_list_does_not_lie():
    found = _found()
    new = {k: v for k, v in found.items() if v > STILL_OPEN.get(k, 0)}
    done = {k: (v, found.get(k, 0)) for k, v in STILL_OPEN.items() if found.get(k, 0) < v}
    assert not new, (
        "New own derivation of the configuration directory - please use "
        f"utils.config_paths.get_config_dir(): {new}"
    )
    assert not done, (
        "These files derive fewer paths themselves than STILL_OPEN says - "
        f"update the list (expected, actual): {done}"
    )


def test_the_source_accepts_its_own_environment(tmp_path, monkeypatch):
    """app/web/config.build_config reads from a PASSED env mapping, not from
    os.environ - the source must support that, otherwise the conversion would
    silently change the meaning of build_config. The signature first, so that
    its absence shows up as a failure and not as a TypeError."""
    import inspect
    assert "environ" in inspect.signature(config_paths.get_config_dir).parameters
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path / "process"))
    assert config_paths.get_config_dir(environ={"DDC_CONFIG_DIR": str(tmp_path / "own")}) == tmp_path / "own"
    assert config_paths.get_config_dir(environ={}) == PROJECT / "config"


def test_the_source_follows_the_variable(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    assert config_paths.get_config_dir() == tmp_path


def test_the_source_reads_the_variable_on_every_call(tmp_path, monkeypatch):
    """Not at import: a service built AFTER a change must see it."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path / "a"))
    config_paths.get_config_dir()
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path / "b"))
    assert config_paths.get_config_dir() == tmp_path / "b"


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_means_default(monkeypatch, value):
    """Empty or only spaces: the default - as in five of the six old copies
    (container_status_service took an empty variable literally)."""
    monkeypatch.setenv("DDC_CONFIG_DIR", value)
    assert config_paths.get_config_dir() == PROJECT / "config"


def test_without_variable_the_project_config_applies(monkeypatch):
    """In the container that is /app/config - the same as every old derivation."""
    monkeypatch.delenv("DDC_CONFIG_DIR", raising=False)
    assert config_paths.get_config_dir() == PROJECT / "config"
