# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""What Docker knows about a container, for the info display (v3.0.2).

Read when someone opens the display, not by the status cycle: one container
inspect and one image inspect, both read-only calls the allowlist proxy lets
through (GET /containers/{id}/json, GET /images/{name}/json).

THE VERSION is only as good as the image's labels. Measured on the operator's
host, 2026-09-28: linuxserver, AdGuard, Nginx Proxy Manager and MinIO label a
real version; an image built FROM ubuntu inherits "22.04" as its
org.opencontainers.image.version, and ubuntu marks that label as its own with
org.opencontainers.image.ref.name=ubuntu - so a version whose ref.name is a
base system is not the app's. A label without a digit ("master") says nothing
either. Without a usable label, a tag other than "latest" is the version
(redis:7-alpine); without that, the image date is the honest answer.
"""

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, Tuple

from utils.logging_utils import get_module_logger

logger = get_module_logger('container_facts_service')

VERSION_LABELS = ('org.opencontainers.image.version', 'org.label-schema.version', 'version')
# Base images that label their OWN version, inherited by every image built on them
BASE_SYSTEMS = frozenset({'ubuntu', 'debian', 'alpine', 'fedora', 'centos', 'rockylinux',
                          'almalinux', 'amazonlinux', 'busybox', 'redhat', 'ubi'})
# Unraid's macvlan/ipvlan networks: the container has its own LAN address
_LAN_NETWORK = re.compile(r'^(br|eth|bond|wlan)\d+(\.\d+)?$')
# Docker writes this for "never" (a container that was never stopped)
_NEVER = '0001-01-01'


@dataclass
class ContainerFacts:
    """A container as Docker describes it. Every field None when not known."""
    running: bool = False
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    exit_code: Optional[int] = None
    oom_killed: bool = False
    restart_policy: Optional[str] = None
    restart_count: Optional[int] = None
    health: Optional[str] = None  # the health check's verdict; None without a check
    version: Optional[str] = None
    image_created: Optional[datetime] = None
    memory_limit: Optional[int] = None  # bytes
    network_mode: Optional[str] = None
    # (container port, protocol) -> published host port
    published: Dict[Tuple[int, str], int] = field(default_factory=dict)


def _moment(value) -> Optional[datetime]:
    """A Docker timestamp ("2026-09-28T06:57:39.472938994Z") as an aware datetime."""
    if not value or str(value).startswith(_NEVER):
        return None
    text = str(value).replace('Z', '+00:00')
    # Python reads at most six fractional digits; Docker writes nine
    text = re.sub(r'(\.\d{6})\d+', r'\1', text)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def version_of(labels: Dict[str, str], reference: str) -> Optional[str]:
    """The app's version from the image labels or the tag, or None."""
    labels = labels or {}
    inherited = str(labels.get('org.opencontainers.image.ref.name') or '').lower() in BASE_SYSTEMS
    for key in VERSION_LABELS:
        if key == 'org.opencontainers.image.version' and inherited:
            continue
        value = str(labels.get(key) or '').strip()
        if value and any(ch.isdigit() for ch in value):
            return value
    tag = reference.rsplit(':', 1)[1] if ':' in reference.rsplit('/', 1)[-1] else ''
    if tag and tag != 'latest' and any(ch.isdigit() for ch in tag):
        return tag
    return None


def _published(ports: Dict) -> Dict[Tuple[int, str], int]:
    out = {}
    for spec, bindings in (ports or {}).items():
        try:
            port, proto = str(spec).split('/', 1)
            host_port = int((bindings or [{}])[0].get('HostPort'))
            out[(int(port), proto)] = host_port
        except (ValueError, TypeError, AttributeError, IndexError):
            continue
    return out


def facts_from_attrs(attrs: Dict, image_attrs: Optional[Dict] = None) -> ContainerFacts:
    """Build the facts from a container inspect and (optionally) an image inspect."""
    attrs = attrs or {}
    state = attrs.get('State') or {}
    config = attrs.get('Config') or {}
    host = attrs.get('HostConfig') or {}
    running = bool(state.get('Running'))
    exit_code = state.get('ExitCode')
    return ContainerFacts(
        running=running,
        started_at=_moment(state.get('StartedAt')) if running else None,
        finished_at=None if running else _moment(state.get('FinishedAt')),
        exit_code=exit_code if isinstance(exit_code, int) and not running else None,
        oom_killed=bool(state.get('OOMKilled')) and not running,
        restart_policy=((host.get('RestartPolicy') or {}).get('Name') or None),
        restart_count=attrs.get('RestartCount') if isinstance(attrs.get('RestartCount'), int) else None,
        health=((state.get('Health') or {}).get('Status') or None),
        version=version_of(config.get('Labels') or {}, str(config.get('Image') or '')),
        image_created=_moment((image_attrs or {}).get('Created')),
        memory_limit=host.get('Memory') or None,
        network_mode=host.get('NetworkMode') or None,
        published=_published((attrs.get('NetworkSettings') or {}).get('Ports')),
    )


def connect_port(facts: Optional[ContainerFacts], game_port: Optional[int]) -> Optional[int]:
    """The port players connect to, for the game port the server names, or None.

    The server names its port INSIDE the container. Published, the host port
    counts; on the host network, or on one of Unraid's own networks (br0,
    eth0, bond0: the container has its own address in the LAN), the port is
    the same outside. A bridge network that does not publish it - Docker's
    own or a user-defined one - has no port a player could reach, so none is
    shown rather than a wrong one.
    """
    if not game_port or facts is None:
        return None
    for proto in ('udp', 'tcp'):
        if (game_port, proto) in facts.published:
            return facts.published[(game_port, proto)]
    if facts.network_mode == 'host' or _LAN_NETWORK.match(str(facts.network_mode or '')):
        return game_port
    return None


def _read(name: str) -> ContainerFacts:
    from services.docker_service.client_factory import build_docker_client
    client = build_docker_client(timeout=5)
    try:
        attrs = client.containers.get(name).attrs
        image_attrs = None
        try:
            image_attrs = client.images.get(attrs.get('Image')).attrs
        except Exception as e:  # noqa: BLE001 - a removed image leaves the container readable
            logger.debug(f"Image of {name} not readable: {e}")
        return facts_from_attrs(attrs, image_attrs)
    finally:
        client.close()


async def get_container_facts(name: str) -> Optional[ContainerFacts]:
    """The facts of one container, or None when Docker cannot say. Never raises."""
    try:
        return await asyncio.to_thread(_read, name)
    except Exception as e:  # noqa: BLE001 - the info display opens without them
        logger.debug(f"Container facts for {name} not readable: {e}")
        return None
