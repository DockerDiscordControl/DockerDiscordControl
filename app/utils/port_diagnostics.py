# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Port Diagnostics                              #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                      #
# Licensed under the MIT License                                              #
# ============================================================================ #

from utils.logging_utils import get_module_logger
import socket
from pathlib import Path
import subprocess
import logging
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = get_module_logger('port_diagnostics')


def _own_container_id():
    """The container this process runs in, imported when asked.

    NOT a module-level import: tests/unit/app_modules replaces the services
    package with stubs, and pulling the real chain in at import time broke
    that group's collection. app/bot/token.py carries the same warning.
    """
    from services.docker_service.self_restart import own_container_id

    return own_container_id()


def _docker_client(timeout: int):
    """The sanctioned Docker client - the one that goes through the allowlist
    proxy rather than straight at the socket."""
    from services.docker_service.client_factory import build_docker_client

    return build_docker_client(timeout=timeout)


class PortDiagnostics:
    """Diagnose port-related issues and provide solutions"""

    EXPECTED_WEB_PORT = 9374  # Internal container port
    COMMON_EXTERNAL_PORTS = [8374, 9374, 8080, 8000]

    def __init__(self):
        self.container_name = self._detect_container_name()
        self.host_info = self._get_host_info()

    def _detect_container_name(self) -> Optional[str]:
        """The container's NAME, not its id.

        It used to run `docker inspect <hostname> --format {{.Name}}` and,
        when that binary turned out not to exist, fall back to the hostname -
        which Docker sets to the container's short id. That is why the
        diagnostics page showed "e993e9fb661b" where the operator expected
        "dockerdiscordcontrol", and why a suggested `docker run` once carried
        a hex string as the --name.

        describe_self() already answers this through the allowlist proxy, and
        falls back to the id only when there is genuinely nothing better.
        """
        container_id = _own_container_id()
        if not container_id:
            return None
        try:
            name = _docker_client(5).containers.get(container_id).name
        except Exception as error:                  # noqa: BLE001
            logger.debug("Could not read own container name: %s: %s",
                         type(error).__name__, error)
            return container_id
        return (name or container_id).lstrip('/')

    def _get_python_version(self) -> str:
        """Get Python version string."""
        try:
            import sys
            return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        except (AttributeError, ImportError):
            return 'unknown'

    def _get_container_uptime(self) -> str:
        """How long THIS CONTAINER has been running.

        IT USED TO READ /proc/uptime, which inside a container is the HOST's
        uptime - the kernel is shared. On the operator's machine, two minutes
        after a rebuild, it reported "22d 23h 49m". That was a real number
        about a real machine, under a name that made it evidence about
        something else, which is worse than no number at all.

        State.StartedAt is the container's own, and the allowlist proxy
        already permits the inspect this reads it from.
        """
        started = self._own_container_attribute(("State", "StartedAt"))
        if not started:
            # The host's uptime is not a substitute for the container's.
            return 'unknown'

        try:
            # Docker reports nanoseconds; datetime stops at microseconds.
            stamp = started.rstrip('Z')
            if '.' in stamp:
                whole, fraction = stamp.split('.', 1)
                stamp = f"{whole}.{fraction[:6]}"
            began = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError) as error:
            logger.debug("Could not read the container's start time: %s", error)
            return 'unknown'

        running = (datetime.now(timezone.utc) - began).total_seconds()
        if running < 0:
            return 'unknown'
        days = int(running // 86400)
        hours = int((running % 86400) // 3600)
        minutes = int((running % 3600) // 60)
        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    def _own_container_attribute(self, path):
        """One value out of this container's own inspect, or None.

        None means the question could not be put - never a stand-in answer
        from somewhere else. That distinction is what this module keeps
        getting wrong (see the port mapping, one commit earlier).
        """
        container_id = _own_container_id()
        if not container_id:
            return None
        try:
            attributes = _docker_client(5).containers.get(container_id).attrs
        except Exception as error:                  # noqa: BLE001 - any failure is "unknown"
            logger.debug("Could not inspect own container: %s: %s",
                         type(error).__name__, error)
            return None
        for key in path:
            if not isinstance(attributes, dict):
                return None
            attributes = attributes.get(key)
        return attributes

    def _get_memory_usage(self) -> str:
        """Get memory usage from /proc/meminfo."""
        try:
            with open('/proc/meminfo', 'r') as f:
                meminfo = f.read()
                mem_total = int([line for line in meminfo.split('\n') if line.startswith('MemTotal:')][0].split()[1]) * 1024
                mem_available = int([line for line in meminfo.split('\n') if line.startswith('MemAvailable:')][0].split()[1]) * 1024
                mem_used = mem_total - mem_available
                mem_percent = (mem_used / mem_total) * 100
                return f"{mem_used // 1024 // 1024}MB / {mem_total // 1024 // 1024}MB ({mem_percent:.1f}%)"
        except (IOError, OSError) as e:
            logger.debug(f"File I/O error reading memory info: {e}", exc_info=True)
            return 'unknown'
        except (ValueError, TypeError, IndexError, ZeroDivisionError) as e:
            logger.debug(f"Data parsing error calculating memory usage: {e}", exc_info=True)
            return 'unknown'

    def _get_disk_usage(self) -> str:
        """Get disk usage for /app."""
        try:
            import shutil
            total, used, free = shutil.disk_usage('/app')
            used_percent = (used / total) * 100
            return f"{used // 1024 // 1024}MB / {total // 1024 // 1024}MB ({used_percent:.1f}%)"
        except (ImportError, AttributeError) as e:
            logger.debug(f"Import error getting disk usage: {e}", exc_info=True)
            return 'unknown'
        except (OSError, ValueError, ZeroDivisionError) as e:
            logger.debug(f"Error calculating disk usage: {e}", exc_info=True)
            return 'unknown'

    def _host_memory_total(self) -> int:
        """The machine's own RAM, in bytes, or 0 when it cannot be read.

        Inside a container /proc/meminfo is the HOST's, which is exactly what
        this needs: it is the number Docker reports as a container's "limit"
        when the container was started without --memory.
        """
        try:
            with open('/proc/meminfo', 'r') as handle:
                for line in handle:
                    if line.startswith('MemTotal:'):
                        return int(line.split()[1]) * 1024
        except (IOError, OSError, ValueError, IndexError) as error:
            logger.debug("Could not read the machine's memory total: %s", error)
        return 0

    def _get_ddc_memory_usage(self) -> str:
        """How much memory DDC's own container is using.

        It used to run `docker stats` against a binary the image does not
        carry, catch the FileNotFoundError and answer 'unknown'. The allowlist
        proxy permits GET /containers/<id>/stats, so the number is simply
        available.

        A LIMIT IS NOT ALWAYS A LIMIT. A container started without --memory is
        reported with the HOST's entire RAM as its limit; a percentage of that
        says nothing, and a rule built on one once fired a memory warning at
        56 GB on a healthy machine. In that case the usage is given alone.
        """
        container_id = _own_container_id()
        if not container_id:
            return 'unknown'
        try:
            container = _docker_client(15).containers.get(container_id)
            memory = (container.stats(stream=False) or {}).get('memory_stats') or {}
            used = int(memory.get('usage') or 0)
            limit = int(memory.get('limit') or 0)
        except Exception as error:                  # noqa: BLE001 - any failure is "unknown"
            logger.debug("Could not read own memory usage: %s: %s",
                         type(error).__name__, error)
            return 'unknown'

        if used <= 0:
            return 'unknown'
        in_mb = used // 1024 // 1024
        machine = self._host_memory_total()
        if limit <= 0 or (machine and limit >= machine):
            # No limit of its own: the "limit" is the whole machine.
            return f"{in_mb}MB"
        return f"{in_mb}MB / {limit // 1024 // 1024}MB ({used / limit * 100:.1f}%)"

    def _get_ddc_image_size(self) -> str:
        """The size of the image DDC is running from.

        Same story as the memory field: `docker images` against a binary that
        is not there. The proxy permits GET /images/<name>/json.
        """
        container_id = _own_container_id()
        if not container_id:
            return 'unknown'
        try:
            client = _docker_client(15)
            reference = (client.containers.get(container_id)
                         .attrs.get('Config', {}).get('Image'))
            if not reference:
                return 'unknown'
            size = int(client.images.get(reference).attrs.get('Size') or 0)
        except Exception as error:                  # noqa: BLE001
            logger.debug("Could not read own image size: %s: %s",
                         type(error).__name__, error)
            return 'unknown'
        return f"{size // 1024 // 1024}MB" if size > 0 else 'unknown'

    def _detect_platform(self) -> tuple:
        """(the platform this process runs on, whether the HOST is Unraid).

        TWO DIFFERENT MACHINES, and conflating them was the bug. The first
        value is about wherever this process is - inside a container that is
        alpine, and /etc/os-release answers it correctly. The second is about
        the host, and it used to be answered by looking for
        /etc/unraid-version INSIDE the container: a file that is not there and
        never will be, so an Unraid installation reported itself as
        not-Unraid. The flag decides whether the panel offers Unraid steps or
        generic Docker ones, so being wrong sent the operator down the wrong
        path.
        """
        platform = self._this_platform()
        return platform, self._host_is_unraid(platform)

    def _this_platform(self) -> str:
        """The name of the system this process is running on."""
        try:
            if os.path.exists('/etc/unraid-version') or os.path.exists('/boot/config/ident.cfg'):
                return 'unraid'
            if os.path.exists('/etc/os-release'):
                with open('/etc/os-release', 'r') as handle:
                    content = handle.read().lower()
                for name in ('unraid', 'alpine', 'ubuntu', 'debian'):
                    if name in content:
                        return name
        except (IOError, OSError) as error:
            logger.debug("Could not read this platform's name: %s", error)
        return 'unknown'

    def _host_is_unraid(self, platform: str) -> bool:
        """Whether the machine running Docker is Unraid.

        TWO WAYS, because there are two situations.

        Inside a container the local filesystem is the CONTAINER's, so asking
        it about the host is the original mistake. The Docker daemon runs on
        the host and says so: GET /version reports its kernel, which on Unraid
        reads like "6.18.38-Unraid".

        Run straight on the host - from a checkout, no /.dockerenv - those
        same local files ARE the host's, and /etc/unraid-version is exactly
        what it looks like. Two cases covering that predate this change and
        were right; they were only wrong about the other situation.

        False means "no evidence", not "definitely not". Generic Docker advice
        is the safe reading of that, because it works on Unraid too.
        """
        if not os.path.exists('/.dockerenv') and platform == 'unraid':
            return True

        try:
            version = _docker_client(5).version() or {}
        except Exception as error:                  # noqa: BLE001
            logger.debug("Could not ask Docker about its host: %s: %s",
                         type(error).__name__, error)
            return False

        said = " ".join(str(version.get(key, '')) for key in
                        ('KernelVersion', 'OperatingSystem', 'Os'))
        return 'unraid' in said.lower()

    def _get_host_info(self) -> Dict:
        """Get host system information."""
        platform, is_unraid = self._detect_platform()
        docker_socket_available = os.path.exists('/var/run/docker.sock')

        info = {
            'platform': platform,
            'is_unraid': is_unraid,
            'is_docker': os.path.exists('/.dockerenv'),
            'python_version': self._get_python_version(),
            'container_uptime': self._get_container_uptime(),
            'memory_usage': self._get_memory_usage(),
            'disk_usage': self._get_disk_usage(),
            'docker_socket_available': docker_socket_available,
            'ddc_memory_usage': '',
            'ddc_image_size': ''
        }

        # Get DDC-specific metrics if Docker socket is available
        if self.container_name and docker_socket_available:
            info['ddc_memory_usage'] = self._get_ddc_memory_usage()
            info['ddc_image_size'] = self._get_ddc_image_size()

        return info

    def check_port_binding(self) -> Dict:
        """Check current port bindings for this container"""
        result = {
            'internal_port_listening': False,
            'external_ports': [],
            'port_mappings': {},
            'issues': [],
            'solutions': []
        }

        # Check if internal port is listening
        result['internal_port_listening'] = self._is_port_listening(self.EXPECTED_WEB_PORT)

        if not result['internal_port_listening']:
            result['issues'].append(f"Web UI service not listening on internal port {self.EXPECTED_WEB_PORT}")
            # NOT supervisorctl: DDC has been one process since v3, and the
            # image has no supervisord to ask (see the Application-tab
            # finding of the same day).
            result['solutions'].append(
                "The web UI did not answer on its own port - check the container log "
                "for a startup failure")
            return result

        mappings, known = self._get_docker_port_mappings()
        result['port_mappings'] = mappings
        result['port_mapping_known'] = known

        # Nothing was learned, so nothing is claimed. Silence here is the whole
        # fix: an unanswerable question is not a fault.
        if known:

            # Check for proper mapping
            web_port_mapped = False
            for internal_port, external_ports in mappings.items():
                # Equality, not a prefix. startswith() accepted 93745 as "the
                # web UI's own mapping" because it begins with 9374 (review C16).
                if str(internal_port) == str(self.EXPECTED_WEB_PORT):
                    web_port_mapped = True
                    result['external_ports'] = external_ports
                    break

            if not web_port_mapped:
                result['issues'].append(f"Port {self.EXPECTED_WEB_PORT} not mapped to any external port")
                if self.host_info['is_unraid']:
                    result['solutions'].extend(self._get_unraid_solutions())
                else:
                    result['solutions'].extend(self._get_docker_solutions())
            else:
                # Check if external ports are accessible
                for ext_port in result['external_ports']:
                    if not self._is_external_port_accessible(ext_port):
                        result['issues'].append(f"External port {ext_port} not accessible")
                        result['solutions'].append(f"Check firewall or host port conflicts for port {ext_port}")

        return result

    def _is_port_listening(self, port: int) -> bool:
        """Check if a port is listening locally"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                result = sock.connect_ex(('127.0.0.1', port))
                return result == 0
        except (socket.error, OSError) as e:
            # Socket errors (connection failed)
            logger.debug(f"Socket error checking port {port}: {e}", exc_info=True)
            return False

    def _is_external_port_accessible(self, port: int) -> bool:
        """Check if external port is accessible from outside"""
        # This would require more complex networking checks
        # For now, just return True if port mapping exists
        return True

    def _get_docker_port_mappings(self):
        """(the mappings, whether the question could be answered at all).

        THE SECOND VALUE IS THE POINT. This used to shell out to a `docker`
        binary that is deliberately not in the image, catch the
        FileNotFoundError, and return {} - which the caller read as "nothing is
        mapped" and reported as a fault, with advice. On the operator's machine
        it declared his working panel unreachable and offered a command that
        would have replaced his container without its volumes.

        DDC can simply ask. Its allowlist proxy permits
        GET /containers/<name>/json, and self_restart already knows which
        container this process is in.
        """
        container_id = _own_container_id()
        if not container_id:
            # Run from a checkout there is no container, so there is no
            # mapping to have an opinion about.
            return {}, False

        try:
            client = _docker_client(5)
            container = client.containers.get(container_id)
            ports = (container.attrs.get('NetworkSettings') or {}).get('Ports') or {}
        except Exception as error:                  # noqa: BLE001 - any failure is "unknown"
            logger.debug("Could not read own port mappings: %s: %s",
                         type(error).__name__, error)
            return {}, False

        mappings: Dict = {}
        for spec, bindings in ports.items():
            internal = str(spec).split('/')[0]
            for binding in bindings or []:
                mappings.setdefault(internal, []).append({
                    'host': binding.get('HostIp', ''),
                    'port': binding.get('HostPort', ''),
                })
        return mappings, True

    def _get_unraid_solutions(self) -> List[str]:
        """What to do about a genuinely unmapped port, on Unraid.

        NOTHING HERE CREATES A CONTAINER. The previous list offered "Remove
        container and re-install from Community Apps" and a bare start command
        with no -v, either of which would have taken the operator's config,
        logs and Mech state with it. Every step edits what is already there.
        """
        return [
            "UNRAID: Docker tab -> Edit the DDC container -> WebUI port: "
            f"set Container Port to {self.EXPECTED_WEB_PORT} and choose a free Host Port",
            "UNRAID: Apply saves the edit and restarts the container; existing "
            "config and data are kept",
            "UNRAID: if the Host Port is refused, another container already has "
            "it - pick a different one",
        ]

    def _get_docker_solutions(self) -> List[str]:
        """What to do about a genuinely unmapped port, anywhere else.

        See the note above: no line here builds a new container.
        """
        return [
            f"DOCKER: stop the container and start it again with -p <host>:{self.EXPECTED_WEB_PORT}, "
            "keeping the -v options it already has",
            "DOCKER: with compose, add the port under `ports:` and run "
            "`docker compose up -d` - the volumes stay",
            "DOCKER: check the host port is free first: netstat -tlnp | grep <host>",
        ]

    def get_diagnostic_report(self) -> Dict:
        """Generate complete diagnostic report"""
        report = {
            # A field called timestamp held logger.name - the fixed string
            # "app.utils.port_diagnostics" (review C16).
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'container_name': self.container_name,
            'host_info': self.host_info,
            'port_check': self.check_port_binding(),
            'recommendations': []
        }

        report['recommendations'] = self._recommendations(report['port_check'])
        return report

    def _the_scheme(self) -> str:
        """http or https, read from the mode DDC is actually running in.

        A fixed "http://" was wrong for every installation with TLS, and the
        address is the one line of a report a reader types by hand.
        """
        return "https" if self._tls_mode() == "self-signed" else "http"

    @staticmethod
    def _tls_mode() -> str:
        return (os.environ.get("DDC_TLS_MODE") or "off").strip().lower()

    # BEHIND A PROXY THE HOST PORT IS NOT AN ADDRESS FOR A BROWSER. It speaks
    # plain HTTP to the reverse proxy and refuses anybody else (app/web/tls.py).
    # Until 2026-09-26 proxy mode was treated like self-signed here and the
    # report offered https://<host>:<port>, which fails in the handshake. The
    # address that works is the proxy's, which DDC cannot know.
    BEHIND_A_PROXY = ("DDC_TLS_MODE=proxy: open the panel through your reverse proxy over "
                      "HTTPS - the host port only answers the proxy")

    def _recommendations(self, port_check: Dict) -> List[str]:
        """What to tell the operator, built from what was just measured.

        THESE USED TO BE THREE FIXED STRINGS, appended to every report on an
        Unraid host whether anything was wrong or not::

            "Check Unraid Docker settings: Host Port 8374 -> Container Port 9374"
            "Access Web UI at: http://[UNRAID-IP]:8374 (default: admin/admin)"

        and the same report had measured the mapping three lines above -
        9374 on the operator's own container, not 8374 (2026-09-26). The
        scheme was fixed too, while DDC_TLS_MODE=self-signed answers HTTPS
        only. And admin/admin has never been a DDC credential: the
        first-time bootstrap is admin/setup and it closes as soon as a
        password is set. No line here names a credential at all.
        """
        host_ports = [str(entry.get("port")) if isinstance(entry, dict) else str(entry)
                      for entry in port_check.get("external_ports") or []]
        # The same address twice - IPv4 and IPv6 bind separately - is one
        # address to a reader.
        seen = list(dict.fromkeys(p for p in host_ports if p))

        unraid = bool(self.host_info.get('is_unraid'))
        if not seen:
            # Nothing was learned about the mapping, so no number is claimed -
            # only the one port this container is certain of, its own. The
            # careful step-by-step advice for a genuinely unmapped port is
            # already written and already attached to port_check['solutions'].
            if unraid:
                return [
                    f"UNRAID: the web UI listens on container port "
                    f"{self.EXPECTED_WEB_PORT} - open the Docker tab, edit DDC and give "
                    f"that container port a free host port",
                ]
            return [
                f"The web UI listens on container port {self.EXPECTED_WEB_PORT} - "
                f"check the port mapping, -p <host>:{self.EXPECTED_WEB_PORT}",
            ]

        scheme = self._the_scheme()
        where = "[UNRAID-IP]" if unraid else "localhost"
        if self._tls_mode() == "proxy":
            told = [self.BEHIND_A_PROXY]
        else:
            told = [f"Web UI: {scheme}://{where}:{port}" for port in seen]
        told.append(
            f"Host port {' and '.join(seen)} is mapped to container port "
            f"{self.EXPECTED_WEB_PORT}; check the host firewall if the panel "
            f"cannot be reached from another machine")
        if scheme == "https":
            told.append(
                "TLS is on, so the panel answers HTTPS only - a plain http:// "
                "address will be refused")
        return told

    def log_startup_diagnostics(self):
        """Log diagnostic information at startup"""
        report = self.get_diagnostic_report()

        logger.info("=== DDC Port Diagnostics ===")
        logger.info(f"Container: {report['container_name'] or 'Unknown'}")
        logger.info(f"Platform: {report['host_info']['platform']}")

        internal_listening = report['port_check']['internal_port_listening']
        logger.info(f"Internal Web UI Port {self.EXPECTED_WEB_PORT}: {'LISTENING' if internal_listening else 'NOT LISTENING'}")

        if not internal_listening:
            # Only warn if the port is genuinely not listening
            logger.warning(f"Web UI service is not listening on port {self.EXPECTED_WEB_PORT}")
            logger.info("This may indicate a startup issue. Check if the web server process started correctly.")
        else:
            # Port is listening, report success
            if report['port_check']['port_mappings']:
                logger.info(f"Port Mappings: {report['port_check']['port_mappings']}")
            else:
                # Port mapping detection often fails from inside containers, this is normal
                logger.debug("Port mapping detection not available from inside container (normal)")

            logger.info("Port configuration OK")

        # Log access information with actual IP resolution
        actual_host_ip = self._get_actual_host_ip()
        # http:// on a panel that answers only https is a link that fails, or
        # at best redirects (app/web/tls.py).
        scheme = "https" if os.environ.get("DDC_TLS_MODE", "").strip().lower() == "self-signed" \
            else "http"

        if self._tls_mode() == "proxy":
            logger.info(self.BEHIND_A_PROXY)
        elif report['port_check']['external_ports']:
            for port_info in report['port_check']['external_ports']:
                if isinstance(port_info, dict):
                    host = port_info['host']
                    if host in ['0.0.0.0', '::']:
                        host = actual_host_ip or 'localhost'
                    logger.info(f"Web UI should be accessible at: {scheme}://{host}:{port_info['port']}")
                else:
                    host = actual_host_ip or 'localhost'
                    logger.info(f"Web UI should be accessible at: {scheme}://{host}:{port_info}")
        else:
            host = actual_host_ip or 'localhost'
            logger.info(f"Web UI: {scheme}://{host}:{self.EXPECTED_WEB_PORT}")

        logger.info("=== End Diagnostics ===")

        return report

    # Reached, but useless in a line an operator reads on another computer:
    # the health check and the container itself use these.
    NOT_WORTH_PRINTING = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})

    def _try_an_address_that_was_used(self) -> Optional[str]:
        """An address the panel has actually been reached on.

        The TLS side learns these - from SNI, from the plain-HTTP redirect and
        from the Host of every request - and keeps them beside the certificate,
        because a certificate has to name them (app/web/tls.py). That makes
        them the one source here that is an observation rather than a guess.

        Nothing is learned on an installation nobody has visited yet, and then
        this returns None and the guessing below has its turn. An address can
        be observed or guessed; it cannot be known before anybody has been.
        """
        try:
            from app.web.tls import known_names
            from utils.config_paths import get_config_dir

            for name in known_names(Path(get_config_dir()) / "tls"):
                if name.lower() not in self.NOT_WORTH_PRINTING:
                    logger.info(f"Using an address the panel was reached on: {name}")
                    return name
        except Exception as error:  # noqa: BLE001 - this runs during startup
            logger.debug(f"Could not read the addresses the panel was reached on: {error}")
        return None

    def _try_environment_variable_ip(self) -> Optional[str]:
        """Try to get host IP from environment variables."""
        import os
        host_ip_env = os.environ.get('HOST_IP') or os.environ.get('UNRAID_IP') or os.environ.get('SERVER_IP')
        if host_ip_env:
            logger.info(f"Using HOST_IP from environment: {host_ip_env}")
            return host_ip_env
        return None

    def _try_traceroute_ip(self) -> Optional[str]:
        """Try to find host IP using traceroute method."""
        try:
            logger.info("Trying traceroute method to find host IP...")
            import subprocess

            # Try traceroute (Alpine has it)
            try:
                result = subprocess.run(['traceroute', '-n', '-m', '3', '-w', '1', '8.8.8.8'],
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0 or result.stdout:
                    logger.info("Traceroute output received")
                    for line in result.stdout.split('\n'):
                        line = line.strip()
                        if line and line[0].isdigit():
                            parts = line.split()
                            if len(parts) >= 2:
                                hop_num, hop_ip = parts[0], parts[1]
                                # Skip first hop (Docker gateway), get second hop (host)
                                if hop_num == '2' and not hop_ip.startswith('172.17.') and not hop_ip.startswith('*'):
                                    logger.info(f"✅ Found host IP via traceroute: {hop_ip}")
                                    return hop_ip
            except FileNotFoundError:
                logger.info("traceroute not found, trying tracepath...")
                try:
                    result = subprocess.run(['tracepath', '-n', '8.8.8.8'],
                                          capture_output=True, text=True, timeout=5)
                    if result.returncode == 0 or result.stdout:
                        for line in result.stdout.split('\n'):
                            if line.strip() and line.strip()[0].isdigit():
                                parts = line.strip().split()
                                if len(parts) >= 2:
                                    hop_num = parts[0].rstrip(':')
                                    hop_ip = parts[1]
                                    if hop_num == '2' and not hop_ip.startswith('172.17.'):
                                        logger.info(f"✅ Found host IP via tracepath: {hop_ip}")
                                        return hop_ip
                except (subprocess.SubprocessError, FileNotFoundError) as e:
                    logger.debug(f"Subprocess error with tracepath: {e}", exc_info=True)
        except Exception as e:
            logger.debug(f"Traceroute method failed: {e}", exc_info=True)
        return None

    def _try_docker_host_gateway(self) -> Optional[str]:
        """Try to find host IP via Docker gateway and routing."""
        try:
            logger.info("Trying standard Docker host detection as fallback...")
            import subprocess

            # Try /etc/hosts first
            try:
                with open('/etc/hosts', 'r') as f:
                    for line in f.read().split('\n'):
                        if 'host.docker.internal' in line or 'host-gateway' in line:
                            parts = line.split()
                            if parts and parts[0] and not parts[0].startswith('127.'):
                                host_ip = parts[0]
                                if host_ip != '172.17.0.1':
                                    logger.info(f"Found Docker host via /etc/hosts: {host_ip}")
                                    return host_ip
            except (IOError, OSError) as e:
                logger.debug(f"File I/O error reading /etc/hosts: {e}", exc_info=True)

            # Try ip route
            result = subprocess.run(['/sbin/ip', 'route'], capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'default' in line and 'via' in line:
                        parts = line.split()
                        if 'via' in parts:
                            idx = parts.index('via')
                            if idx + 1 < len(parts):
                                gateway = parts[idx + 1]
                                logger.info(f"Docker host gateway: {gateway}")
                                if gateway != '172.17.0.1':
                                    return gateway
        except Exception as e:
            logger.debug(f"Docker host detection failed: {e}", exc_info=True)
        return None

    def _get_actual_host_ip(self) -> str:
        """Get the actual accessible IP address of the host."""
        try:
            logger.info("Starting IP detection (looking for host IP)...")

            # Method 0: an address somebody has actually reached the panel on.
            # Asked FIRST because it is the only one that is not a guess: the
            # three below try to work out, from inside a container, an address
            # belonging to the host, and on the operator's own machine all
            # three fail (2026-09-25). Asking first also saves spawning
            # traceroute on every start.
            host_ip = self._try_an_address_that_was_used()
            if host_ip:
                return host_ip

            # Method 1: Try environment variables (fastest)
            host_ip = self._try_environment_variable_ip()
            if host_ip:
                return host_ip

            # Method 2: Try traceroute method
            host_ip = self._try_traceroute_ip()
            if host_ip:
                return host_ip

            # Method 3: Try Docker host gateway
            host_ip = self._try_docker_host_gateway()
            if host_ip:
                return host_ip

            # All methods failed - return fallback
            logger.warning("All host IP detection methods failed, returning None")
        except Exception as e:
            logger.debug(f"Error during host IP detection: {e}", exc_info=True)

        return None

    def _test_if_this_is_our_host(self, ip: str) -> bool:
        """Test if the given IP is likely our Docker host by trying to connect to our web service."""
        try:
            import socket
            # Try to connect to the web service on this IP with the expected external port
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2)
                # Try the common external port mappings
                for port in [8374, 9374]:
                    try:
                        result = s.connect_ex((ip, port))
                        if result == 0:
                            return True
                    except (socket.error, OSError):
                        # Socket errors (connection failed)
                        continue

            # Alternative: Try to see if this IP responds to HTTP on our expected ports
            import subprocess
            try:
                # Quick HTTP check without full request
                result = subprocess.run(['timeout', '2', 'nc', '-z', ip, '8374'],
                                      capture_output=True, timeout=3)
                if result.returncode == 0:
                    return True
            except (subprocess.SubprocessError, FileNotFoundError) as e:
                # Subprocess errors (nc command failed)
                logger.debug(f"Subprocess error testing host with nc: {e}", exc_info=True)
            except (ValueError, OSError) as e:
                # Network or data errors
                logger.debug(f"Error testing host with nc: {e}", exc_info=True)

        except (ImportError, socket.error, OSError) as e:
            # Import or socket errors
            logger.debug(f"Error testing if {ip} is our host: {e}", exc_info=True)
        return False


def run_port_diagnostics() -> Dict:
    """Convenience function to run diagnostics"""
    diagnostics = PortDiagnostics()
    return diagnostics.get_diagnostic_report()


def log_port_diagnostics():
    """Convenience function to log diagnostics at startup"""
    diagnostics = PortDiagnostics()
    return diagnostics.log_startup_diagnostics()
