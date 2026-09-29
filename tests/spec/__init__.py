# -*- coding: utf-8 -*-
"""Tests mapped to the guarantees in SPEC.md.

Each file carries a marker ``# @covers Zn`` at its top and checks exactly what
the guarantee promises - not the implementation that fulfils it today.
"""


def is_not_awaitable_error(error):
    """True if ``error`` is the TypeError of awaiting a non-awaitable (a MagicMock).

    Several tests let a callback run into cog methods on a MagicMock AFTER the
    part they check, and swallow exactly this error. Its wording depends on the
    Python version: 3.14 says "'MagicMock' object can't be awaited", 3.10 says
    "object MagicMock can't be used in 'await' expression". The tests used to
    match only the first, so on CI (Python 3.10) they re-raised it and failed
    - seven red tests on the first develop push of 2026-09-19, while the Unraid
    runtime (3.14) was green. One place for the rule, so the copies cannot
    drift apart again.
    """
    text = str(error)
    return isinstance(error, TypeError) and (
        "can't be awaited" in text or "can't be used in 'await' expression" in text
    )


class _RaisingRow(dict):
    """A list row whose reading fails - a daemon answer that breaks mid-refresh."""

    def __init__(self, error):
        super().__init__()
        self._error = error

    def get(self, *args, **kwargs):
        raise self._error


def listed_rows(containers):
    """docker-py-like fake containers as the rows of GET /containers/json.

    Since 2026-09-28 the web panel's cache reads that one list answer instead of
    containers.list(all=True), which inspected every container again (1 + 37
    requests every 30 s on the operator's host). The fakes the tests had keep
    working through this: a fake whose status raises becomes a row whose
    reading raises, so "it broke mid-refresh" still breaks mid-refresh.
    """
    rows = []
    for container in containers:
        try:
            status = container.status
        except Exception as error:  # noqa: BLE001 - whatever the fake raises
            rows.append(_RaisingRow(error))
            continue
        attrs = container.attrs if isinstance(getattr(container, "attrs", None), dict) else {}
        config = attrs.get("Config") or {}
        rows.append({"Id": container.id, "Names": ["/" + container.name], "State": status,
                     "Image": config.get("Image") or attrs.get("Image") or "",
                     "ImageID": attrs.get("Image") or "",
                     "Labels": config.get("Labels") or attrs.get("Labels") or {}})
    return rows


# cogs/control_ui.py was split on 2026-09-28: the admin picker went to
# admin_ui.py, the mech panel to mech_ui.py. A test that read control_ui.py's
# source for a pattern - or for its ABSENCE - would now look at a third of the
# code and pass for the wrong reason. They read all three.
CONTROL_UI_FILES = ("cogs/control_ui.py", "cogs/admin_ui.py", "cogs/mech_ui.py")


def control_ui_source():
    """The source of the control UI as it was one file: control_ui, admin_ui, mech_ui."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    return "\n\n".join((root / name).read_text(encoding="utf-8") for name in CONTROL_UI_FILES)


def configured_as_drawn(monkeypatch, module, allowed=("start", "stop", "restart")):
    """The current configuration answers for every container with ``allowed``.

    ActionButton asks the CURRENT configuration at the press since the stage 4
    review before v3.1.0 (section 02); tests that draw a button for a container
    the test config does not hold state here what the configuration allows.
    """
    from types import SimpleNamespace
    monkeypatch.setattr(module, "get_server_config_service", lambda: SimpleNamespace(
        get_server_by_docker_name=lambda name: {"docker_name": name,
                                                "allowed_actions": list(allowed)}))



def docker_agrees_with_the_cache(monkeypatch):
    """The bulk actions' fresh Docker read answers what the test's status cache says.

    Restart All / Stop All ask Docker again before acting on a container the
    cache calls running (stage 4 review before v3.1.0, section 01). Tests that
    describe the containers through the cache alone state here that Docker
    agrees with it; test_restart_all_asks_docker_before_it_acts.py covers the
    case where it does not.
    """
    import cogs.admin_overview as ao

    async def _as_cached(docker_name):
        entry = ao.get_status_cache_service().get(docker_name)
        data = (entry or {}).get("data")
        return getattr(data, "is_running", None) if data is not None else None
    monkeypatch.setattr(ao, "_running_now", _as_cached)
