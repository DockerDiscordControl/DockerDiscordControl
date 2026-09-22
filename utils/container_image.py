# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""The image a container runs, read without asking Docker a second time.

``container.image`` in docker-py is not a stored field. It sends
``GET /images/<id>/json``, and when the image a container was created from has
been removed from the host the daemon answers 404 and docker-py raises
``ImageNotFound``. That happens in ordinary operation: an update that recreates
a container, a ``docker image prune``, the containerd image store.

DDC read ``container.image`` in three places, and one container with a removed
image emptied the web panel's container list, reported a running container as
nonexistent in Discord, and dropped it from the bot's list (review E53, a user
report against v2.3.1).

None of them needed the lookup: the reference the container was created with
is already in ``attrs['Config']['Image']``, delivered with the container
itself. Reading it there cannot fail this way, and it saves one API call per
container per refresh.

No imports on purpose - this is called from the web panel, the status service
and the Docker utilities, and must not pull any of them into the others.
"""

_ID_PREFIX = "sha256:"
_SHORT_ID = 12


def _short(image_id: str) -> str:
    if image_id.startswith(_ID_PREFIX):
        image_id = image_id[len(_ID_PREFIX):]
    return image_id[:_SHORT_ID]


def image_name_of(container) -> str:
    """Name of the image ``container`` was created from, e.g.
    ``ich777/steamcmd:valheim``.

    Falls back to the first twelve characters of the image id - what the old
    code showed for an untagged image - when the container was created from a
    bare id or carries no config.
    """
    attrs = getattr(container, "attrs", None) or {}
    reference = (attrs.get("Config") or {}).get("Image") or ""
    if reference and not reference.startswith(_ID_PREFIX):
        return reference
    return _short(reference or attrs.get("Image") or "")


COMPOSE_PROJECT_LABEL = "com.docker.compose.project"


def compose_project_of(container):
    """The Compose stack ``container`` belongs to, or None outside a stack.

    An inspected container carries its labels in ``attrs['Config']['Labels']``,
    a sparse list result at the top level; both come with the container, no
    second request. An empty label is no stack.
    """
    attrs = getattr(container, "attrs", None) or {}
    labels = (attrs.get("Config") or {}).get("Labels") or attrs.get("Labels") or {}
    return labels.get(COMPOSE_PROJECT_LABEL) or None
