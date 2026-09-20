# -*- coding: utf-8 -*-
"""The Docker client's safety net can actually be entered.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage C, section 16 F1, re-checked 2026-09-20):
``get_docker_client_async`` hands back a context manager while the connection
pool is available, and otherwise falls back to building a client of its own.
The fallback ends with ``return individual_client`` - the decorated FUNCTION,
not a call of it. Every caller writes ``async with
get_docker_client_async(...)``, so on the fallback path they get a function
object and the ``async with`` raises AttributeError instead of giving them a
client.

The safety net is supposed to catch exactly the moment the pool is gone -
the moment nothing else works either.
"""

from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest

import services.docker_service.docker_utils as docker_utils


@pytest.mark.asyncio
async def test_the_pool_path_gives_a_context_manager():
    """Premise: with the pool available the caller can enter it."""
    client = MagicMock()

    @asynccontextmanager
    async def pooled(*args, **kwargs):
        yield client

    with patch.object(docker_utils, "USE_CONNECTION_POOL", True), \
         patch("services.docker_service.docker_client_pool.get_docker_client_async", pooled):
        async with docker_utils.get_docker_client_async(operation="test") as entered:
            assert entered is client


@pytest.mark.asyncio
async def test_the_fallback_gives_a_context_manager_too():
    client = MagicMock()

    with patch.object(docker_utils, "USE_CONNECTION_POOL", False), \
         patch.object(docker_utils.docker, "from_env", return_value=client):
        async with docker_utils.get_docker_client_async(operation="test") as entered:
            assert entered is client, "the fallback did not hand out a client"


@pytest.mark.asyncio
async def test_the_fallback_closes_the_client_again():
    """Counter-check: the safety net must not leak the client it opened."""
    client = MagicMock()

    with patch.object(docker_utils, "USE_CONNECTION_POOL", False), \
         patch.object(docker_utils.docker, "from_env", return_value=client):
        async with docker_utils.get_docker_client_async(operation="test"):
            pass

    assert client.close.called
