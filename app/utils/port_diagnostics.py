# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Port Diagnostics                              #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                      #
# Licensed under the MIT License                                              #
# ============================================================================ #

import socket
import subprocess
import json
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

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
    
    def _get_host_info(self) -> Dict:
        """Get host system information"""
        info = {
            'platform': 'unknown',
            'is_unraid': False,
            'is_docker': True if os.path.exists('/.dockerenv') else False,
            'python_version': '',
            'container_uptime': '',
            'memory_usage': '',
            'disk_usage': '',
            'supervisord_status': {},
            'docker_socket_available': False,
            'ddc_memory_usage': '',
            'ddc_image_size': ''
        }
        
        try:
            # Get Python version
            import sys
            info['python_version'] = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
            
            # Get container uptime
            try:
                with open('/proc/uptime', 'r') as f:
                    uptime_seconds = float(f.read().split()[0])
                    days = int(uptime_seconds // 86400)
                    hours = int((uptime_seconds % 86400) // 3600)
                    minutes = int((uptime_seconds % 3600) // 60)
                    if days > 0:
                        info['container_uptime'] = f"{days}d {hours}h {minutes}m"
                    elif hours > 0:
                        info['container_uptime'] = f"{hours}h {minutes}m"
                    else:
                        info['container_uptime'] = f"{minutes}m"
            except (IOError, OSError) as e:
                # File I/O errors (reading /proc/uptime)
                logger.debug(f"File I/O error reading uptime: {e}", exc_info=True)
                info['container_uptime'] = 'unknown'
            except (ValueError, TypeError, IndexError) as e:
                # Data parsing errors (uptime calculation)
                logger.debug(f"Data parsing error calculating uptime: {e}", exc_info=True)
                info['container_uptime'] = 'unknown'
            
            # Get memory usage
            try:
                with open('/proc/meminfo', 'r') as f:
                    meminfo = f.read()
                    mem_total = int([line for line in meminfo.split('\n') if line.startswith('MemTotal:')][0].split()[1]) * 1024
                    mem_available = int([line for line in meminfo.split('\n') if line.startswith('MemAvailable:')][0].split()[1]) * 1024
                    mem_used = mem_total - mem_available
                    mem_percent = (mem_used / mem_total) * 100
                    info['memory_usage'] = f"{mem_used // 1024 // 1024}MB / {mem_total // 1024 // 1024}MB ({mem_percent:.1f}%)"
            except (IOError, OSError) as e:
                # File I/O errors (reading /proc/meminfo)
                logger.debug(f"File I/O error reading memory info: {e}", exc_info=True)
                info['memory_usage'] = 'unknown'
            except (ValueError, TypeError, IndexError, ZeroDivisionError) as e:
                # Data parsing errors (memory calculation)
                logger.debug(f"Data parsing error calculating memory usage: {e}", exc_info=True)
                info['memory_usage'] = 'unknown'
            
            # Get disk usage for /app
            try:
                import shutil
                total, used, free = shutil.disk_usage('/app')
                used_percent = (used / total) * 100
                info['disk_usage'] = f"{used // 1024 // 1024}MB / {total // 1024 // 1024}MB ({used_percent:.1f}%)"
            except (ImportError, AttributeError) as e:
                # Import errors (shutil module unavailable)
                logger.debug(f"Import error getting disk usage: {e}", exc_info=True)
                info['disk_usage'] = 'unknown'
            except (OSError, ValueError, ZeroDivisionError) as e:
                # File system errors or calculation errors
                logger.debug(f"Error calculating disk usage: {e}", exc_info=True)
                info['disk_usage'] = 'unknown'
            
            # Get supervisord process status
            try:
                result = subprocess.run(['supervisorctl', 'status'], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    processes = {}
                    for line in result.stdout.strip().split('\n'):
                        if line.strip():
                            parts = line.split()
                            if len(parts) >= 2:
                                name = parts[0]
                                status = parts[1]
                                processes[name] = status
                    info['supervisord_status'] = processes
            except (subprocess.SubprocessError, FileNotFoundError) as e:
                # Subprocess errors (supervisorctl command not found or failed)
                logger.debug(f"Subprocess error getting supervisord status: {e}", exc_info=True)
                info['supervisord_status'] = {'error': 'supervisorctl not available'}
            except (ValueError, IndexError) as e:
                # Data parsing errors (status output parsing)
                logger.debug(f"Data parsing error parsing supervisord status: {e}", exc_info=True)
                info['supervisord_status'] = {'error': 'parse error'}
            
            # Check Docker socket availability
            try:
                info['docker_socket_available'] = os.path.exists('/var/run/docker.sock')
            except (OSError, PermissionError) as e:
                # File system errors (socket check failed)
                logger.debug(f"Error checking Docker socket: {e}", exc_info=True)
                info['docker_socket_available'] = False
            
            # Get DDC container-specific memory usage and image size
            if self.container_name and info['docker_socket_available']:
                try:
                    # Get container memory usage
                    result = subprocess.run([
                        'docker', 'stats', self.container_name, '--no-stream', '--format',
                        'table {{.MemUsage}}'
                    ], capture_output=True, text=True, timeout=10)
                    
                    if result.returncode == 0:
                        lines = result.stdout.strip().split('\n')
                        if len(lines) >= 2:  # Skip header line
                            mem_usage = lines[1].strip()
                            info['ddc_memory_usage'] = mem_usage
                    else:
                        info['ddc_memory_usage'] = 'unknown'
                except (subprocess.SubprocessError, FileNotFoundError) as e:
                    # Subprocess errors (docker stats command failed)
                    logger.debug(f"Subprocess error getting container memory stats: {e}", exc_info=True)
                    info['ddc_memory_usage'] = 'unknown'
                except (ValueError, IndexError) as e:
                    # Data parsing errors (stats output parsing)
                    logger.debug(f"Data parsing error parsing memory stats: {e}", exc_info=True)
                    info['ddc_memory_usage'] = 'unknown'
                
                try:
                    # Get image size
                    result = subprocess.run([
                        'docker', 'images', '--format', 'table {{.Repository}}:{{.Tag}}\t{{.Size}}',
                        '--filter', f'reference=*{self.container_name}*'
                    ], capture_output=True, text=True, timeout=10)
                    
                    if result.returncode == 0:
                        lines = result.stdout.strip().split('\n')
                        if len(lines) >= 2:  # Skip header line
                            # Try to find DDC image
                            for line in lines[1:]:
                                parts = line.split('\t')
                                if len(parts) >= 2:
                                    image_name = parts[0].lower()
                                    if 'dockerdiscordcontrol' in image_name or 'ddc' in image_name:
                                        info['ddc_image_size'] = parts[1].strip()
                                        break
                            
                            # If not found by name, try alternative approach
                            if not info['ddc_image_size']:
                                # Get image ID from container
                                result2 = subprocess.run([
                                    'docker', 'inspect', self.container_name, '--format', '{{.Image}}'
                                ], capture_output=True, text=True, timeout=5)
                                
                                if result2.returncode == 0:
                                    image_id = result2.stdout.strip()[:12]  # Short ID
                                    result3 = subprocess.run([
                                        'docker', 'images', '--format', 'table {{.ID}}\t{{.Size}}',
                                        '--filter', f'reference={image_id}'
                                    ], capture_output=True, text=True, timeout=5)
                                    
                                    if result3.returncode == 0:
                                        lines3 = result3.stdout.strip().split('\n')
                                        if len(lines3) >= 2:
                                            parts3 = lines3[1].split('\t')
                                            if len(parts3) >= 2:
                                                info['ddc_image_size'] = parts3[1].strip()
                    
                    if not info['ddc_image_size']:
                        info['ddc_image_size'] = 'unknown'

                except (subprocess.SubprocessError, FileNotFoundError) as e:
                    # Subprocess errors (docker images command failed)
                    logger.debug(f"Subprocess error getting image size: {e}", exc_info=True)
                    info['ddc_image_size'] = 'unknown'
                except (ValueError, IndexError) as e:
                    # Data parsing errors (image size parsing)
                    logger.debug(f"Data parsing error parsing image size: {e}", exc_info=True)
                    info['ddc_image_size'] = 'unknown'
                
            # Check if running on Unraid
            if os.path.exists('/etc/unraid-version') or os.path.exists('/boot/config/ident.cfg'):
                info['is_unraid'] = True
                info['platform'] = 'unraid'
            elif os.path.exists('/etc/os-release'):
                with open('/etc/os-release', 'r') as f:
                    content = f.read().lower()
                    if 'unraid' in content:
                        info['is_unraid'] = True
                        info['platform'] = 'unraid'
                    elif 'ubuntu' in content:
                        info['platform'] = 'ubuntu'
                    elif 'debian' in content:
                        info['platform'] = 'debian'
                    elif 'alpine' in content:
                        info['platform'] = 'alpine'
        except (IOError, OSError) as e:
            # File I/O errors (reading system files)
            logger.debug(f"File I/O error detecting host platform: {e}", exc_info=True)
        except (ValueError, AttributeError) as e:
            # Data processing errors (string parsing)
            logger.debug(f"Data processing error detecting host platform: {e}", exc_info=True)

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
    
    def _get_actual_host_ip(self) -> str:
        """Get the actual accessible IP address of the host."""
        try:
            import socket
            import subprocess
            
            # DEBUG: Log what methods we're trying
            logger.info("Starting IP detection (looking for host IP)...")
            
            # Method 0: Check environment variable first (fastest)
            import os
            host_ip_env = os.environ.get('HOST_IP') or os.environ.get('UNRAID_IP') or os.environ.get('SERVER_IP')
            if host_ip_env:
                logger.info(f"Using HOST_IP from environment: {host_ip_env}")
                return host_ip_env
            
            # Method 1: Traceroute to find the real host IP (brilliant idea!)
            try:
                logger.info("Trying traceroute method to find host IP...")
                # Traceroute to an external IP - the hops will show us the path
                # First hop is Docker bridge (172.17.0.1)
                # Second hop should be the real host IP!
                
                # Try traceroute (Alpine has it)
                try:
                    result = subprocess.run(['traceroute', '-n', '-m', '3', '-w', '1', '8.8.8.8'], 
                                          capture_output=True, text=True, timeout=5)
                    if result.returncode == 0 or result.stdout:
                        logger.info("Traceroute output received")
                        lines = result.stdout.split('\n')
                        
                        # Parse traceroute output
                        # Format: " 1  172.17.0.1  0.123 ms  0.045 ms  0.032 ms"
                        #         " 2  192.168.1.249  0.456 ms  0.234 ms  0.198 ms"
                        for line in lines:
                            line = line.strip()
                            if line and line[0].isdigit():
                                parts = line.split()
                                if len(parts) >= 2:
                                    hop_num = parts[0]
                                    hop_ip = parts[1]
                                    
                                    # Skip first hop (Docker gateway)
                                    if hop_num == '1' and hop_ip.startswith('172.17.'):
                                        logger.info(f"Hop 1: Docker gateway at {hop_ip}")
                                        continue
                                    
                                    # Second hop should be our host
                                    if hop_num == '2':
                                        if not hop_ip.startswith('172.17.') and not hop_ip.startswith('*'):
                                            logger.info(f"✅ Found host IP via traceroute: {hop_ip}")
                                            return hop_ip
                except FileNotFoundError:
                    # traceroute not found, try tracepath
                    logger.info("traceroute not found, trying tracepath...")
                    try:
                        result = subprocess.run(['tracepath', '-n', '8.8.8.8'], 
                                              capture_output=True, text=True, timeout=5)
                        if result.returncode == 0 or result.stdout:
                            for line in result.stdout.split('\n'):
                                # tracepath format: " 2:  192.168.1.249   0.456ms"
                                if line.strip() and line.strip()[0].isdigit():
                                    parts = line.strip().split()
                                    if len(parts) >= 2:
                                        hop_num = parts[0].rstrip(':')
                                        hop_ip = parts[1]
                                        
                                        if hop_num == '2' and not hop_ip.startswith('172.17.'):
                                            logger.info(f"✅ Found host IP via tracepath: {hop_ip}")
                                            return hop_ip
                    except (subprocess.SubprocessError, FileNotFoundError) as e:
                        # Subprocess errors (tracepath command failed)
                        logger.debug(f"Subprocess error with tracepath: {e}", exc_info=True)
                    except (ValueError, IndexError) as e:
                        # Data parsing errors (tracepath output parsing)
                        logger.debug(f"Data parsing error with tracepath: {e}", exc_info=True)

            except (subprocess.SubprocessError, FileNotFoundError) as e:
                # Subprocess errors (traceroute command failed)
                logger.debug(f"Subprocess error with traceroute method: {e}", exc_info=True)
            except (ValueError, IndexError) as e:
                # Data parsing errors (traceroute output parsing)
                logger.debug(f"Data parsing error with traceroute method: {e}", exc_info=True)
            
            # Method 2: Standard Docker host detection methods
            try:
                logger.info("Trying standard Docker host detection as fallback...")
                
                # First check /etc/hosts for Docker's standard entries
                try:
                    with open('/etc/hosts', 'r') as f:
                        hosts_content = f.read()
                        for line in hosts_content.split('\n'):
                            # Docker Desktop uses "host.docker.internal"
                            # Docker on Linux with --add-host uses "host-gateway"
                            if 'host.docker.internal' in line or 'host-gateway' in line:
                                parts = line.split()
                                if parts:
                                    host_ip = parts[0]
                                    # Validate it's not localhost
                                    if host_ip and not host_ip.startswith('127.'):
                                        logger.info(f"Found Docker host via /etc/hosts: {host_ip}")
                                        # On Linux, this might be 172.17.0.1, which is Docker bridge
                                        # We need to get the real external IP
                                        if host_ip == '172.17.0.1':
                                            logger.info("Host is Docker bridge, need real external IP...")
                                        else:
                                            return host_ip
                except (IOError, OSError) as e:
                    # File I/O errors (reading /etc/hosts)
                    logger.debug(f"File I/O error reading /etc/hosts: {e}", exc_info=True)
                except (ValueError, IndexError) as e:
                    # Data parsing errors (/etc/hosts parsing)
                    logger.debug(f"Data parsing error parsing /etc/hosts: {e}", exc_info=True)
                
                # Method 2: Get the host IP via route (works on Linux)
                # The host is accessible via the default gateway in bridge mode
                result = subprocess.run(['/sbin/ip', 'route'], capture_output=True, text=True, timeout=3)
                if result.returncode == 0:
                    # Parse route table for default gateway
                    for line in result.stdout.split('\n'):
                        if 'default' in line:
                            parts = line.split()
                            if 'via' in parts:
                                idx = parts.index('via')
                                if idx + 1 < len(parts):
                                    gateway = parts[idx + 1]
                                    logger.info(f"Docker host gateway: {gateway}")
                                    
                                    # On standard Linux Docker, the host is at 172.17.0.1
                                    # But we need the external IP, not the Docker bridge IP
                                    if gateway == '172.17.0.1':
                                        # This is the Docker bridge, we need the real host IP
                                        # Try to get the external IP that would be used to reach internet
                                        route_result = subprocess.run(['ip', 'route', 'get', '1.1.1.1'], 
                                                                    capture_output=True, text=True, timeout=3)
                                        if route_result.returncode == 0:
                                            # Extract source IP from output like:
                                            # "1.1.1.1 via 172.17.0.1 dev eth0 src 172.17.0.2 uid 1000"
                                            for word_idx, word in enumerate(route_result.stdout.split()):
                                                if word == 'src' and word_idx + 1 < len(route_result.stdout.split()):
                                                    src_ip = route_result.stdout.split()[word_idx + 1]
                                                    if src_ip == '172.17.0.2':
                                                        # This is our container IP, not helpful
                                                        # We need to find the actual host external IP
                                                        logger.info("Container is in bridge mode, checking for Unraid host...")
                                                        
                                                        # For Unraid, we'll need to check common IPs
                                                        # Since we can't see the host network from bridge mode
                                                        for host_ip in ['192.168.1.249', '192.168.0.249', '10.0.0.249']:
                                                            try:
                                                                # Quick test if this IP has our web service
                                                                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                                                                    s.settimeout(1)
                                                                    if s.connect_ex((host_ip, 8374)) == 0:
                                                                        logger.info(f"✅ Found Unraid host at {host_ip}")
                                                                        return host_ip
                                                            except (socket.error, OSError):
                                                                # Socket errors (host unreachable)
                                                                continue
                                                    break

            except (subprocess.SubprocessError, FileNotFoundError) as e:
                # Subprocess errors (ip route command failed)
                logger.debug(f"Subprocess error in gateway probe: {e}", exc_info=True)
            except (ValueError, IndexError, socket.error) as e:
                # Data parsing or socket errors
                logger.debug(f"Error in gateway probe method: {e}", exc_info=True)
            
            # Method 2: Smart ARP/neighbor table scanning (might work on host network mode)
            try:
                logger.info("Trying ARP table method as fallback...")
                # Try both arp and ip neigh commands (Alpine uses ip neigh)
                arp_result = None
                
                # Try ip neigh first (more common in containers)
                try:
                    result = subprocess.run(['ip', 'neigh'], capture_output=True, text=True, timeout=3)
                    if result.returncode == 0 and result.stdout:
                        arp_result = result.stdout
                        logger.info(f"Got neighbor table via 'ip neigh': {len(result.stdout)} bytes")
                        # Debug: show what's in the table
                        logger.debug(f"Neighbor table content: {result.stdout[:200]}")
                except (subprocess.SubprocessError, FileNotFoundError) as e:
                    # Subprocess errors (ip neigh command failed)
                    logger.debug(f"Subprocess error with ip neigh: {e}", exc_info=True)
                except (ValueError, AttributeError) as e:
                    # Data processing errors
                    logger.debug(f"Data error with ip neigh: {e}", exc_info=True)
                
                # Fallback to arp -a
                if not arp_result:
                    try:
                        result = subprocess.run(['arp', '-a'], capture_output=True, text=True, timeout=3)
                        if result.returncode == 0 and result.stdout:
                            arp_result = result.stdout
                            logger.info(f"Got ARP table via 'arp -a': {len(result.stdout)} bytes")
                    except (subprocess.SubprocessError, FileNotFoundError) as e:
                        # Subprocess errors (arp command failed)
                        logger.debug(f"Subprocess error with arp -a: {e}", exc_info=True)
                    except (ValueError, AttributeError) as e:
                        # Data processing errors
                        logger.debug(f"Data error with arp -a: {e}", exc_info=True)
                
                if arp_result:
                    logger.info(f"Parsing ARP/neighbor entries...")
                    # Parse ARP table looking for likely host IPs
                    host_candidates = []
                    for line in arp_result.split('\n'):
                        if '192.168.' in line or '10.0.' in line:
                            # Extract IP from different formats:
                            # arp -a: "? (192.168.1.249) at aa:bb:cc:dd:ee:ff [ether] on eth0"
                            # ip neigh: "192.168.1.249 dev eth0 lladdr aa:bb:cc:dd:ee:ff REACHABLE"
                            import re
                            
                            # Try both patterns
                            ip_match = re.search(r'\((\d+\.\d+\.\d+\.\d+)\)', line)  # arp format
                            if not ip_match:
                                ip_match = re.search(r'^(\d+\.\d+\.\d+\.\d+)\s', line)  # ip neigh format
                            
                            if ip_match:
                                potential_host = ip_match.group(1)
                                logger.info(f"Found potential host IP in ARP: {potential_host}")
                                # Test if this could be our Docker host
                                if self._test_if_this_is_our_host(potential_host):
                                    logger.info(f"✅ Confirmed {potential_host} is our Docker host!")
                                    return potential_host
                                host_candidates.append(potential_host)
                    
                    # If no host responded to port test, return the first reasonable candidate
                    if host_candidates:
                        logger.info(f"Found {len(host_candidates)} candidate IPs, selecting best one...")
                        # Prefer IPs ending with common Unraid server numbers
                        for suffix in ['.249', '.250', '.99', '.100']:
                            for ip in host_candidates:
                                if ip.endswith(suffix):
                                    logger.info(f"Selected {ip} based on common Unraid IP pattern")
                                    return ip
                        # Then try any non-gateway IP
                        for ip in host_candidates:
                            if not ip.endswith('.1') and not ip.endswith('.255'):
                                logger.info(f"Selected {ip} as non-gateway IP")
                                return ip
                        # Fallback to any candidate
                        logger.info(f"Using first candidate: {host_candidates[0]}")
                        return host_candidates[0]
                else:
                    logger.warning("No ARP/neighbor table data available")

            except (subprocess.SubprocessError, FileNotFoundError) as e:
                # Subprocess errors (ip/arp commands failed)
                logger.debug(f"Subprocess error in ARP scan: {e}", exc_info=True)
            except (ValueError, AttributeError, ImportError) as e:
                # Data parsing or import errors (regex module)
                logger.debug(f"Error in ARP scan method: {e}", exc_info=True)
            
            # Method 3: Docker gateway detection with network scanning
            try:
                # Get Docker gateway, then scan the same network for the likely host
                result = subprocess.run(['ip', 'route', 'show', 'default'], 
                                      capture_output=True, text=True, timeout=3)
                if result.returncode == 0:
                    gateway_ip = None
                    for line in result.stdout.strip().split('\n'):
                        if 'default via' in line:
                            gateway_ip = line.split()[2]
                            break
                    
                    if gateway_ip and gateway_ip.startswith('172.17'):
                        # This is Docker bridge gateway (172.17.0.1)
                        # The real host is likely on a different network that we can discover
                        # Try to find what network the host is actually on by checking interfaces
                        
                        # Check all network interfaces for non-Docker networks
                        iface_result = subprocess.run(['ip', 'addr', 'show'], 
                                                    capture_output=True, text=True, timeout=3)
                        if iface_result.returncode == 0:
                            for line in iface_result.stdout.split('\n'):
                                # Look for inet addresses that aren't Docker bridges
                                if 'inet ' in line and not '127.0' in line and not '172.17.' in line:
                                    import re
                                    ip_match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', line)
                                    if ip_match:
                                        ip = ip_match.group(1)
                                        if ip.startswith(('192.168.', '10.0.')):
                                            return ip

            except (subprocess.SubprocessError, FileNotFoundError) as e:
                # Subprocess errors (ip commands failed)
                logger.debug(f"Subprocess error in gateway scan: {e}", exc_info=True)
            except (ValueError, IndexError, ImportError, AttributeError) as e:
                # Data parsing or import errors
                logger.debug(f"Error in gateway scan method: {e}", exc_info=True)
            
            # Method 2: Try to get the Docker host IP via gateway, but validate it's external
            try:
                result = subprocess.run(['ip', 'route', 'show', 'default'], 
                                      capture_output=True, text=True, timeout=3)
                if result.returncode == 0:
                    for line in result.stdout.strip().split('\n'):
                        if 'default via' in line:
                            gateway_ip = line.split()[2]
                            # Only return if it's not a Docker internal network
                            if not gateway_ip.startswith(('172.17.', '172.18.')):
                                return gateway_ip
            except (subprocess.SubprocessError, FileNotFoundError) as e:
                # Subprocess errors (ip route command failed)
                logger.debug(f"Subprocess error getting default route: {e}", exc_info=True)
            except (ValueError, IndexError) as e:
                # Data parsing errors
                logger.debug(f"Data parsing error with default route: {e}", exc_info=True)
            
            # Method 3: Try to connect to a known external service to determine our IP
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.settimeout(3)
                    s.connect(('8.8.8.8', 80))
                    local_ip = s.getsockname()[0]
                    # Don't return localhost or Docker internal IPs
                    if not local_ip.startswith(('127.', '172.17.', '172.18.', '10.')):
                        return local_ip
            except (socket.error, OSError) as e:
                # Socket errors (connection failed)
                logger.debug(f"Socket error connecting to determine local IP: {e}", exc_info=True)
            except (ValueError, IndexError) as e:
                # Data errors (IP parsing)
                logger.debug(f"Data error determining local IP: {e}", exc_info=True)
            
            # Method 4: For Unraid, try to get the actual server IP from host network
            if self.host_info['is_unraid']:
                try:
                    # Try to access the host's network configuration via /proc/net
                    result = subprocess.run(['ip', 'addr', 'show'], 
                                          capture_output=True, text=True, timeout=3)
                    if result.returncode == 0:
                        # Look for ethernet interfaces with 192.168.x.x addresses
                        lines = result.stdout.split('\n')
                        for i, line in enumerate(lines):
                            if 'eth0' in line or 'enp' in line or 'ens' in line:
                                # Look at the next few lines for inet addresses
                                for j in range(i+1, min(i+5, len(lines))):
                                    if 'inet ' in lines[j] and '192.168.' in lines[j]:
                                        ip = lines[j].strip().split()[1].split('/')[0]
                                        return ip
                except (subprocess.SubprocessError, FileNotFoundError) as e:
                    # Subprocess errors (ip addr command failed)
                    logger.debug(f"Subprocess error getting Unraid network config: {e}", exc_info=True)
                except (ValueError, IndexError) as e:
                    # Data parsing errors
                    logger.debug(f"Data parsing error with Unraid network config: {e}", exc_info=True)
                
                try:
                    # Check /etc/hosts for unraid entries
                    with open('/etc/hosts', 'r') as f:
                        for line in f:
                            if 'unraid' in line.lower() or 'tower' in line.lower():
                                ip = line.split()[0]
                                if not ip.startswith('127.'):
                                    return ip
                except (IOError, OSError) as e:
                    # File I/O errors (reading /etc/hosts)
                    logger.debug(f"File I/O error reading /etc/hosts for Unraid: {e}", exc_info=True)
                except (ValueError, IndexError) as e:
                    # Data parsing errors
                    logger.debug(f"Data parsing error with /etc/hosts Unraid entries: {e}", exc_info=True)
            
            # Method 5: Check environment variables that might contain the IP  
            import os
            for env_var in ['HOST_IP', 'DOCKER_HOST_IP', 'SERVER_IP', 'UNRAID_IP']:
                if env_var in os.environ:
                    ip = os.environ[env_var]
                    if ip and not ip.startswith('127.'):
                        return ip
                        
            # Method 6: For Unraid specifically, check common configuration locations
            if self.host_info['is_unraid']:
                # Check if there's a Unraid-specific IP config file
                for config_path in ['/config/unraid_ip.txt', '/app/config/server_ip.txt']:
                    try:
                        with open(config_path, 'r') as f:
                            ip = f.read().strip()
                            if ip and not ip.startswith('127.'):
                                return ip
                    except (IOError, OSError) as e:
                        # File I/O errors (config file not found)
                        logger.debug(f"File I/O error reading config file {config_path}: {e}", exc_info=True)
                    except (ValueError, AttributeError) as e:
                        # Data errors (IP parsing)
                        logger.debug(f"Data error reading IP from {config_path}: {e}", exc_info=True)
                        
                # For Unraid systems, we can make an educated guess based on common networks
                # This is a fallback for when we can't detect the actual IP
                common_unraid_ips = ['192.168.1.249', '192.168.0.249', '10.0.0.249']
                for potential_ip in common_unraid_ips:
                    try:
                        # Quick test if this IP might be reachable
                        result = subprocess.run(['ping', '-c', '1', '-W', '1', potential_ip],
                                              capture_output=True, text=True, timeout=2)
                        if result.returncode == 0:
                            return potential_ip
                    except (subprocess.SubprocessError, FileNotFoundError) as e:
                        # Subprocess errors (ping command failed)
                        logger.debug(f"Subprocess error pinging {potential_ip}: {e}", exc_info=True)
                    except (ValueError, OSError) as e:
                        # Network or data errors
                        logger.debug(f"Error pinging {potential_ip}: {e}", exc_info=True)
            
            # Method 7: Last resort - try hostname resolution
            try:
                hostname = socket.gethostname()
                host_ip = socket.gethostbyname(hostname)
                if not host_ip.startswith('127.'):
                    return host_ip
            except (socket.error, socket.gaierror, OSError) as e:
                # Socket errors (hostname resolution failed)
                logger.debug(f"Socket error resolving hostname: {e}", exc_info=True)
            except (ValueError, AttributeError) as e:
                # Data errors
                logger.debug(f"Data error with hostname resolution: {e}", exc_info=True)

        except (ImportError, AttributeError) as e:
            # Import errors (socket, subprocess modules unavailable)
            logger.debug(f"Import error getting host IP: {e}", exc_info=True)
        except (ValueError, TypeError) as e:
            # Data processing errors
            logger.debug(f"Data error getting host IP: {e}", exc_info=True)
        
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