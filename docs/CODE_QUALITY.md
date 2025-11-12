# DDC Code Quality Guide

Complete guide to code quality standards, tools, and best practices for DockerDiscordControl.

## Table of Contents

- [Overview](#overview)
- [Quality Standards](#quality-standards)
- [Code Quality Tools](#code-quality-tools)
- [Running Quality Checks](#running-quality-checks)
- [CI/CD Quality Gates](#cicd-quality-gates)
- [Interpreting Results](#interpreting-results)
- [Improving Code Quality](#improving-code-quality)
- [Configuration Files](#configuration-files)

## Overview

DDC maintains high code quality standards through automated checks:

- **Cyclomatic Complexity**: < 10 (Grade B)
- **Maintainability Index**: > 80 (Grade A)
- **Pylint Score**: > 8.0/10
- **PEP 8 Compliance**: Enforced via Flake8
- **Type Safety**: Progressive typing with MyPy

### Tools Used

1. **Radon**: Cyclomatic complexity and maintainability index
2. **Xenon**: Complexity monitoring and gates
3. **Pylint**: Code quality linting
4. **Flake8**: Style guide enforcement (PEP 8)
5. **MyPy**: Static type checking
6. **SonarCloud**: Comprehensive code analysis (optional)

## Quality Standards

### Cyclomatic Complexity

**Target**: < 10 (Grade B or better)

Cyclomatic complexity measures the number of independent paths through code.

**Grades**:
- **A**: 1-5 (Simple, easy to test)
- **B**: 6-10 (More complex, moderate risk)
- **C**: 11-20 (Complex, high risk)
- **D**: 21-50 (Very complex, very high risk)
- **F**: 50+ (Extremely complex, untestable)

**Why it matters**:
- High complexity = harder to understand
- More complex code = more bugs
- Difficult to test thoroughly
- Harder to maintain

### Maintainability Index

**Target**: > 80 (Grade A)

Maintainability index is calculated from:
- Cyclomatic complexity
- Lines of code
- Halstead volume
- Comment density

**Grades**:
- **A**: 80-100 (Highly maintainable)
- **B**: 60-79 (Moderately maintainable)
- **C**: 40-59 (Low maintainability)
- **D**: 0-39 (Very low maintainability)

**Why it matters**:
- Predicts long-term maintenance costs
- Indicates code readability
- Correlates with bug density
- Affects team velocity

### Pylint Score

**Target**: > 8.0/10

Pylint checks for:
- Code errors
- Code smells
- Complexity issues
- Best practice violations
- Naming conventions
- Documentation coverage

**Score Interpretation**:
- **10.0**: Perfect (rare!)
- **9.0-10.0**: Excellent
- **8.0-9.0**: Good (our target)
- **7.0-8.0**: Acceptable
- **< 7.0**: Needs improvement

### PEP 8 Compliance

**Target**: 100% compliance (with exceptions)

PEP 8 is Python's official style guide. Enforced via Flake8.

**Key Standards**:
- Max line length: 100 characters
- 4 spaces for indentation (no tabs)
- Naming conventions:
  - Functions/variables: `snake_case`
  - Classes: `PascalCase`
  - Constants: `UPPER_CASE`
- Import ordering
- Whitespace usage

### Type Safety

**Target**: Progressive typing (increasing coverage over time)

MyPy performs static type checking:
- Catches type errors before runtime
- Improves code documentation
- Enables better IDE support
- Prevents common bugs

**Current Status**:
- Lenient mode (progressive)
- `check_untyped_defs = True`
- Gradually increasing strictness

## Code Quality Tools

### 1. Radon

**Purpose**: Complexity and maintainability analysis

**Installation**:
```bash
pip install radon
```

**Usage**:

```bash
# Check cyclomatic complexity
radon cc services/ --min B  # Fail if below grade B

# With averages
radon cc services/ -a -s

# Maintainability index
radon mi services/ --min A  # Fail if below grade A

# Show statistics
radon cc services/ --total-average
```

**Output Example**:
```
services/config/config_service.py
    M 85 - ConfigService.get_config (42:4)
    A 3 - ConfigService.save_config (90:4)

1 blocks (classes, functions, methods) analyzed.
Average complexity: A (3.5)
```

### 2. Xenon

**Purpose**: Automated complexity monitoring

**Installation**:
```bash
pip install xenon
```

**Usage**:

```bash
# Monitor complexity with thresholds
xenon --max-absolute B --max-modules A --max-average A services/

# This will FAIL the build if thresholds are exceeded
```

**Output Example**:
```
Blocks with complexity higher than B:
  - services/docker_service/docker_utils.py:get_container_status_async (CC: 11)

FAILURE: Complexity threshold exceeded
```

### 3. Pylint

**Purpose**: Code quality linting

**Installation**:
```bash
pip install pylint
```

**Configuration**: `.pylintrc`

**Usage**:

```bash
# Run pylint on all code
pylint services/ app/ utils/

# Specific files
pylint services/config/config_service.py

# With output format
pylint services/ --output-format=text --score=yes

# Generate config
pylint --generate-rcfile > .pylintrc
```

**Output Example**:
```
************* Module services.config.config_service
services/config/config_service.py:42:0: C0301: Line too long (105/100) (line-too-long)
services/config/config_service.py:90:4: W0613: Unused argument 'force_reload' (unused-argument)

Your code has been rated at 8.45/10
```

### 4. Flake8

**Purpose**: PEP 8 style enforcement

**Installation**:
```bash
pip install flake8 mccabe
```

**Configuration**: `.flake8`

**Usage**:

```bash
# Run flake8
flake8 services/ app/ utils/

# With statistics
flake8 services/ --statistics --count

# Check specific complexity
flake8 services/ --max-complexity=10
```

**Output Example**:
```
services/config/config_service.py:42:80: E501 line too long (105 > 100 characters)
services/docker_service/docker_utils.py:120:1: C901 'get_container_status_async' is too complex (11)

2     E501 line too long
1     C901 too complex
```

### 5. MyPy

**Purpose**: Static type checking

**Installation**:
```bash
pip install mypy
```

**Configuration**: `mypy.ini`

**Usage**:

```bash
# Run mypy with config
mypy --config-file mypy.ini

# Specific modules
mypy services/config/

# With cache
mypy --config-file mypy.ini --incremental
```

**Output Example**:
```
services/config/config_service.py:42: error: Argument 1 to "get_config" has incompatible type "str"; expected "bool"
services/mech/mech_service.py:90: error: Missing return statement

Found 2 errors in 2 files (checked 45 source files)
```

### 6. SonarCloud (Optional)

**Purpose**: Comprehensive code analysis

**Free for**: Open source projects

**Setup**:
1. Go to https://sonarcloud.io
2. Link GitHub repository
3. Get `SONAR_TOKEN`
4. Add to GitHub Secrets
5. Configure `sonar-project.properties`

**Features**:
- Code smells detection
- Security vulnerability scanning
- Bug detection
- Code coverage tracking
- Technical debt estimation
- Duplicate code detection

## Running Quality Checks

### Quick Check (All Tools)

```bash
# Install all tools
pip install -r requirements-test.txt

# Run all checks
./scripts/check_quality.sh
```

### Individual Checks

**Complexity**:
```bash
# Quick check
radon cc services/ app/ utils/ --min B

# Detailed report
radon cc services/ app/ utils/ -a -s --total-average > complexity_report.txt
```

**Maintainability**:
```bash
radon mi services/ app/ utils/ --min A
```

**Pylint**:
```bash
pylint services/ app/ utils/ --score=yes
```

**Flake8**:
```bash
flake8 services/ app/ utils/ --statistics
```

**MyPy**:
```bash
mypy --config-file mypy.ini
```

### Pre-Commit Checks

**Install pre-commit hook**:
```bash
# Create .git/hooks/pre-commit
cat > .git/hooks/pre-commit << 'EOF'
#!/bin/bash
# Run quick quality checks before commit

echo "Running quality checks..."

# Flake8 (fast)
flake8 services/ app/ utils/ --select=E9,F63,F7,F82
if [ $? -ne 0 ]; then
    echo "❌ Flake8 found critical errors"
    exit 1
fi

# Complexity check (fast)
radon cc services/ app/ utils/ --min B --total-average
if [ $? -ne 0 ]; then
    echo "❌ Complexity check failed"
    exit 1
fi

echo "✅ Quality checks passed"
exit 0
EOF

chmod +x .git/hooks/pre-commit
```

## CI/CD Quality Gates

**Workflow**: `.github/workflows/code-quality.yml`

### Jobs

#### 1. Code Complexity Analysis

**Runs**:
- Radon cyclomatic complexity check
- Maintainability index check
- Xenon complexity monitoring

**Fails if**:
- Average complexity > 10 (Grade B)
- Maintainability index < 80 (Grade A)

#### 2. Pylint Quality Check

**Runs**:
- Full pylint analysis

**Fails if**:
- Pylint score < 8.0/10

#### 3. Flake8 Style Check

**Runs**:
- PEP 8 compliance check
- Complexity check

**Fails if**:
- Critical PEP 8 violations
- Complexity > 10

#### 4. MyPy Type Checking

**Runs**:
- Static type analysis

**Status**: Informational (progressive typing)

#### 5. SonarCloud Analysis (Optional)

**Runs**:
- Comprehensive code analysis

**Status**: Informational

### Quality Summary

All jobs must pass for PR to be merged:
- ✅ Code Complexity
- ✅ Pylint Score
- ✅ Flake8 Style
- ℹ️ MyPy Types (informational)

## Interpreting Results

### Complexity Results

**Grade A (1-5)**: ✅ Excellent
- Simple, easy to understand
- Easy to test
- Low maintenance cost

**Grade B (6-10)**: ✅ Good (Target)
- Moderately complex
- Acceptable risk
- Testable

**Grade C (11-20)**: ⚠️ Warning
- Complex, refactor if possible
- Higher risk of bugs
- Harder to test

**Grade D/F (21+)**: ❌ Critical
- Very complex, MUST refactor
- Very high risk
- Difficult/impossible to test

### Maintainability Results

**Grade A (80-100)**: ✅ Excellent (Target)
- Highly maintainable
- Clear, readable code
- Low technical debt

**Grade B (60-79)**: ⚠️ Acceptable
- Moderately maintainable
- Some refactoring needed

**Grade C/D (< 60)**: ❌ Poor
- Low maintainability
- High technical debt
- Urgent refactoring needed

### Pylint Results

**10.0**: 🎯 Perfect (rare)
**9.0-10.0**: ✅ Excellent
**8.0-9.0**: ✅ Good (Target)
**7.0-8.0**: ⚠️ Acceptable
**< 7.0**: ❌ Needs improvement

**Common Issues**:
- `C0301`: Line too long → Break into multiple lines
- `W0613`: Unused argument → Remove or prefix with `_`
- `R0913`: Too many arguments → Use dataclass or config object
- `R0914`: Too many local variables → Extract functions
- `C0103`: Invalid name → Follow naming conventions

### Flake8 Results

**Error Codes**:
- **E**: PEP 8 errors
- **W**: PEP 8 warnings
- **F**: PyFlakes errors
- **C**: Complexity (mccabe)
- **N**: Naming conventions

**Common Issues**:
- `E501`: Line too long
- `F401`: Unused import
- `C901`: Function too complex
- `E302`: Expected 2 blank lines

## Improving Code Quality

### Reducing Complexity

**Before** (Complexity 15):
```python
def process_container(container_name, action, options):
    if action == "start":
        if options.get("force"):
            if container_exists(container_name):
                if is_running(container_name):
                    stop_container(container_name)
                start_container(container_name)
            else:
                create_and_start(container_name)
        else:
            start_container(container_name)
    elif action == "stop":
        # ... more nested conditions
```

**After** (Complexity 3-5):
```python
def process_container(container_name, action, options):
    handler = get_action_handler(action)
    return handler.execute(container_name, options)

class StartActionHandler:
    def execute(self, container_name, options):
        if options.get("force"):
            return self._force_start(container_name)
        return self._normal_start(container_name)

    def _force_start(self, container_name):
        # Simple, focused logic
        pass
```

**Techniques**:
1. **Extract functions**: Break complex functions into smaller ones
2. **Early returns**: Avoid deep nesting
3. **Strategy pattern**: Replace if/elif chains
4. **Guard clauses**: Check conditions early
5. **Command pattern**: Encapsulate operations

### Improving Maintainability

**Add Documentation**:
```python
def calculate_power(state: MechState) -> float:
    """Calculate current power with continuous decay.

    Power decays at 1.0 per day since last update.

    Args:
        state: Current mech state

    Returns:
        Current power level (min 0.0)

    Example:
        >>> state = MechState(total_donated=100.0, last_update=time.time())
        >>> calculate_power(state)
        100.0
    """
    seconds_since_update = time.time() - state.last_update
    decay = seconds_since_update / 86400  # 1 power per day
    current_power = max(0.0, state.total_donated - decay)
    return current_power
```

**Reduce Line Count**:
```python
# Before (10 lines)
def get_containers(self):
    containers = []
    for container in self.client.containers.list():
        containers.append(container)
    return containers

# After (1 line)
def get_containers(self):
    return self.client.containers.list()
```

**Increase Comment Density**:
```python
# Before
def process(data):
    x = data * 2
    y = x + 5
    z = y / 3
    return z

# After
def process(data):
    # Double the input value
    doubled = data * 2

    # Add offset for calculation
    with_offset = doubled + 5

    # Normalize result
    normalized = with_offset / 3

    return normalized
```

### Fixing Pylint Issues

**Line too long**:
```python
# Before
config_service = ConfigService(config_dir=config_dir, cache_service=cache_service, loader_service=loader_service)

# After
config_service = ConfigService(
    config_dir=config_dir,
    cache_service=cache_service,
    loader_service=loader_service
)
```

**Too many arguments**:
```python
# Before
def create_container(name, image, ports, volumes, env, network, restart):
    pass

# After
@dataclass
class ContainerConfig:
    name: str
    image: str
    ports: Dict[str, int]
    volumes: Dict[str, str]
    env: Dict[str, str]
    network: str
    restart_policy: str

def create_container(config: ContainerConfig):
    pass
```

**Unused variable**:
```python
# Before
def process(value, unused_param):
    return value * 2

# After
def process(value, _unused_param):  # Prefix with _
    return value * 2
```

### Adding Type Hints

**Before**:
```python
def get_config(force_reload=False):
    return load_config_from_disk()
```

**After**:
```python
from typing import Dict, Any

def get_config(force_reload: bool = False) -> Dict[str, Any]:
    return load_config_from_disk()
```

**Complex Types**:
```python
from typing import List, Dict, Optional, Union

def get_containers(
    active_only: bool = True,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    containers = self._fetch_containers()

    if active_only:
        containers = [c for c in containers if c.get('active')]

    if limit:
        containers = containers[:limit]

    return containers
```

## Configuration Files

### .pylintrc

**Location**: `/path/to/.pylintrc`

**Key Settings**:
```ini
[MASTER]
jobs=0  # Use all CPU cores

[DESIGN]
max-args=10
max-attributes=15
max-branches=15

[FORMAT]
max-line-length=100
```

### .flake8

**Location**: `/path/to/.flake8`

**Key Settings**:
```ini
[flake8]
max-line-length = 100
max-complexity = 10
exclude = .git,__pycache__,venv
ignore = E203,W503
```

### mypy.ini

**Location**: `/path/to/mypy.ini`

**Key Settings**:
```ini
[mypy]
python_version = 3.9
check_untyped_defs = True
warn_return_any = True
ignore_missing_imports = True
```

### sonar-project.properties

**Location**: `/path/to/sonar-project.properties`

**Key Settings**:
```properties
sonar.projectKey=DockerDiscordControl_DockerDiscordControl
sonar.sources=services,app,utils
sonar.tests=tests
sonar.python.coverage.reportPaths=coverage.xml
```

## Continuous Improvement

### Daily Tasks

1. Check CI/CD quality results
2. Address critical issues (Grade D/F complexity)
3. Review pylint scores for new code

### Weekly Tasks

1. Review maintainability trends
2. Refactor complex functions (> Grade C)
3. Update type hints for new code
4. Clean up pylint warnings

### Monthly Tasks

1. Run full quality audit
2. Update quality thresholds if needed
3. Review technical debt
4. Plan refactoring sprints

## Troubleshooting

### "Complexity too high" in CI

**Solution**: Refactor complex functions
```bash
# Find complex functions
radon cc services/ --min C

# Focus on Grade D/F first
radon cc services/ --min D
```

### "Pylint score too low"

**Solution**: Fix top issues
```bash
# Show only errors (not warnings)
pylint services/ --errors-only

# Focus on specific categories
pylint services/ --disable=all --enable=E
```

### "MyPy type errors"

**Solution**: Add type hints or ignore
```python
# Add type hints
def my_function(value: int) -> str:
    return str(value)

# Or ignore specific line
result = my_function(42)  # type: ignore
```

## See Also

- [SERVICES.md](SERVICES.md) - Service architecture
- [CONTRIBUTING.md](CONTRIBUTING.md) - Contribution guidelines
- [PERFORMANCE.md](PERFORMANCE.md) - Performance testing
- [ERROR_HANDLING.md](ERROR_HANDLING.md) - Error handling
