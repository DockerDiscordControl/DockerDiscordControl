# -*- coding: utf-8 -*-
"""Importing one service must not import all of them.

THE FINDING (review E31, services/__init__.py): the package's ``__init__``
imported five services eagerly and re-exported them:

    from .infrastructure.container_info_service import get_container_info_service
    from .infrastructure.action_log_service import get_action_log_service
    from .infrastructure.spam_protection_service import get_spam_protection_service
    from .config.config_service import get_config_service
    from .mech.mech_service import get_mech_service

so ``import services.config.config_service`` - or anything else under
``services`` - ran all five first.

Measured in the running container:

    import services : 1199 ms, 23 modules pulled in

and measured in the source tree: **nothing uses the re-exports.** Not one
``from services import ...``, not one ``services.get_config_service(...)``, not
one bare ``import services``. Every caller imports the module it wants
directly.

Two things that cost nothing to keep and something to have:

1. **1.2 seconds** of every start, for names nobody asks for.
2. **Coupling.** An ImportError anywhere in those five - a syntax error in the
   mech service, a missing dependency - made ``services.config.config_service``
   unimportable too. A mech problem becoming a configuration problem is the
   same sentence as reviews E8 and E12, one layer down.

It is also why ``tests/unit/app_modules/test_utils_and_bot.py`` has to replace
the whole ``services`` package with stubs to test anything.

The ``sys.path`` setup stays: it is load-bearing and has nothing to do with
this.
"""

import subprocess
import sys
import textwrap

import pytest

PROJECT = __file__.rsplit("/tests/", 1)[0]


def _in_a_fresh_interpreter(code: str) -> str:
    """Import side effects can only be measured before anything is imported."""
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=PROJECT, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, f"the probe itself failed:\n{result.stderr}"
    # The services write log lines to stdout while they initialise, so the
    # answer is the LAST line, not the whole of it.
    lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
    assert lines, f"the probe printed nothing:\n{result.stderr}"
    return lines[-1].strip()


def test_importing_the_package_does_not_import_the_mech():
    output = _in_a_fresh_interpreter("""
        import sys
        import services
        print("mech" if any(m.startswith("services.mech") for m in sys.modules) else "clean")
    """)

    assert output == "clean", (
        "importing the services package pulled in the mech service; an "
        "ImportError there would make services.config unimportable too"
    )


def test_importing_the_package_is_cheap():
    output = _in_a_fresh_interpreter("""
        import sys
        import services
        print(len([m for m in sys.modules if m.startswith("services.")]))
    """)

    assert int(output) <= 3, (
        f"importing the services package pulled in {output} submodules; it was "
        f"23 before, costing 1.2 s of every start for re-exports nobody uses"
    )


def test_a_single_service_can_still_be_imported():
    """Counter-check: the package must still work as a package."""
    output = _in_a_fresh_interpreter("""
        from services.config.config_service import get_config_service
        print("ok" if callable(get_config_service) else "broken")
    """)

    assert output == "ok"


def test_the_path_setup_is_still_there():
    """Counter-check: sys.path is load-bearing and must not be swept away."""
    source = open(f"{PROJECT}/services/__init__.py", encoding="utf-8").read()
    assert "sys.path.insert" in source, (
        "the sys.path setup was removed along with the re-exports; it is a "
        "different thing and other imports depend on it"
    )
