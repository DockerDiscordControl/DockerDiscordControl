# -*- coding: utf-8 -*-
"""The web panel's container list costs one Docker request per refresh.

MEASURED ON THE OPERATOR'S HOST (2026-09-28): the web panel's background worker
refreshes its container list every 30 seconds, whether or not anyone has the
panel open. It called docker-py's ``containers.list(all=True)``, which answers
the list request and then INSPECTS EVERY CONTAINER AGAIN, one request each -
1 + 37 requests every 30 seconds. The cache keeps five fields per container
(id, name, status, image, stack), and the list answer carries all five.

It reads that one answer now. The one field the list does not always answer
like the inspect is the image name: once a container's tag has moved on (a
pull without recreating it), the list names the image by its id. Measured: 1 of
37 (verwaltli-api-old). Only such a container is inspected, so the panel shows
the same names as before - checked live against the old way for all 37.

COUNTER-CHECK (2026-09-28): with containers.list(all=True) back in
update_docker_cache, the one-request case went red; with the moved-tag lookup
removed, the moved-tag case did.
"""

import logging
from types import SimpleNamespace

import pytest

from app.utils import web_helpers as wh

ROWS = [
    {"Id": "a" * 64, "Names": ["/Valheim"], "State": "running", "Image": "ich777/steamcmd:valheim",
     "ImageID": "sha256:1", "Labels": {}},
    {"Id": "b" * 64, "Names": ["/szr-api"], "State": "running", "Image": "szr-api",
     "ImageID": "sha256:2", "Labels": {"com.docker.compose.project": "szr"}},
    # The tag moved on after a pull: the list names the image by its id
    {"Id": "c" * 64, "Names": ["/verwaltli-api-old"], "State": "exited",
     "Image": "sha256:387d403f61dd9cf2e165d23e1b3fe87c3faff2d3516fe319fe4a7b3f4c7cc45e",
     "ImageID": "sha256:387d403f61dd9cf2e165d23e1b3fe87c3faff2d3516fe319fe4a7b3f4c7cc45e", "Labels": {}},
]


class _Client:
    def __init__(self):
        self.requests = []
        self.api = SimpleNamespace(containers=self._list, inspect_container=self._inspect)
        self.containers = SimpleNamespace(list=self._full_list)

    def _list(self, all=False):
        self.requests.append("list")
        return [dict(row) for row in ROWS]

    def _inspect(self, container_id):
        self.requests.append(f"inspect {container_id[:1]}")
        return {"Config": {"Image": "verwaltli-api"}}

    def _full_list(self, all=False):
        raise AssertionError("containers.list(all=True) inspects every container again")

    def close(self):
        pass


@pytest.fixture
def refreshed(monkeypatch):
    fresh = {'global_timestamp': None, 'containers': [], 'error': None, 'container_timestamps': {},
             'container_hashes': {}, 'bg_refresh_running': False, 'priority_containers': set(),
             'last_cleanup': None, 'access_count': 0}
    monkeypatch.setattr(wh, "docker_cache", fresh)
    client = _Client()
    monkeypatch.setattr("services.docker_service.client_factory.build_docker_client", lambda **kw: client)
    wh.update_docker_cache(logging.getLogger("test"))
    return client, {c["name"]: c for c in fresh["containers"]}


def test_one_request_for_the_list(refreshed):
    client, containers = refreshed
    assert client.requests.count("list") == 1
    assert [r for r in client.requests if r.startswith("inspect")] == ["inspect c"], \
        "a container whose list entry was complete was inspected anyway"
    assert set(containers) == {"Valheim", "szr-api", "verwaltli-api-old"}


def test_the_five_fields_come_from_the_list(refreshed):
    _, containers = refreshed
    assert containers["szr-api"] == {"id": "b" * 12, "name": "szr-api", "status": "running",
                                     "image": "szr-api", "compose_project": "szr"}


def test_a_moved_tag_still_shows_the_image_name(refreshed):
    _, containers = refreshed
    assert containers["verwaltli-api-old"]["image"] == "verwaltli-api"
