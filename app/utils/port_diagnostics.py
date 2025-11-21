# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Port Diagnostics                              #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                      #
# Licensed under the MIT License                                              #
# ============================================================================ #

import socket
import subprocess
import logging
import os
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class PortDiagnostics:
    """Diagnose port-related issues and provide solutions"""

    EXPECTED_WEB_PORT = 9374  # Internal container port
    COMMON_EXTERNAL_PORTS = [8374, 9374, 8080, 8000]

    def __init__(self):
        self.container_name = self._detect_container_name()
        self.host_info = self._get_host_info()

    def _detect_container_name(self) -> Optional[str]:
        """Detect the current container name"""
        try:
            # Try to read from hostname (Docker sets this to container ID/name)
            with open('/etc/hostname', 'r') as f:
                hostname = f.read().strip()

            # Try to get container name from Docker API (if docker command is available)
            try:
                result = subprocess.run([
                    'docker', 'inspect', hostname, '--format', '{{.Name}}'
                ], capture_output=True, text=True, timeout=5)

                if result.returncode == 0:
                    name = result.stdout.strip().lstrip('/')
                    return name
            except (FileNotFoundError, subprocess.TimeoutExpired):
                # Docker command not available or timeout - this is normal inside containers
                pass

            # Fall back to hostname or default name
            return hostname if hostname else "dockerdiscordcontrol"
        except (IOError, OSError) as e:
            # File I/O errors (reading /etc/hostname)
            logger.debug(f"File I/O error detecting container name: {e}", exc_info=True)
            return "dockerdiscordcontrol"
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            # Subprocess errors (docker inspect command failures)
            logger.debug(f"Subprocess error detecting container name: {e}", exc_info=True)
            return "dockerdiscordcontrol"

    def _get_python_version(self) -> str:
        """Get Python version string."""
        try:
            import sys
            return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        except (AttributeError, ImportError):
            return 'unknown'

    def _get_container_uptime(self) -> str:
        """Get container uptime from /proc/uptime."""
        try:
            with open('/proc/uptime', 'r') as f:
                uptime_seconds = float(f.read().split()[0])
                days = int(uptime_seconds // 86400)
                hours = int((uptime_seconds % 86400) // 3600)
                minutes = int((uptime_seconds % 3600) // 60)
                if days > 0:
                    return f"{days}d {hours}h {minutes}m"
                elif hours > 0:
                    return f"{hours}h {minutes}m"
                else:
                    return f"{minutes}m"
        except (IOError, OSError) as e:
            logger.debug(f"File I/O error reading uptime: {e}", exc_info=True)
            return 'unknown'
        except (ValueError, TypeError, IndexError) as e:
            logger.debug(f"Data parsing error calculating uptime: {e}", exc_info=True)
            return 'unknown'

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

    def _get_supervisord_status(self) -> Dict:
        """Get supervisord process status."""
        try:
            result = subprocess.run(['supervisorctl', 'status'],
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                processes = {}
                for line in result.stdout.strip().split('\n'):
                    if line.strip():
                        parts = line.split()
                        if len(parts) >= 2:
                            processes[parts[0]] = parts[1]
                return processes
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            logger.debug(f"Subprocess error getting supervisord status: {e}", exc_info=True)
            return {'error': 'supervisorctl not available'}
        except (ValueError, IndexError) as e:
            logger.debug(f"Data parsing error parsing supervisord status: {e}", exc_info=True)
            return {'error': 'parse error'}

    def _get_ddc_memory_usage(self) -> str:
        """Get DDC container memory usage."""
        try:
            result = subprocess.run([
                'docker', 'stats', self.container_name, '--no-stream', '--format',
                'table {{.MemUsage}}'
            ], capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if len(lines) >= 2:
                    return lines[1].strip()
            return 'unknown'
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            logger.debug(f"Subprocess error getting container memory stats: {e}", exc_info=True)
            return 'unknown'
        except (ValueError, IndexError) as e:
            logger.debug(f"Data parsing error parsing memory stats: {e}", exc_info=True)
            return 'unknown'

    def _get_ddc_image_size(self) -> str:
        """Get DDC container image size."""
        try:
            result = subprocess.run([
                'docker', 'images', '--format', 'table {{.Repository}}:{{.Tag}}\t{{.Size}}',
                '--filter', f'reference=*{self.container_name}*'
            ], capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if len(lines) >= 2:
                    for line in lines[1:]:
                        parts = line.split('\t')
                        if len(parts) >= 2:
                            image_name = parts[0].lower()
                            if 'dockerdiscordcontrol' in image_name or 'ddc' in image_name:
                                return parts[1].strip()
            return 'unknown'
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            logger.debug(f"Subprocess error getting image size: {e}", exc_info=True)
            return 'unknown'
        except (ValueError, IndexError) as e:
            logger.debug(f"Data parsing error parsing image size: {e}", exc_info=True)
            return 'unknown'

    def _detect_platform(self) -> tuple:
        """Detect platform and check if Unraid. Returns (platform_name, is_unraid)."""
        try:
            if os.path.exists('/etc/unraid-version') or os.path.exists('/boot/config/ident.cfg'):
                return 'unraid', True
            elif os.path.exists('/etc/os-release'):
                with open('/etc/os-release', 'r') as f:
                    content = f.read().lower()
                    if 'unraid' in content:
                        return 'unraid', True
                    elif 'ubuntu' in content:
                        return 'ubuntu', False
                    elif 'debian' in content:
                        return 'debian', False
                    elif 'alpine' in content:
                        return 'alpine', False
        except (IOError, OSError) as e:
            logger.debug(f"File I/O error detecting host platform: {e}", exc_info=True)
        except (ValueError, AttributeError) as e:
            logger.debug(f"Data processing error detecting host platform: {e}", exc_info=True)
        return 'unknown', False

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
            'supervisord_status': self._get_supervisord_status(),
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
            result['solutions'].append("Check if gunicorn/web service is running: supervisorctl status webui")
            return result

        # Get Docker port mappings if possible
        if self.container_name:
            mappings = self._get_docker_port_mappings()
            result['port_mappings'] = mappings

            # Check for proper mapping
            web_port_mapped = False
            for internal_port, external_ports in mappings.items():
                if str(internal_port).startswith(str(self.EXPECTED_WEB_PORT)):
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

    def _get_docker_port_mappings(self) -> Dict:
        """Get Docker port mappings for this container"""
        try:
            if not self.container_name:
                return {}

            # Docker command may not be available inside container
            try:
                result = subprocess.run([
                    'docker', 'port', self.container_name
                ], capture_output=True, text=True, timeout=5)

                if result.returncode != 0:
                    return {}

                mappings = {}
                for line in result.stdout.strip().split('\n'):
                    if line.strip():
                        # Format: "9374/tcp -> 0.0.0.0:8374"
                        match = re.match(r'(\d+)/tcp -> (.+):(\d+)', line)
                        if match:
                            internal_port = match.group(1)
                            external_host = match.group(2)
                            external_port = match.group(3)

                            if internal_port not in mappings:
                                mappings[internal_port] = []
                            mappings[internal_port].append({
                                'host': external_host,
                                'port': external_port
                            })

                return mappings
            except (FileNotFoundError, subprocess.TimeoutExpired):
                # Docker command not available - this is normal inside containers
                logger.debug("Docker command not available for port mapping detection")
                return {}
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            # Subprocess errors (docker port command failed)
            logger.debug(f"Subprocess error getting Docker port mappings: {e}", exc_info=True)
            return {}
        except (ValueError, IndexError, AttributeError) as e:
            # Data parsing errors (port mapping parsing)
            logger.debug(f"Data parsing error parsing port mappings: {e}", exc_info=True)
            return {}

    def _get_unraid_solutions(self) -> List[str]:
        """Get Unraid-specific solutions"""
        return [
            "UNRAID FIX: Go to Docker tab → Edit DDC container → Set 'Host Port: 8374' and 'Container Port: 9374'",
            "UNRAID FIX: Remove container and re-install from Community Apps with correct port mapping",
            "UNRAID FIX: Verify template shows: WebUI Port - Host: 8374, Container: 9374",
            f"UNRAID MANUAL: docker run -d --name {self.container_name or 'dockerdiscordcontrol'} -p 8374:9374 -v /var/run/docker.sock:/var/run/docker.sock dockerdiscordcontrol/dockerdiscordcontrol:latest"
        ]

    def _get_docker_solutions(self) -> List[str]:
        """Get generic Docker solutions"""
        return [
            f"DOCKER FIX: Add port mapping: -p 8374:{self.EXPECTED_WEB_PORT}",
            f"DOCKER FIX: Recreate container with: docker run -d --name {self.container_name or 'dockerdiscordcontrol'} -p 8374:{self.EXPECTED_WEB_PORT} dockerdiscordcontrol/dockerdiscordcontrol:latest",
            "DOCKER FIX: Check if port 8374 is already in use: netstat -tlnp | grep 8374",
            "DOCKER FIX: Try alternative port: -p 8375:9374 or -p 8000:9374"
        ]

    def get_diagnostic_report(self) -> Dict:
        """Generate complete diagnostic report"""
        report = {
            'timestamp': logger.name,
            'container_name': self.container_name,
            'host_info': self.host_info,
            'port_check': self.check_port_binding(),
            'recommendations': []
        }

        # Add platform-specific recommendations
        if self.host_info['is_unraid']:
            report['recommendations'].extend([
                "For Unraid users: Ensure Community Apps template has correct port mapping",
                "Check Unraid Docker settings: Host Port 8374 → Container Port 9374",
                "Access Web UI at: http://[UNRAID-IP]:8374 (default: admin/admin)"
            ])
        else:
            report['recommendations'].extend([
                "Ensure Docker port mapping: -p 8374:9374",
                "Check firewall settings for port 8374",
                "Access Web UI at: http://localhost:8374 (default: admin/admin)"
            ])

        return report

    def log_startup_diagnostics(self):
        """Log diagnostic information at startup"""
        report = self.get_diagnostic_report()

        logger.info("=== DDC Port Diagnostics ===")
        logger.info(f"Container: {report['container_name'] or 'Unknown'}")
        logger.info(f"Platform: {report['host_info']['platform']}")
        logger.info(f"Internal Web UI Port {self.EXPECTED_WEB_PORT}: {'LISTENING' if report['port_check']['internal_port_listening'] else 'NOT LISTENING'}")

        if report['port_check']['port_mappings']:
            logger.info(f"Port Mappings: {report['port_check']['port_mappings']}")
        else:
            logger.warning("No port mappings detected - Web UI may not be accessible externally")

        # Log issues and solutions
        if report['port_check']['issues']:
            logger.warning("PORT ISSUES DETECTED:")
            for issue in report['port_check']['issues']:
                logger.warning(f"  WARNING: {issue}")

            logger.info("SUGGESTED SOLUTIONS:")
            for solution in report['port_check']['solutions']:
                logger.info(f"  SOLUTION: {solution}")
        else:
            logger.info("Port configuration appears correct")

        # Log access information with actual IP resolution
        actual_host_ip = self._get_actual_host_ip()

        if report['port_check']['external_ports']:
            for port_info in report['port_check']['external_ports']:
                if isinstance(port_info, dict):
                    # Replace generic bind addresses with actual IP
                    host = port_info['host']
                    if host in ['0.0.0.0', '::']:
                        host = actual_host_ip or 'localhost'
                    logger.info(f"Web UI should be accessible at: http://{host}:{port_info['port']}")
                else:
                    host = actual_host_ip or 'localhost'
                    logger.info(f"Web UI should be accessible at: http://{host}:{port_info}")
        elif self.host_info['is_unraid']:
            if actual_host_ip:
                logger.info(f"Web UI should be accessible at: http://{actual_host_ip}:8374")
            else:
                logger.info("Web UI should be accessible at: http://[UNRAID-IP]:8374")
        else:
            host = actual_host_ip or 'localhost'
            logger.info(f"Web UI should be accessible at: http://{host}:8374")

        logger.info("=== End Diagnostics ===")

        return report

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
