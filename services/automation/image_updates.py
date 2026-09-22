# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Is there a newer image for a container's tag? (roadmap Phase 4d)

The registry is asked for the current digest of the tag a container runs,
by HEAD on the manifest - a HEAD does not count against Docker Hub's pull
limit - using the anonymous token flow Docker Hub, ghcr.io and lscr.io share
(401 with a Bearer challenge, a token from its realm, the request again).
That digest is compared with the RepoDigests of the local image, which DDC
reads through the reserved, read-only GET /images/{name}/json of the proxy.

This module only KNOWS; it never pulls. Pulling is POST /images/create, which
the allowlist proxy refuses on purpose. So the only honest reaction to an
update is a notice - "restart on update" would restart the old image.

An unknown remote digest (registry unreachable, private image, no digest
header) is "unknown", never "update".
Test: tests/spec/test_an_image_update_is_detected_from_the_registry_digest.py
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Dict, Optional, Set

logger = logging.getLogger("ddc.image_updates")

DOCKER_HUB = "registry-1.docker.io"
MANIFEST_TYPES = ", ".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])


@dataclass(frozen=True)
class ImageRef:
    registry: str
    repository: str
    tag: str


def parse_image_reference(reference: str) -> Optional[ImageRef]:
    """Normalise like Docker: nginx -> registry-1.docker.io/library/nginx:latest.

    A reference pinned to a digest (name@sha256:...) cannot change and is not
    checked (None), and neither is a bare image id.
    """
    reference = (reference or "").strip()
    if not reference or "@" in reference:
        return None
    # A container created from a bare image id carries the id in Config.Image.
    # Normalised like a name it became library/sha256:<id> and DDC asked Docker
    # Hub about it every six hours, for something that has no tag to follow.
    bare = reference[len("sha256:"):] if reference.startswith("sha256:") else reference
    if len(bare) == 64 and all(c in "0123456789abcdef" for c in bare.lower()):
        return None
    first, _, rest = reference.partition("/")
    if rest and ("." in first or ":" in first or first == "localhost"):
        registry, path = first, rest
    else:
        registry, path = "docker.io", reference
    if registry in ("docker.io", "index.docker.io"):
        registry = DOCKER_HUB
    name, tag = path, "latest"
    last_slash = path.rfind("/")
    colon = path.rfind(":")
    if colon > last_slash:
        name, tag = path[:colon], path[colon + 1:]
    if registry == DOCKER_HUB and "/" not in name:
        name = f"library/{name}"
    return ImageRef(registry, name, tag)


def local_digests(image_attrs: Dict, ref: ImageRef) -> Set[str]:
    """The local image's digests for this repository (RepoDigests is repo@digest)."""
    digests = set()
    for entry in image_attrs.get("RepoDigests") or []:
        repo, _, digest = entry.partition("@")
        parsed = parse_image_reference(repo)
        if digest and parsed and (parsed.registry, parsed.repository) == (ref.registry, ref.repository):
            digests.add(digest)
    return digests


def update_available(remote: Optional[str], local: Set[str]) -> Optional[bool]:
    """True/False when both sides are known, None (unknown) otherwise."""
    if not remote or not local:
        return None
    return remote not in local


def _challenge(header: str) -> Dict[str, str]:
    return dict(re.findall(r'(\w+)="([^"]*)"', header or ""))


async def remote_digest(ref: ImageRef, scheme: str = "https", timeout: float = 15.0) -> Optional[str]:
    """Docker-Content-Digest of the tag's manifest, or None when it cannot be known."""
    import aiohttp

    url = f"{scheme}://{ref.registry}/v2/{ref.repository}/manifests/{ref.tag}"
    headers = {"Accept": MANIFEST_TYPES}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.head(url, headers=headers, allow_redirects=True) as answer:
                if answer.status == 401:
                    challenge = _challenge(answer.headers.get("WWW-Authenticate", ""))
                else:
                    return answer.headers.get("Docker-Content-Digest") if answer.status == 200 else None
            realm = challenge.get("realm")
            if not realm:
                return None
            params = {k: v for k, v in challenge.items() if k in ("service", "scope")}
            params.setdefault("scope", f"repository:{ref.repository}:pull")
            async with session.get(realm, params=params) as token_answer:
                if token_answer.status != 200:
                    return None
                data = await token_answer.json(content_type=None)
            token = data.get("token") or data.get("access_token")
            if not token:
                return None
            headers["Authorization"] = f"Bearer {token}"
            async with session.head(url, headers=headers, allow_redirects=True) as answer:
                if answer.status != 200:
                    return None
                return answer.headers.get("Docker-Content-Digest")
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
        logger.info(f"Image update check: {ref.registry}/{ref.repository}:{ref.tag} not reachable ({error})")
        return None


IMAGE_UPDATE = "image_update"
CHECK_INTERVAL_SECONDS = 6 * 3600


class ImageUpdateChecker:
    """Reports an update once per new remote digest; re-arms when the local image catches up."""

    def __init__(self):
        self._reported: Dict[str, str] = {}

    def observe(self, container: str, image: str, remote: Optional[str], local: Set[str]):
        from services.automation.container_watch import WatchEvent

        verdict = update_available(remote, local)
        if verdict is None:
            return []
        if not verdict:
            self._reported.pop(container, None)
            return []
        if self._reported.get(container) == remote:
            return []
        self._reported[container] = remote
        return [WatchEvent(container, IMAGE_UPDATE,
                           f"A newer image for '{container}' ({image}) is in the registry.")]
