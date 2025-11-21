# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Security Test Helpers                          #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Helper utilities for security testing.
"""

import re
import os
from pathlib import Path
from typing import List, Dict, Any, Optional


class SecurityTestHelper:
    """Helper class for security testing operations."""

    def __init__(self):
        self.project_root = Path(__file__).parent.parent.parent

    def scan_for_patterns(
        self,
        directory: Path,
        patterns: List[str],
        file_extensions: Optional[List[str]] = None,
        exclude_dirs: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Scan directory for regex patterns in files.

        Args:
            directory: Directory to scan
            patterns: List of regex patterns to search for
            file_extensions: File extensions to include (e.g., ['.py', '.js'])
            exclude_dirs: Directories to exclude from scanning

        Returns:
            List of findings with file, line number, and match
        """
        findings = []
        exclude_dirs = exclude_dirs or []

        # Compile patterns for efficiency
        compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]

        for file_path in self._get_files_to_scan(directory, file_extensions, exclude_dirs):
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()

                for line_num, line in enumerate(lines, 1):
                    for pattern in compiled_patterns:
                        matches = pattern.findall(line)
                        for match in matches:
                            findings.append({
                                'file': str(file_path),
                                'line': line_num,
                                'match': match if isinstance(match, str) else line.strip(),
                                'pattern': pattern.pattern
                            })
            except (IOError, UnicodeDecodeError):
                # Skip files that can't be read
                continue

        return findings

    def _get_files_to_scan(
        self,
        directory: Path,
        file_extensions: Optional[List[str]] = None,
        exclude_dirs: Optional[List[str]] = None
    ) -> List[Path]:
        """Get list of files to scan based on criteria."""
        files = []
        exclude_dirs = exclude_dirs or []

        for root, dirs, filenames in os.walk(directory):
            # Remove excluded directories from dirs list to prevent traversal
            dirs[:] = [d for d in dirs if d not in exclude_dirs]

            for filename in filenames:
                file_path = Path(root) / filename

                # Skip files in excluded directories (double check)
                if any(exclude_dir in str(file_path) for exclude_dir in exclude_dirs):
                    continue

                # Filter by file extensions if specified
                if file_extensions:
                    if not any(filename.endswith(ext) for ext in file_extensions):
                        continue

                files.append(file_path)

        return files

    def check_file_permissions(self, file_path: Path) -> Dict[str, Any]:
        """Check file permissions for security issues."""
        try:
            stat = file_path.stat()
            mode = stat.st_mode

            return {
                'path': str(file_path),
                'owner_read': bool(mode & 0o400),
                'owner_write': bool(mode & 0o200),
                'owner_execute': bool(mode & 0o100),
                'group_read': bool(mode & 0o040),
                'group_write': bool(mode & 0o020),
                'group_execute': bool(mode & 0o010),
                'other_read': bool(mode & 0o004),
                'other_write': bool(mode & 0o002),
                'other_execute': bool(mode & 0o001),
                'world_writable': bool(mode & 0o002),
                'world_readable': bool(mode & 0o004),
                'executable': bool(mode & 0o111),
            }
        except OSError:
            return {'path': str(file_path), 'error': 'Cannot read file permissions'}

    def find_sensitive_files(self, directory: Path) -> List[Dict[str, str]]:
        """Find potentially sensitive files."""
        sensitive_patterns = [
            r'.*\.key$',
            r'.*\.pem$',
            r'.*\.crt$',
            r'.*\.p12$',
            r'.*\.pfx$',
            r'.*password.*',
            r'.*secret.*',
            r'.*\.env.*',
            r'.*config.*\.json$',
            r'.*\.sqlite$',
            r'.*\.db$',
        ]

        findings = []
        compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in sensitive_patterns]

        for file_path in directory.rglob('*'):
            if file_path.is_file():
                filename = file_path.name

                for pattern in compiled_patterns:
                    if pattern.match(filename):
                        findings.append({
                            'file': str(file_path),
                            'reason': f'Matches pattern: {pattern.pattern}',
                            'type': 'sensitive_filename'
                        })
                        break

        return findings

    def check_dependency_vulnerabilities(self) -> List[Dict[str, Any]]:
        """Check for known vulnerabilities in dependencies."""
        findings = []
        requirements_files = [
            'requirements.txt',
            'requirements-dev.txt',
            'requirements-test.txt',
            'Pipfile',
            'poetry.lock',
            'package.json',
        ]

        for req_file in requirements_files:
            req_path = self.project_root / req_file
            if req_path.exists():
                findings.append({
                    'file': str(req_path),
                    'message': f'Dependencies file found: {req_file}',
                    'recommendation': f'Run security audit on {req_file}',
                })

        return findings

    def validate_security_headers(self, headers: Dict[str, str]) -> List[Dict[str, str]]:
        """Validate HTTP security headers."""
        issues = []

        required_headers = {
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': ['DENY', 'SAMEORIGIN'],
            'X-XSS-Protection': '1; mode=block',
            'Strict-Transport-Security': None,  # Any value is good
            'Content-Security-Policy': None,
        }

        for header, expected_value in required_headers.items():
            if header not in headers:
                issues.append({
                    'header': header,
                    'issue': 'Missing security header',
                    'recommendation': f'Add {header} header'
                })
            elif expected_value is not None:
                actual_value = headers[header]
                if isinstance(expected_value, list):
                    if actual_value not in expected_value:
                        issues.append({
                            'header': header,
                            'issue': f'Invalid value: {actual_value}',
                            'recommendation': f'Use one of: {expected_value}'
                        })
                elif actual_value != expected_value:
                    issues.append({
                        'header': header,
                        'issue': f'Invalid value: {actual_value}',
                        'recommendation': f'Use: {expected_value}'
                    })

        return issues

    def check_cors_configuration(self, cors_origins: List[str]) -> List[Dict[str, str]]:
        """Check CORS configuration for security issues."""
        issues = []

        # Check for overly permissive CORS
        if '*' in cors_origins:
            issues.append({
                'issue': 'Wildcard CORS origin allowed',
                'risk': 'HIGH',
                'recommendation': 'Specify exact origins instead of using *'
            })

        # Check for localhost in production
        localhost_patterns = ['localhost', '127.0.0.1', '0.0.0.0']
        for origin in cors_origins:
            if any(pattern in origin for pattern in localhost_patterns):
                issues.append({
                    'issue': f'Localhost origin in CORS: {origin}',
                    'risk': 'MEDIUM',
                    'recommendation': 'Remove localhost origins in production'
                })

        return issues

    def analyze_authentication_strength(self, auth_config: Dict[str, Any]) -> List[Dict[str, str]]:
        """Analyze authentication configuration for security weaknesses."""
        issues = []

        # Check password requirements
        if 'password_min_length' in auth_config:
            min_length = auth_config['password_min_length']
            if min_length < 8:
                issues.append({
                    'issue': f'Password minimum length too short: {min_length}',
                    'recommendation': 'Use minimum 8 characters for passwords'
                })

        # Check session timeout
        if 'session_timeout' in auth_config:
            timeout = auth_config['session_timeout']
            if timeout > 24 * 60 * 60:  # 24 hours in seconds
                issues.append({
                    'issue': f'Session timeout too long: {timeout} seconds',
                    'recommendation': 'Use shorter session timeouts for security'
                })

        # Check for secure cookie settings
        cookie_config = auth_config.get('cookie_config', {})
        if not cookie_config.get('secure', False):
            issues.append({
                'issue': 'Cookies not marked as secure',
                'recommendation': 'Set secure=True for cookies in production'
            })

        if not cookie_config.get('httponly', True):
            issues.append({
                'issue': 'Cookies accessible via JavaScript',
                'recommendation': 'Set httponly=True for authentication cookies'
            })

        return issues


class SecurityAssertions:
    """Custom assertions for security testing."""

    @staticmethod
    def assert_no_sensitive_data_in_logs(log_content: str):
        """Assert that logs don't contain sensitive data."""
        sensitive_patterns = [
            r'password["\s]*[:=]["\s]*[^\s"]+',
            r'token["\s]*[:=]["\s]*[^\s"]+',
            r'secret["\s]*[:=]["\s]*[^\s"]+',
            r'api_key["\s]*[:=]["\s]*[^\s"]+',
        ]

        for pattern in sensitive_patterns:
            matches = re.findall(pattern, log_content, re.IGNORECASE)
            if matches:
                raise AssertionError(f"Sensitive data found in logs: {matches}")

    @staticmethod
    def assert_proper_error_handling(response_data: str):
        """Assert that error responses don't leak sensitive information."""
        # Should not contain stack traces in production
        sensitive_error_patterns = [
            r'Traceback \(most recent call last\):',
            r'File ".*\.py", line \d+',
            r'Exception: .*',
            r'Error: .*\.py',
        ]

        for pattern in sensitive_error_patterns:
            if re.search(pattern, response_data):
                raise AssertionError(f"Error response contains sensitive information: {pattern}")

    @staticmethod
    def assert_secure_redirect(redirect_url: str, allowed_domains: List[str]):
        """Assert that redirects only go to allowed domains."""
        if redirect_url.startswith('http'):
            from urllib.parse import urlparse
            parsed = urlparse(redirect_url)

            if parsed.netloc not in allowed_domains:
                raise AssertionError(f"Redirect to untrusted domain: {parsed.netloc}")


# Utility functions for common security checks
def is_hash_secure(hash_value: str) -> bool:
    """Check if a hash value appears to use a secure algorithm."""
    # bcrypt hashes start with $2a$, $2b$, etc.
    if hash_value.startswith(('$2a$', '$2b$', '$2x$', '$2y$')):
        return True

    # Argon2 hashes start with $argon2
    if hash_value.startswith('$argon2'):
        return True

    # PBKDF2 hashes are longer and contain multiple parts
    if len(hash_value) > 50 and '$' in hash_value:
        return True

    return False


def check_encryption_strength(encrypted_data: str) -> Dict[str, Any]:
    """Check encryption strength based on observable characteristics."""
    return {
        'length': len(encrypted_data),
        'appears_base64': all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=' for c in encrypted_data),
        'has_sufficient_entropy': len(set(encrypted_data)) > len(encrypted_data) * 0.4,
        'not_plaintext': encrypted_data != encrypted_data.lower() and encrypted_data != encrypted_data.upper(),
    }
