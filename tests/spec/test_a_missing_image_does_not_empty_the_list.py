# -*- coding: utf-8 -*-
"""
THE FINDING (review E53, reported by a user on GitHub 2026-09-22 against
v2.3.1): "app was working fine then all of a sudden there is no servers in my
discord channel. log into the app and there is no dockers to select, clicking
refresh just errors."

    ERROR in web_helpers: Docker connection error during live query:
    404 Client Error for http+docker://localhost/v1.47/images/6afa95.../json:
    Not Found ("No such image: sha256:6afa95...")

`container.image` is not a stored field. docker-py resolves it with an extra
request - `GET /images/<id>/json` - and when the image a container was created
from is gone, the daemon answers 404 and docker-py raises `ImageNotFound`.
Images disappear under containers in ordinary operation: an update that
recreates a container, a `docker image prune`, the containerd image store.

Three places read it, and one bad container did something different to each:

    app/utils/web_helpers.py            update_docker_cache
        the 404 left the loop, so the WHOLE refresh failed - every time,
        because the image stays gone. One container emptied the web panel's
        list. That is the reporter's log line.

    services/infrastructure/container_status_service.py  _query_container_sync
        `ImageNotFound` is a `NotFound`, so the outer handler reported the
        container as "container_not_found" - a running container, declared
        nonexistent, which is review C18's sentence in another file.

    services/docker_service/docker_utils.py  list_docker_containers
        caught the NotFound and `continue`d: the container silently dropped
        out of the list.

None of them needed the lookup. The image reference the container was created
with is already in `container.attrs['Config']['Image']`, delivered with the
container itself. Reading it there cannot 404, and it is one API call fewer
per container per refresh.

The fake below behaves like docker-py: `.image` answers for a container whose
image exists and raises `ImageNotFound` for one whose image is gone. So the
only thing wrong in these tests is the one thing that was wrong on the
reporter's host.
"""

import contextlib
import logging
from types import SimpleNamespace

import docker
import pytest


class _Container:
    """A docker-py Container whose image has been removed from the host."""

    def __init__(self, name, *, image_ref="ich777/steamcmd:valheim",
                 image_id="sha256:6afa951ea8ec34384951a28c5bd1f4b4edd459a5315b91dc3f318b55495544af",
                 image_gone=True, status="running"):
        self.id = f"{name}-0123456789abcdef"
        self.short_id = self.id[:10]
        self.name = name
        self.status = status
        self._image_gone = image_gone
        self.attrs = {
            "Image": image_id,
            "Config": {"Image": image_ref},
            "State": {"StartedAt": "2026-09-22T10:00:00.000000000Z"},
            "NetworkSettings": {"Ports": {}},
        }

    @property
    def image(self):
        # What docker-py does: a second request, GET /images/<id>/json.
        if self._image_gone:
            raise docker.errors.ImageNotFound(
                f'No such image: {self.attrs["Image"]}')
        return SimpleNamespace(tags=[self.attrs["Config"]["Image"]],
                               id=self.attrs["Image"])


class _Client:
    def __init__(self, containers):
        self._containers = {c.name: c for c in containers}
        self.containers = self

    def list(self, all=False):
        return list(self._containers.values())

    def get(self, name):
        return self._containers[name]

    def close(self):
        pass


def _three():
    return [_Container("Satisfactory", image_gone=False,
                       image_ref="wolveix/satisfactory-server:latest"),
            _Container("Valheim"),  # <- its image is gone
            _Container("V-Rising", image_gone=False,
                       image_ref="trueosiris/vrising")]


# --------------------------------------------------------------------------- #
# The shared helper
# --------------------------------------------------------------------------- #


def test_the_image_name_comes_from_the_container_itself():
    from utils.container_image import image_name_of

    assert image_name_of(_Container("Valheim")) == "ich777/steamcmd:valheim"


def test_a_container_created_from_a_bare_id_shows_a_short_id():
    """COUNTER-CHECK: the old code showed 12 characters of the id when there
    was no tag. A container created from an id keeps that."""
    from utils.container_image import image_name_of

    c = _Container("x", image_ref="sha256:6afa951ea8ec34384951a28c5bd1f4b4edd4")
    assert image_name_of(c) == "6afa951ea8ec"


def test_a_container_with_no_config_still_has_a_name():
    from utils.container_image import image_name_of

    c = _Container("x")
    c.attrs = {"Image": "sha256:0123456789abcdef0123"}
    assert image_name_of(c) == "0123456789ab"


# --------------------------------------------------------------------------- #
# 1. The web panel's list - the reporter's symptom
# --------------------------------------------------------------------------- #


def test_one_missing_image_does_not_empty_the_web_panel_list(monkeypatch):
    """THE FINDING: one container with a removed image, three containers on
    the host - all three must be in the list."""
    import app.utils.web_helpers as wh

    monkeypatch.setattr("services.docker_service.client_factory.build_docker_client", lambda **kw: _Client(_three()))
    with wh.cache_lock:
        wh.docker_cache["containers"] = []
        wh.docker_cache["error"] = None

    wh.update_docker_cache(logging.getLogger("test"))

    names = sorted(c["name"] for c in wh.docker_cache["containers"])
    assert names == ["Satisfactory", "V-Rising", "Valheim"], (
        f"the web panel list is {names}; one missing image emptied it"
    )
    assert wh.docker_cache["error"] is None
    valheim = next(c for c in wh.docker_cache["containers"] if c["name"] == "Valheim")
    assert valheim["image"] == "ich777/steamcmd:valheim"


# --------------------------------------------------------------------------- #
# 2. The Discord status - a running container declared nonexistent
# --------------------------------------------------------------------------- #


def test_a_running_container_with_a_missing_image_is_not_reported_missing():
    import time

    from services.infrastructure.container_status_service import (
        ContainerStatusRequest,
        get_container_status_service,
    )

    service = get_container_status_service()
    result = service._query_container_sync(
        _Client(_three()),
        ContainerStatusRequest(container_name="Valheim", include_stats=False,
                               include_details=False),
        time.time())

    assert result.success is True, (
        f"Valheim is running and was reported as {result.error_type!r}: "
        f"{result.error_message}"
    )
    assert result.is_running is True
    assert result.image == "ich777/steamcmd:valheim"


# --------------------------------------------------------------------------- #
# 3. The container list the bot uses - a container silently dropped
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_container_with_a_missing_image_stays_in_the_list(monkeypatch):
    import services.docker_service.docker_utils as docker_utils

    @contextlib.asynccontextmanager
    async def fake_client(*_a, **_kw):
        yield _Client(_three())

    monkeypatch.setattr(docker_utils, "get_docker_client_async", fake_client)

    result = await docker_utils.list_docker_containers()

    names = sorted(c["name"] for c in result)
    assert names == ["Satisfactory", "V-Rising", "Valheim"], (
        f"the list is {names}; the container with the missing image fell out"
    )
