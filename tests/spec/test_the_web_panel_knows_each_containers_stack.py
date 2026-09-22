# -*- coding: utf-8 -*-
"""The web panel's container list knows each container's Compose stack (Phase 4c, part 1).

Sorting the server order by stack - the handwork Phase 4c replaces - needs the
stack in the panel. Compose writes it as the label com.docker.compose.project.
docker-py's containers.list(all=True) inspects each container, so the label
is in attrs['Config']['Labels']; a sparse list result carries it as the
top-level 'Labels' instead. Both are read, no second request is made, and a
container outside any stack has no project (None), not an empty string that
would group all of them into one nameless stack.

COUNTER-CHECK (2026-09-22): red before - the cache entry had no
'compose_project' key.
"""

import logging

from utils.container_image import compose_project_of

LABEL = "com.docker.compose.project"


class _Container:
    def __init__(self, name, attrs):
        self.id = f"{name}-0123456789abcdef"
        self.name = name
        self.status = "running"
        self.attrs = attrs

    @property
    def image(self):  # a second request - must not be needed
        raise AssertionError("container.image was read")


def test_the_project_is_read_from_the_inspected_labels():
    c = _Container("web", {"Config": {"Image": "nginx", "Labels": {LABEL: "blog"}}})
    assert compose_project_of(c) == "blog"


def test_a_sparse_list_result_carries_the_labels_at_the_top():
    c = _Container("web", {"Image": "nginx", "Labels": {LABEL: "blog"}})
    assert compose_project_of(c) == "blog"


def test_outside_a_stack_there_is_no_project():
    assert compose_project_of(_Container("a", {"Config": {"Labels": {}}})) is None
    assert compose_project_of(_Container("b", {"Config": {"Labels": {LABEL: ""}}})) is None
    assert compose_project_of(_Container("c", {"Config": {"Labels": None}})) is None
    assert compose_project_of(_Container("d", {})) is None


class _Client:
    def __init__(self, containers):
        self.containers = self
        self._containers = containers

    def list(self, all=False):
        return list(self._containers)

    def close(self):
        pass


def test_the_cache_entry_names_the_stack(monkeypatch):
    import app.utils.web_helpers as wh

    containers = [_Container("web", {"Config": {"Image": "nginx", "Labels": {LABEL: "blog"}}}),
                  _Container("solo", {"Config": {"Image": "redis", "Labels": {}}})]
    monkeypatch.setattr("services.docker_service.client_factory.build_docker_client",
                        lambda **kw: _Client(containers))
    with wh.cache_lock:
        wh.docker_cache["containers"] = []
        wh.docker_cache["error"] = None
    wh.update_docker_cache(logging.getLogger("test"))
    stacks = {c["name"]: c["compose_project"] for c in wh.docker_cache["containers"]}
    assert stacks == {"web": "blog", "solo": None}
