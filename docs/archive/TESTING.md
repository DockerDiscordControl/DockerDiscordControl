# DDC Testing Guide

Complete guide to testing DockerDiscordControl.

## Production Release Notice

**IMPORTANT**: The main branch is production-only as of v2.0.0 (2025-11-18). All testing infrastructure, test files, and development tooling have been removed from the main branch to create a clean production release.

**For Development**: Active development continues in the `v2.0` branch, which contains the complete testing infrastructure:
- Full test suite (unit, integration, performance, security tests)
- Test configuration files (pytest.ini, requirements-test.txt)
- CI/CD workflows (.github/workflows/)
- Code quality tools configuration

**To contribute or run tests**: Switch to the `v2.0` branch:
```bash
git checkout origin/v2.0
```

---

## Table of Contents

- [Overview](#overview)
- [Test Structure](#test-structure)
- [Running Tests](#running-tests)
- [Test Coverage](#test-coverage)
- [Writing Tests](#writing-tests)
- [Test Priorities](#test-priorities)
- [CI/CD Integration](#cicd-integration)

## Overview

**Note**: This documentation describes the testing infrastructure available in the `v2.0` development branch.

DDC follows a comprehensive testing strategy with multiple test levels:

```
┌─────────────────────────────────────┐
│          Test Pyramid               │
│                                     │
│              E2E Tests              │  ← Few, High Value
│         ┌─────────────────┐         │
│         │  Integration    │         │  ← Some, Medium Value
│     ┌───┴────────────────┴───┐     │
│     │     Unit Tests          │     │  ← Many, Fast
│ ┌───┴──────────────────────┴───┐   │
│ │    Performance Tests          │   │
│ └───────────────────────────────┘   │
└─────────────────────────────────────┘
```

### Current Status (Baseline)

- **Total Tests**: 36 tests
- **Estimated Coverage**: 5-10%
- **Tests per Service**: 0.72 average

### Target Status

- **Total Tests**: 150-200 tests
- **Target Coverage**: 80%+
- **Tests per Service**: 2-3 minimum

## Test Structure

**Note**: The test structure below exists in the `v2.0` development branch. The `tests/` directory has been removed from the main branch.

```
tests/  (Available in v2.0 branch only)
├── unit/                          # Unit tests (fast, isolated)
│   └── services/
│       ├── config/               # ConfigService tests (15 tests)
│       ├── docker/               # DockerService tests (20 tests)
│       ├── donation/             # DonationService tests (15 tests)
│       ├── mech/                 # MechService tests (25 tests)
│       └── scheduler/            # SchedulerService tests (20 tests)
├── integration/                   # Integration tests (slower, real dependencies)
│   ├── test_donation_flow.py    # End-to-end donation flow
│   └── test_docker_integration.py
├── performance/                   # Performance tests
│   ├── test_config_service_performance.py
│   ├── test_docker_async_queue_performance.py
│   └── test_mech_service_performance.py
├── e2e/                          # End-to-end tests (slowest, full system)
│   └── test_web_ui_e2e.py
├── security/                      # Security tests (SAST, dependency scanning)
│   └── test_security_sast.py
└── load/                         # Load testing (Locust)
    └── locustfile.py
```

## Running Tests

**Prerequisites**: Switch to the `v2.0` branch to access the test infrastructure:
```bash
git checkout origin/v2.0
pip install -r requirements-test.txt
```

### Run All Tests

```bash
# Run all tests
python -m pytest tests/

# Run with verbose output
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ --cov=services --cov=app --cov=utils --cov-report=html
```

### Run Specific Test Categories

```bash
# Unit tests only (fast)
python -m pytest tests/unit/ -v

# Integration tests
python -m pytest tests/integration/ -v

# Performance tests
python -m pytest tests/performance/ --benchmark-only

# E2E tests
python -m pytest tests/e2e/ -v

# Security tests
python -m pytest tests/security/ -v
```

### Run Tests for Specific Services

```bash
# ConfigService tests
python -m pytest tests/unit/services/config/ -v

# DockerService tests
python -m pytest tests/unit/services/docker/ -v

# DonationService tests
python -m pytest tests/unit/services/donation/ -v

# MechService tests
python -m pytest tests/unit/services/mech/ -v
```

### Run with Coverage

```bash
# Generate coverage report
python -m pytest tests/unit/ --cov=services --cov-report=term-missing

# Generate HTML coverage report
python -m pytest tests/unit/ --cov=services --cov-report=html
open htmlcov/index.html
```

### Run Parallel Tests

```bash
# Run tests in parallel (faster)
python -m pytest tests/unit/ -n auto
```

## Test Coverage

### Coverage Goals

| Component | Target Coverage | Priority |
|-----------|----------------|----------|
| ConfigService | 90%+ | Critical |
| DockerService | 85%+ | Critical |
| DonationService | 90%+ | Critical |
| MechService | 85%+ | Critical |
| SchedulerService | 80%+ | High |
| Web UI | 70%+ | Medium |
| Utilities | 80%+ | High |

### Measuring Coverage

```bash
# Generate coverage report
python -m pytest tests/ --cov=services --cov=app --cov=utils \
  --cov-report=term-missing \
  --cov-report=html \
  --cov-report=xml

# View HTML report
open htmlcov/index.html

# Coverage summary
coverage report -m
```

### Coverage Enforcement

**Note**: `pytest.ini` is available in the `v2.0` branch only.

pytest.ini configuration enforces minimum coverage:

```ini
[pytest]
addopts =
    --cov-fail-under=80
    --cov-report=term-missing
```

## Writing Tests

### Unit Test Template

```python
# tests/unit/services/my_service/test_my_service.py

import pytest
from unittest.mock import Mock, patch, MagicMock
from services.my_service import MyService, get_my_service

class TestMyService:
    """Unit tests for MyService."""

    @pytest.fixture
    def service(self):
        """Create MyService instance for testing."""
        return MyService()

    def test_service_initialization(self, service):
        """Test service initializes correctly."""
        assert service is not None
        assert hasattr(service, 'some_attribute')

    def test_some_method_success(self, service):
        """Test method succeeds with valid input."""
        result = service.some_method("valid_input")
        assert result == "expected_output"

    def test_some_method_invalid_input(self, service):
        """Test method raises error with invalid input."""
        with pytest.raises(ValueError, match="Invalid input"):
            service.some_method("invalid_input")

    @patch('services.my_service.external_dependency')
    def test_method_with_mocked_dependency(self, mock_dep, service):
        """Test method with mocked external dependency."""
        mock_dep.return_value = "mocked_value"

        result = service.method_using_dependency()

        assert result == "expected_result"
        mock_dep.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_method(self, service):
        """Test async method."""
        result = await service.async_method()
        assert result == "expected_result"
```

### Integration Test Template

```python
# tests/integration/test_my_integration.py

import pytest
from services.my_service import get_my_service
from services.other_service import get_other_service

class TestMyIntegration:
    """Integration tests for MyService with real dependencies."""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        """Setup and teardown for each test."""
        # Setup
        yield
        # Teardown

    def test_service_integration(self):
        """Test MyService integrates with OtherService."""
        my_service = get_my_service()
        other_service = get_other_service()

        # Execute integration
        result = my_service.integrate_with(other_service)

        # Verify
        assert result.success is True
        assert result.data is not None
```

### Performance Test Template

```python
# tests/performance/test_my_service_performance.py

import pytest
from services.my_service import MyService

class TestMyServicePerformance:
    """Performance tests for MyService."""

    @pytest.fixture
    def service(self):
        return MyService()

    def test_method_performance(self, service, benchmark):
        """Test method performance."""
        result = benchmark(service.some_method, "input")
        assert result is not None

    def test_method_latency(self, service):
        """Test method latency is under threshold."""
        import time

        iterations = 100
        start = time.time()

        for _ in range(iterations):
            service.some_method("input")

        duration = time.time() - start
        avg_latency_ms = (duration / iterations) * 1000

        assert avg_latency_ms < 10.0  # Under 10ms
```

## Test Priorities

### Priority 1: Critical Services (Must Have 80%+ Coverage)

**ConfigService** (15 tests minimum):
- ✅ Configuration loading from files
- ✅ Configuration caching
- ✅ Token encryption/decryption
- ✅ Configuration validation
- ✅ Error handling for missing/invalid configs

**DockerService** (20 tests minimum):
- ✅ Async queue system
- ✅ Container operations (start, stop, restart)
- ✅ Container status queries
- ✅ Error handling and retries
- ✅ Resource cleanup

**DonationService** (15 tests minimum):
- ✅ Donation processing (web, Discord, test)
- ✅ Validation logic
- ✅ Power calculations
- ✅ Event emission
- ✅ Error handling

**MechService** (25 tests minimum):
- ✅ Power calculation and decay
- ✅ Evolution tier calculation
- ✅ State management
- ✅ Animation generation
- ✅ Caching behavior

**SchedulerService** (20 tests minimum):
- ✅ Task scheduling
- ✅ Periodic task execution
- ✅ Task cancellation
- ✅ Error handling
- ✅ Concurrent task management

### Priority 2: Integration Tests (Critical Flows)

**Donation Flow** (5 tests):
- ✅ Web UI donation → Power update → Animation
- ✅ Discord donation → Member count → Power calculation
- ✅ Test donation → State verification
- ✅ Multiple donations → Cumulative effect
- ✅ Failed donation → Rollback

**Docker Operations** (5 tests):
- ✅ Container lifecycle (start → status → stop)
- ✅ Concurrent operations
- ✅ Error recovery
- ✅ Status caching
- ✅ Queue management

### Priority 3: E2E Tests (User Workflows)

**Web UI** (3 tests):
- ✅ Setup flow
- ✅ Donation submission
- ✅ Configuration changes

## ConfigService Test Examples

```python
# tests/unit/services/config/test_config_service.py

import pytest
from pathlib import Path
from services.config.config_service import ConfigService, get_config_service
from services.exceptions import ConfigLoadError, ConfigValidationError

class TestConfigService:
    """Unit tests for ConfigService."""

    @pytest.fixture
    def config_service(self, tmp_path):
        """Create ConfigService with temporary config files."""
        # Create test config files
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        (config_dir / "config.json").write_text('{"language": "de"}')
        (config_dir / "containers.json").write_text('{"containers": []}')
        (config_dir / "channels.json").write_text('{"channels": {}}')

        return ConfigService(config_dir=str(config_dir))

    def test_config_loading(self, config_service):
        """Test configuration loads successfully."""
        config = config_service.get_config()
        assert config is not None
        assert "language" in config

    def test_config_caching(self, config_service):
        """Test configuration is cached."""
        config1 = config_service.get_config()
        config2 = config_service.get_config()
        assert config1 is config2  # Same object

    def test_force_reload(self, config_service):
        """Test force reload bypasses cache."""
        config1 = config_service.get_config()
        config2 = config_service.get_config(force_reload=True)
        assert config1 is not config2  # Different objects

    def test_token_encryption(self, config_service):
        """Test token encryption/decryption."""
        plaintext = "my_secret_token"
        encrypted = config_service.encrypt_token(plaintext)

        assert encrypted != plaintext
        assert encrypted.startswith("ENC:")

        decrypted = config_service.decrypt_token(encrypted)
        assert decrypted == plaintext

    def test_missing_config_file(self, tmp_path):
        """Test error handling for missing config file."""
        with pytest.raises(ConfigLoadError, match="not found"):
            ConfigService(config_dir=str(tmp_path / "nonexistent"))

    # ... 10 more tests for validation, updates, error cases, etc.
```

## DonationService Test Examples

```python
# tests/unit/services/donation/test_unified_donation_service.py

import pytest
from services.donation.unified.service import UnifiedDonationService
from services.donation.unified.models import DonationRequest, DonationResult

class TestUnifiedDonationService:
    """Unit tests for UnifiedDonationService."""

    @pytest.fixture
    def service(self):
        """Create service instance."""
        return UnifiedDonationService()

    def test_process_donation_success(self, service):
        """Test successful donation processing."""
        request = DonationRequest(
            donor_name="Test Donor",
            amount=5.0,
            source="test"
        )

        result = service.process_donation(request)

        assert result.success is True
        assert result.new_state is not None
        assert result.new_state.current_power > 0

    def test_process_donation_invalid_amount(self, service):
        """Test donation with invalid amount."""
        request = DonationRequest(
            donor_name="Test Donor",
            amount=-5.0,  # Invalid
            source="test"
        )

        result = service.process_donation(request)

        assert result.success is False
        assert "VALIDATION_FAILED" in result.error_code

    @pytest.mark.asyncio
    async def test_process_donation_async(self, service):
        """Test async donation processing."""
        request = DonationRequest(
            donor_name="Test Donor",
            amount=5.0,
            source="discord"
        )

        result = await service.process_donation_async(request)

        assert result.success is True

    # ... 12 more tests for different scenarios, error cases, edge cases
```

## MechService Test Examples

```python
# tests/unit/services/mech/test_mech_service.py

import pytest
from datetime import datetime, timezone
from services.mech.mech_service import MechService
from services.mech.models import MechState

class TestMechService:
    """Unit tests for MechService."""

    @pytest.fixture
    def service(self):
        """Create service instance."""
        return MechService()

    def test_power_calculation(self, service):
        """Test power calculation from donations."""
        # Create test state with known donation time
        state = MechState(
            total_donations=50.0,
            last_donation_time=datetime.now(timezone.utc)
        )

        power = service.calculate_current_power(state)

        assert power == 50.0

    def test_power_decay(self, service):
        """Test continuous power decay calculation."""
        # State with donation 12 hours ago
        from datetime import timedelta
        twelve_hours_ago = datetime.now(timezone.utc) - timedelta(hours=12)

        state = MechState(
            total_donations=50.0,
            last_donation_time=twelve_hours_ago
        )

        power = service.calculate_current_power(state)

        # After 12 hours, power should have decayed by 0.5 (12/24)
        assert power == pytest.approx(49.5, rel=0.01)

    def test_evolution_tier_calculation(self, service):
        """Test evolution tier based on power."""
        assert service.calculate_evolution_tier(0) == 0
        assert service.calculate_evolution_tier(10) == 1
        assert service.calculate_evolution_tier(50) == 2
        assert service.calculate_evolution_tier(100) == 3

    # ... 22 more tests for different calculations, caching, animations, etc.
```

## CI/CD Integration

**Note**: GitHub Actions workflows (`.github/workflows/`) are available in the `v2.0` branch only. The main branch is production-focused and does not include CI/CD workflows.

In the `v2.0` development branch, tests run automatically in GitHub Actions:

```yaml
# .github/workflows/tests.yml (v2.0 branch only)

name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -r requirements-test.txt

      - name: Run unit tests with coverage
        run: |
          python -m pytest tests/unit/ \
            --cov=services \
            --cov=app \
            --cov=utils \
            --cov-report=xml \
            --cov-report=term-missing \
            --cov-fail-under=80

      - name: Upload coverage to Codecov
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml
```

## Best Practices

### 1. Test Naming

```python
# ✅ Good: Descriptive test names
def test_config_loading_succeeds_with_valid_file():
    pass

def test_donation_processing_fails_with_negative_amount():
    pass

# ❌ Bad: Vague test names
def test_config():
    pass

def test_donation():
    pass
```

### 2. Test Independence

```python
# ✅ Good: Each test is independent
class TestMyService:
    @pytest.fixture
    def service(self):
        return MyService()  # Fresh instance per test

    def test_method_a(self, service):
        service.method_a()
        assert service.state == "expected"

    def test_method_b(self, service):
        service.method_b()
        assert service.state == "expected"

# ❌ Bad: Tests depend on execution order
class TestMyService:
    service = MyService()  # Shared instance

    def test_method_a(self):
        self.service.method_a()
        assert self.service.state == "expected"

    def test_method_b(self):
        # Depends on test_method_a running first
        self.service.method_b()
        assert self.service.state == "expected"
```

### 3. Use Fixtures

```python
# ✅ Good: Use fixtures for setup
@pytest.fixture
def mock_config():
    return {"language": "de", "debug": False}

@pytest.fixture
def service(mock_config):
    return MyService(mock_config)

def test_service_operation(service):
    result = service.operate()
    assert result == "expected"

# ❌ Bad: Duplicate setup in each test
def test_service_operation():
    config = {"language": "de", "debug": False}
    service = MyService(config)
    result = service.operate()
    assert result == "expected"
```

### 4. Test Error Cases

```python
# ✅ Good: Test both success and failure
def test_donation_success(service):
    result = service.process(amount=5.0)
    assert result.success is True

def test_donation_invalid_amount(service):
    with pytest.raises(ValueError, match="Amount must be positive"):
        service.process(amount=-5.0)

def test_donation_missing_donor(service):
    with pytest.raises(ValueError, match="Donor name required"):
        service.process(donor_name=None, amount=5.0)

# ❌ Bad: Only test success path
def test_donation(service):
    result = service.process(amount=5.0)
    assert result.success is True
```

### 5. Mock External Dependencies

```python
# ✅ Good: Mock external dependencies
@patch('services.my_service.external_api')
def test_api_call(mock_api, service):
    mock_api.return_value = {"status": "success"}

    result = service.call_external_api()

    assert result == "success"
    mock_api.assert_called_once()

# ❌ Bad: Rely on external dependencies
def test_api_call(service):
    # Fails if external API is down
    result = service.call_external_api()
    assert result == "success"
```

## Troubleshooting

### Tests Not Found

**Problem**: pytest cannot find tests

**Solution**:
```bash
# Ensure test files start with test_
# Ensure test functions start with test_
# Run from project root
python -m pytest tests/ -v
```

### Import Errors

**Problem**: ModuleNotFoundError in tests

**Solution**:
```python
# Add to tests/conftest.py
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
```

### Fixture Not Found

**Problem**: fixture 'xyz' not found

**Solution**:
```python
# Ensure fixture is in conftest.py or same file
# Check fixture scope (function, class, module, session)
@pytest.fixture(scope="function")
def my_fixture():
    return "value"
```

## See Also

- [PERFORMANCE.md](PERFORMANCE.md) - Performance testing guide
- [CODE_QUALITY.md](CODE_QUALITY.md) - Code quality standards
- [CONTRIBUTING.md](CONTRIBUTING.md) - Contribution guidelines
- [SERVICES.md](SERVICES.md) - Service architecture

## External Resources

- **pytest Documentation**: https://docs.pytest.org/
- **pytest-cov**: https://pytest-cov.readthedocs.io/
- **pytest-asyncio**: https://pytest-asyncio.readthedocs.io/
- **unittest.mock**: https://docs.python.org/3/library/unittest.mock.html
