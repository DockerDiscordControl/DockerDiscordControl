# -*- coding: utf-8 -*-
"""Restarting DDC's own container, from inside it.

THE OPERATOR ASKED (2026-09-24) for a button that restarts DDC, shown only when
a restart is actually needed, and said an earlier assistant had told him it
could not be done "because the systems are separated".

THEY ARE NOT SEPARATED. DDC's whole purpose is to talk to Docker, and its own
container is a container like any other. Measured on his server, from inside
the running container:

    HOSTNAME                     1f27843345e6
    docker inspect ... .Id       1f27843345e6...
    DOCKER_HOST                  unix:///run/ddc-proxy/docker.sock
    containers.get($HOSTNAME)    dockerdiscordcontrol, running

Docker sets a container's hostname to its own short id unless told otherwise,
so the process can look itself up with no configuration at all. The allowlist
in front of the socket already permits POST /containers/<name>/restart for any
name (services/docker_proxy/allowlist_proxy.py), so nothing had to be opened up
either.

WHAT DOES NEED CARE IS THE ORDER. `restart` stops the container, which kills
the very process that is answering the request - so the answer has to be on its
way before the restart is asked for. The request thread therefore returns at
once and a timer does the asking a moment later. Nothing waits for the result:
by the time Docker acts there is nobody left to tell.

`protected_containers` (["ddc", "portainer"]) is not a guard against this. It
stops AUTO-ACTION RULES from acting on DDC, which is about a rule firing
unattended - the opposite of an operator pressing a button and being told the
bot is going down.
"""

import os
import threading
from typing import Optional, Tuple

from utils.logging_utils import get_module_logger

logger = get_module_logger('ddc.self_restart')

# Long enough for the response to leave, short enough that the operator does
# not wonder whether the button worked.
RESTART_DELAY_SECONDS = 1.5


def own_container_id() -> Optional[str]:
    """The id of the container this process runs in, or None outside one.

    Docker sets HOSTNAME to the container's short id. An operator who has given
    the container a hostname of their own gets None here rather than a wrong
    guess - a restart aimed at the wrong container is worse than no button.
    """
    name = (os.environ.get('HOSTNAME') or '').strip()
    if not name:
        return None
    # A short id is 12 hex characters; a full one 64. Anything else is a
    # hostname somebody chose, and it is not ours to interpret.
    if len(name) in (12, 64) and all(c in '0123456789abcdef' for c in name.lower()):
        return name
    return None


def describe_self(client=None) -> Tuple[bool, str]:
    """(can we restart ourselves, the container's name or why not).

    Asked before the button is offered, so the operator is not shown a control
    that cannot work.
    """
    container_id = own_container_id()
    if not container_id:
        return False, "not running in a container, or its hostname was renamed"
    try:
        if client is None:
            # The one place a client may be built: v3.0 points DOCKER_HOST at
            # the allowlist proxy, and a client built any other way talks to
            # the socket directly, past it. Pinned by
            # tests/spec/test_every_docker_client_site_is_known.py, which
            # caught this module doing it the easy way.
            from services.docker_service.client_factory import build_docker_client

            client = build_docker_client(timeout=10)
        container = client.containers.get(container_id)
        return True, container.name
    except Exception as error:                       # noqa: BLE001 - any failure is "no"
        logger.warning(f"Cannot identify own container: {type(error).__name__}: {error}")
        return False, f"{type(error).__name__}"


def restart_myself(client=None, delay: float = RESTART_DELAY_SECONDS,
                   timer=threading.Timer) -> Tuple[bool, str]:
    """Ask Docker to restart this container, AFTER this call has returned.

    Returns what the caller can still say; the restart itself happens once the
    answer is gone. A failure to even find the container is reported now, since
    that is knowable before anything is scheduled.
    """
    ok, name = describe_self(client)
    if not ok:
        return False, name

    container_id = own_container_id()

    def _do_it():
        try:
            if client is None:
                from services.docker_service.client_factory import build_docker_client

                inner = build_docker_client(timeout=30)
            else:
                inner = client
            logger.info(f"Restarting own container {name} on request from the panel")
            inner.containers.get(container_id).restart()
        except Exception as error:                   # noqa: BLE001
            # Nobody is listening any more - the log is the only place left.
            logger.error(f"Self-restart failed: {type(error).__name__}: {error}")

    handle = timer(delay, _do_it)
    handle.daemon = True
    handle.start()
    return True, name
