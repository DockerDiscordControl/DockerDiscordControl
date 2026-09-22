# -*- coding: utf-8 -*-
"""The low-level container listing is called the way docker-py declares it.

THE FINDING (review C56, section 16 F3): ``get_containers_data()`` called
``client.api.containers(all=True, Lstat=True)``. docker-py's low-level
``APIClient.containers`` has a fixed signature and no ``**kwargs``, and there
is no ``Lstat`` parameter in it - in the pinned 7.1.0 the parameters are
(quiet, all, trunc, latest, since, before, limit, size, filters). The call
therefore raised ``TypeError: containers() got an unexpected keyword
argument 'Lstat'`` every single time, and the except clause of the function
named (DockerException, TimeoutError, OSError, RuntimeError), so the error
did not even come back as the documented empty list - it left the function.

The existing tests never saw it: they hand in a Mock for ``client.api``,
and a Mock accepts every keyword there is. This test asks the real docker-py
instead.
"""

import inspect

import pytest

from docker.api.container import ContainerApiMixin

from services.docker_service import docker_utils


def _listing_call_kwargs():
    """The keywords `get_containers_data` passes to `client.api.containers`."""
    source = inspect.getsource(docker_utils.get_containers_data)
    line = next(ln for ln in source.splitlines() if "client.api.containers" in ln)
    args = line.split("client.api.containers", 1)[1]
    return {part.split("=")[0].strip() for part in args.split(",")[1:]
            if "=" in part and not part.strip().startswith(")")}


def test_every_keyword_exists_in_docker_py():
    accepted = set(inspect.signature(ContainerApiMixin.containers).parameters)
    passed = _listing_call_kwargs()

    assert passed, "the call could not be read - the test has lost its subject"
    assert passed <= accepted, (
        f"docker-py does not know {sorted(passed - accepted)}; the call raises "
        f"TypeError on every container listing"
    )


def test_the_signature_has_no_catch_all():
    """Without this, a **kwargs in docker-py would make the test above hollow."""
    kinds = {p.kind for p in
             inspect.signature(ContainerApiMixin.containers).parameters.values()}

    assert inspect.Parameter.VAR_KEYWORD not in kinds


@pytest.mark.asyncio
async def test_a_listing_against_the_real_signature_comes_back(monkeypatch):
    """The same question once more, through the function itself."""
    class _Api:
        def containers(self, quiet=False, all=False, trunc=False, latest=False,
                       since=None, before=None, limit=-1, size=False, filters=None):
            running = {"Id": "abcdef123456", "Names": ["/web"], "State": "running",
                       "Image": "nginx", "Created": 0}
            stopped = {"Id": "fedcba654321", "Names": ["/db"], "State": "exited",
                       "Image": "postgres", "Created": 0}
            # Docker itself hands out the stopped ones only when asked.
            return [running, stopped] if all else [running]

    class _Client:
        api = _Api()

    class _Ctx:
        async def __aenter__(self):
            return _Client()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(docker_utils, "get_docker_client_async", lambda **kw: _Ctx())
    monkeypatch.setattr(docker_utils, "_containers_cache", None)
    monkeypatch.setattr(docker_utils, "_cache_timestamp", 0)

    result = await docker_utils.get_containers_data()

    # Sorted by name, and a stopped container belongs in the list: the callers
    # of this function build their container list from it (found by mutation M3
    # of review C56).
    assert [c["name"] for c in result] == ["db", "web"]
    assert result[1]["status"] == "running", result[1]
    assert "error" not in result[1], (
        f"a perfectly normal running container came back as a processing error: {result[1]}"
    )
