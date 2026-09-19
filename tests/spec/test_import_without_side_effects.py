# -*- coding: utf-8 -*-
"""An ``import`` must not read any configuration from disk.

NO ``@covers`` marker, and that on purpose: that would be a new guarantee, and
the guarantees are the operator's decision, not mine. If this is to become
Z11, the marker follows.

WHERE THE FINDING COMES FROM (stage 3, 2026-09-17): when running each of the 127
test files on its own, two tests in ``test_r2_g5_mech.py`` failed as soon as
they ran alone - not on their own assertion, but already at the ``import`` in
line 1. ``docker_utils.py:76-80`` calls ``_load_timeout_from_config(...)`` five
times AT MODULE LEVEL, and each of these calls calls ``load_config()``. A sixth
case sits at ``:676`` (``_CACHE_TTL``).

Why this is more than a question of style:

1. An import reads the disk. If the read fails - permissions, missing
   directory, broken file - it is not a function that fails but the
   IMPORT, and that as an ``ImportError`` deep in a nine-level chain instead
   of an understandable message.
2. The safety net there catches ``(ConfigLoadError, KeyError, ValueError,
   TypeError)``. An ``AttributeError`` demonstrably slipped through.
3. The moment of loading depends on who happens to import first.
   Exactly that made the two tests above order-dependent.

WHY IN A SEPARATE PROCESS: the obvious way would be ``importlib.reload``.
That would rebuild the module world of this test run and thereby create
exactly the order dependency that is to be eliminated here. A separate
process has a fresh ``sys.modules`` and leaves nothing behind.

COUNTER-CHECK (carried out 2026-09-17), in three steps - two of them mistakes
of mine, and both belong here:

*First run, before the fix:* red, with exactly the right reason in the
stack - ``services/docker_service/__init__.py:10`` -> ``docker_utils.py:76``
-> ``:57 config = load_config()`` -> ``AssertionError: IMPORT READ
CONFIGURATION``. The guard ``GUARD_ALREADY_LOADED`` did NOT fire, so the module
really was still unloaded and the test checks something.

*Second run, after the fix in the production code:* still red - but the
stack showed ``File "<string>", line 27``, i.e. the CHECK LOOP of this test.
The import had long been running through silently; what failed was the access
to the lazy values, because the stub was still in place. An access SHOULD read
configuration, that is the point of the change. The test measured itself
broken. Fixed by restoring ``load_config`` before the check loop.

*At the same time 23 red tests* in ``tests/unit/services/docker_service``:
``NameError`` on ``CONTAINER_TYPE_PATTERNS`` and ``DEFAULT_TIMEOUT_CONFIG``. I
had named the trap - a module-level ``__getattr__`` does not serve free names
in a function body - and then converted only the five timeout values, forgetting
the two dictionaries. My guard grep likewise searched only for the five
names and reported completion. The second version extracts the lazy names via
AST from ``_TIMEOUT_SPECS`` and ``_LAZY_BUILDERS`` - i.e. from the code instead
of from my enumeration - and promptly found ``_CACHE_TTL`` too.

*Third run:* import test green, ``tests/unit/services/docker_service`` back to
86 green.

EVIDENCE OF EFFECT, and it is stronger than a mutation:
``tests/unit/audit_2026_09/test_r2_g5_mech.py`` failed ALONE with 2 of 41.
After the fix: 41 green, **without a single test being touched**.
The order dependency has disappeared because its cause is gone.

WHAT THIS DOES NOT PROVE: this test checks ONE module, not the project.
``services/mech/progress_service.py:125`` still reads at import time
(``CFG = load_config()``) - deliberately left alone, because five test files
assign ``progress_service.CFG`` from outside, which makes it de facto an
interface. Whoever wants to extend this guarantee to the whole project must
first decide there what happens to that interface.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]

# Return codes of the subprocess
OK = 0
GUARD_ALREADY_LOADED = 3
GUARD_NOT_FLOAT = 4


def _run(module: str) -> subprocess.CompletedProcess:
    """Import ``module`` in a fresh process in which load_config raises.

    The watchdog is the sabotage itself: ``load_config`` raises an
    ``AssertionError``. That is in NONE of the exceptions caught by
    ``_load_timeout_from_config`` - so the test measures whether the call
    TAKES PLACE, not merely whether its result is handled.
    """
    script = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(PROJECT)!r})

        import services.config.config_service as cs

        # Guard against a blunt tool: if the target module is already loaded
        # before we sabotage, the import below can no longer trigger anything and
        # the test would be green without proving anything.
        if {module!r} in sys.modules:
            sys.exit({GUARD_ALREADY_LOADED})

        def _raise(*_a, **_k):
            raise AssertionError("IMPORT READ CONFIGURATION")

        _real_load_config = cs.load_config
        cs.load_config = _raise

        import importlib
        module = importlib.import_module({module!r})

        # UNDO the sabotage before the values are touched.
        # Without this the test measures itself broken: an access to one of the
        # lazy values SHOULD read configuration - that is the whole point of the
        # change. The first version left the stub in place and therefore failed
        # on its own check loop, although the import had long run through
        # silently. What is checked is the IMPORT, not the access.
        cs.load_config = _real_load_config

        # The values must still be there and be floats - otherwise the import
        # would be silent, but the module unusable. Three existing tests in
        # tests/unit/services/docker_service/ pin exactly that down.
        for name in ("DEFAULT_FAST_STATS_TIMEOUT", "DEFAULT_SLOW_STATS_TIMEOUT",
                     "DEFAULT_FAST_INFO_TIMEOUT", "DEFAULT_SLOW_INFO_TIMEOUT",
                     "DEFAULT_CONTAINER_LIST_TIMEOUT"):
            if not isinstance(getattr(module, name, None), float):
                sys.exit({GUARD_NOT_FLOAT})

        sys.exit({OK})
        """
    )
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=120, cwd=str(PROJECT),
    )


def test_docker_utils_reads_no_configuration_on_import():
    """``import services.docker_service.docker_utils`` does not touch the disk."""
    result = _run("services.docker_service.docker_utils")

    assert result.returncode != GUARD_ALREADY_LOADED, (
        "The module was already loaded before the stub was set - then this "
        "test checks nothing. Probably services/__init__.py already pulls it in."
    )
    assert result.returncode != GUARD_NOT_FLOAT, (
        "The import did stay silent, but the timeout values are no longer floats - "
        "that would make the module unusable."
    )
    assert result.returncode == OK, (
        "The import read configuration from disk.\n"
        "An import should do nothing: if the read fails, it is not a "
        "function that fails but the import - as an ImportError deep in the chain.\n"
        f"--- stderr ---\n{result.stderr[-2000:]}"
    )
