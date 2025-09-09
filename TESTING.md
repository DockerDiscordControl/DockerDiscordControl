# DDC Testing Documentation

This document describes the comprehensive testing framework for DockerDiscordControl (DDC).

## Overview

DDC uses a multi-layered testing approach to ensure code quality, security, and performance:

- **Unit Tests**: Test individual components in isolation
- **Integration Tests**: Test component interactions with real systems
- **End-to-End Tests**: Test complete user workflows through the browser
- **Security Tests**: Static and dynamic security analysis (SAST/DAST)
- **Performance Tests**: Benchmarking and load testing
- **Load Tests**: Realistic user simulation with Locust

## Quick Start

### Run All Tests

```bash
# Run all test suites
./scripts/run_tests.sh --all

# Run specific test types
./scripts/run_tests.sh --unit --integration
./scripts/run_tests.sh --security --performance
```

### Run Tests Manually

```bash
# Unit tests only
python -m pytest tests/unit/ -v

# Integration tests
python -m pytest tests/integration/ -v -m integration

# With coverage
python -m pytest --cov=app --cov=cogs --cov=services --cov=utils
```

## Test Structure

```
tests/
├── conftest.py                 # Global fixtures and configuration
├── unit/                       # Unit tests
│   ├── services/               # Service layer tests
│   ├── cogs/                   # Discord cog tests
│   ├── app/                    # Web UI tests
│   └── utils/                  # Utility function tests
├── integration/                # Integration tests
│   ├── test_docker_api_integration.py
│   └── test_web_api_integration.py
├── e2e/                        # End-to-end tests
│   └── test_web_ui_e2e.py
├── security/                   # Security tests
│   ├── test_security_sast.py
│   └── security_test_helpers.py
├── performance/                # Performance tests
│   └── test_performance.py
└── load/                       # Load testing
    └── locustfile.py
```

## Unit Tests

Unit tests focus on individual components and functions. They use mocks to isolate the system under test.

### Example Unit Test

```python
@patch('services.docker.docker_service.get_docker_client')
def test_get_containers_success(self, mock_get_client):
    # Arrange
    mock_client = Mock()
    mock_client.containers.list.return_value = [mock_container]
    mock_get_client.return_value = mock_client
    
    # Act
    result = self.service.get_containers()
    
    # Assert
    assert result.success is True
    assert len(result.data) == 1
```

### Running Unit Tests

```bash
# All unit tests
python -m pytest tests/unit/ -v

# Specific service tests
python -m pytest tests/unit/services/test_donation_management_service.py -v

# With coverage
python -m pytest tests/unit/ --cov=services --cov-report=html
```

## Integration Tests

Integration tests verify interactions between components and with real external systems (Docker daemon, databases, etc.).

### Docker Integration Tests

These tests require a running Docker daemon:

```bash
# Run Docker integration tests
python -m pytest tests/integration/ -v -m docker

# Skip if Docker not available
python -m pytest tests/integration/ -v -m "integration and not docker"
```

### Prerequisites

- Docker daemon running
- Test containers can be created/destroyed
- Sufficient permissions for Docker operations

## End-to-End Tests

E2E tests simulate complete user workflows using Selenium WebDriver.

### Prerequisites

```bash
# Install Chrome/Chromium
sudo apt-get install chromium-browser  # Ubuntu
brew install --cask google-chrome      # macOS

# Install ChromeDriver
pip install chromedriver-autoinstaller
```

### Running E2E Tests

```bash
# Headless browser testing
python -m pytest tests/e2e/ -v -m e2e

# With visible browser (for debugging)
python -m pytest tests/e2e/ -v -m e2e --headed
```

### Test Scenarios

- User login/logout
- Container management through UI
- Responsive design testing
- JavaScript error detection
- Basic accessibility checks

## Security Tests

Security tests use static analysis (SAST) to identify vulnerabilities in source code.

### Tools Used

- **Bandit**: Python security linter
- **Custom patterns**: SQL injection, XSS, command injection detection
- **Dependency scanning**: Known vulnerability detection

### Running Security Tests

```bash
# All security tests
python -m pytest tests/security/ -v -m security

# Bandit scan only
bandit -r . -f json -ll --exclude tests/

# Custom security patterns
python -m pytest tests/security/test_security_sast.py::TestSASTSecurityScanning::test_sql_injection_patterns -v
```

### Security Test Categories

1. **Static Code Analysis**
   - Hardcoded secrets detection
   - SQL injection patterns
   - Command injection vulnerabilities
   - XSS vulnerability patterns
   - Insecure deserialization

2. **Configuration Security**
   - Encryption strength validation
   - Authentication configuration
   - Session security settings

3. **Input Validation**
   - Web form validation
   - API endpoint security
   - Path traversal protection

## Performance Tests

Performance tests measure system performance under various conditions using pytest-benchmark.

### Running Performance Tests

```bash
# All performance tests
python -m pytest tests/performance/ -v -m performance --benchmark-only

# Specific benchmarks
python -m pytest tests/performance/ -v -k "docker" --benchmark-sort=mean

# Memory profiling
python -m pytest tests/performance/ -v --benchmark-histogram
```

### Performance Metrics

- Container operation latency
- Memory usage under load
- Concurrent operation throughput
- Web UI response times
- Database query performance

## Load Testing

Load testing simulates realistic user behavior using Locust.

### Running Load Tests

```bash
# Start DDC web server
DDC_WEB_PORT=5001 python -m app.web_ui &

# Run load tests
locust -f tests/load/locustfile.py --host=http://localhost:5001

# Headless load test
locust -f tests/load/locustfile.py --host=http://localhost:5001 \
       --users=50 --spawn-rate=5 --run-time=300s --headless
```

### Load Test Scenarios

1. **Normal Web Users** (`DDCWebUser`): Typical web UI interactions
2. **API Users** (`DDCAPIUser`): API-heavy usage patterns
3. **Heavy Users** (`DDCHeavyUser`): Stress testing scenarios
4. **Mobile Users** (`DDCMobileUser`): Mobile-specific behavior
5. **Stress Test** (`StressTestUser`): System limit testing

### Load Test Reports

Locust generates detailed HTML reports with:
- Request statistics
- Response time percentiles
- Failure analysis
- Charts and graphs

## Test Configuration

### pytest.ini

Main pytest configuration file:

```ini
[tool:pytest]
testpaths = tests
python_files = test_*.py *_test.py
python_classes = Test* *Tests
python_functions = test_*

# Test markers
markers =
    unit: Unit tests
    integration: Integration tests
    e2e: End-to-end tests
    security: Security tests
    performance: Performance tests
    slow: Slow running tests
    docker: Tests requiring Docker daemon
```

### Environment Variables

Set these environment variables for testing:

```bash
export TESTING=true
export DDC_LOG_LEVEL=DEBUG
export DDC_WEB_PORT=5001
```

### Test Dependencies

Install test dependencies:

```bash
pip install -r requirements-test.txt
```

Key dependencies:
- `pytest`: Test framework
- `pytest-asyncio`: Async test support
- `pytest-cov`: Coverage reporting
- `pytest-benchmark`: Performance testing
- `selenium`: Browser automation
- `locust`: Load testing
- `bandit`: Security scanning

## CI/CD Integration

### GitHub Actions Example

```yaml
name: DDC Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v2
    
    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: '3.9'
    
    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install -r requirements-test.txt
    
    - name: Run unit tests
      run: ./scripts/run_tests.sh --unit
    
    - name: Run security tests
      run: ./scripts/run_tests.sh --security
    
    - name: Upload coverage
      uses: codecov/codecov-action@v1
```

## Test Data and Fixtures

### Global Fixtures (conftest.py)

- `mock_docker_client`: Mock Docker daemon
- `mock_discord_ctx`: Mock Discord interaction context
- `sample_config`: Test configuration data
- `temp_config_dir`: Temporary directory for config files

### Test Data Management

- Use factories for creating test objects
- Isolate test data per test
- Clean up after each test
- Use meaningful test data that reflects real usage

## Debugging Tests

### Common Commands

```bash
# Run with verbose output
python -m pytest -v -s

# Run specific test
python -m pytest tests/unit/services/test_docker_service.py::TestDockerService::test_get_containers -v

# Drop into debugger on failure
python -m pytest --pdb

# Run last failed tests
python -m pytest --lf

# Show test coverage gaps
python -m pytest --cov=app --cov-report=term-missing
```

### Test Debugging Tips

1. Use `pytest.set_trace()` for debugging
2. Run tests with `-s` flag to see print statements
3. Use `--pdb-trace` to debug from test start
4. Mock external dependencies consistently
5. Check fixture scope and cleanup

## Best Practices

### Writing Tests

1. **Follow AAA pattern**: Arrange, Act, Assert
2. **One assertion per test**: Focus on single behavior
3. **Descriptive test names**: Clearly state what is being tested
4. **Independent tests**: Tests should not depend on each other
5. **Mock external dependencies**: Isolate system under test

### Test Organization

1. **Group related tests**: Use test classes for related functionality
2. **Use appropriate markers**: Mark tests by type and requirements
3. **Maintain test data**: Keep test fixtures clean and meaningful
4. **Document complex tests**: Add docstrings for complex test scenarios

### Performance Considerations

1. **Fast unit tests**: Mock heavy operations
2. **Selective integration tests**: Only test critical paths
3. **Parallel execution**: Use pytest-xdist for speed
4. **Resource cleanup**: Prevent test interference

## Continuous Testing

### Pre-commit Hooks

Set up pre-commit hooks to run tests automatically:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: unit-tests
        name: Unit Tests
        entry: python -m pytest tests/unit/ -x
        language: system
        pass_filenames: false
        
      - id: security-scan
        name: Security Scan
        entry: bandit -r . -ll --exclude tests/
        language: system
        pass_filenames: false
```

### Test Metrics

Track these testing metrics:
- Test coverage percentage
- Test execution time
- Number of tests per component
- Flaky test identification
- Performance regression detection

## Troubleshooting

### Common Issues

1. **Docker tests failing**: Ensure Docker daemon is running
2. **E2E tests timing out**: Increase wait times or use explicit waits
3. **Permission errors**: Check file/directory permissions
4. **Import errors**: Verify PYTHONPATH includes project root
5. **Mock issues**: Ensure mocks match real interface

### Getting Help

- Check test logs in `reports/` directory
- Run with verbose output for detailed information
- Isolate failing tests to understand root cause
- Review mock configurations for correctness

## Future Enhancements

Planned testing improvements:
- Visual regression testing
- API contract testing
- Chaos engineering tests
- Multi-browser E2E testing
- Performance baseline tracking