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
            return hostname if hostname else "DockerDiscordControl"
        except Exception as e:
            logger.debug(f"Could not detect container name: {e}")
            return "DockerDiscordControl"
    
    def _get_host_info(self) -> Dict:
        """Get host system information"""
        info = {
            'platform': 'unknown',
            'is_unraid': False,
            'is_docker': True if os.path.exists('/.dockerenv') else False
        }
        
        try:
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
        except Exception as e:
            logger.debug(f"Could not detect host platform: {e}")
        
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
        except Exception:
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
        except Exception as e:
            logger.debug(f"Could not get Docker port mappings: {e}")
            return {}
    
    def _get_unraid_solutions(self) -> List[str]:
        """Get Unraid-specific solutions"""
        return [
            "UNRAID FIX: Go to Docker tab → Edit DDC container → Set 'Host Port: 8374' and 'Container Port: 9374'",
            "UNRAID FIX: Remove container and re-install from Community Apps with correct port mapping",
            "UNRAID FIX: Verify template shows: WebUI Port - Host: 8374, Container: 9374",
            f"UNRAID MANUAL: docker run -d --name {self.container_name or 'DockerDiscordControl'} -p 8374:9374 -v /var/run/docker.sock:/var/run/docker.sock dockerdiscordcontrol/dockerdiscordcontrol:latest"
        ]
    
    def _get_docker_solutions(self) -> List[str]:
        """Get generic Docker solutions"""
        return [
            f"DOCKER FIX: Add port mapping: -p 8374:{self.EXPECTED_WEB_PORT}",
            f"DOCKER FIX: Recreate container with: docker run -d --name {self.container_name or 'DockerDiscordControl'} -p 8374:{self.EXPECTED_WEB_PORT} dockerdiscordcontrol/dockerdiscordcontrol:latest",
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
        
        # Log access information
        if report['port_check']['external_ports']:
            for port_info in report['port_check']['external_ports']:
                if isinstance(port_info, dict):
                    logger.info(f"Web UI should be accessible at: http://{port_info['host']}:{port_info['port']}")
                else:
                    logger.info(f"Web UI should be accessible at: http://localhost:{port_info}")
        elif self.host_info['is_unraid']:
            logger.info("Web UI should be accessible at: http://[UNRAID-IP]:8374")
        else:
            logger.info("Web UI should be accessible at: http://localhost:8374")
        
        logger.info("=== End Diagnostics ===")
        
        return report


def run_port_diagnostics() -> Dict:
    """Convenience function to run diagnostics"""
    diagnostics = PortDiagnostics()
    return diagnostics.get_diagnostic_report()


def log_port_diagnostics():
    """Convenience function to log diagnostics at startup"""
    diagnostics = PortDiagnostics()
    return diagnostics.log_startup_diagnostics()