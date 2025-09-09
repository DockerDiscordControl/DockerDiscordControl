#!/bin/bash
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Test Runner Script                             #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_DIR="${PROJECT_ROOT}/tests"
REPORTS_DIR="${PROJECT_ROOT}/reports"

# Default values
RUN_UNIT=true
RUN_INTEGRATION=false
RUN_E2E=false
RUN_SECURITY=false
RUN_PERFORMANCE=false
RUN_LOAD=false
PARALLEL=false
COVERAGE=true
VERBOSE=false
FAIL_FAST=false
CLEAN=false

# Help function
show_help() {
    echo "DDC Test Runner"
    echo ""
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -h, --help              Show this help message"
    echo "  -a, --all               Run all test suites"
    echo "  -u, --unit              Run unit tests (default)"
    echo "  -i, --integration       Run integration tests"
    echo "  -e, --e2e               Run end-to-end tests"
    echo "  -s, --security          Run security tests (SAST/DAST)"
    echo "  -p, --performance       Run performance tests"
    echo "  -l, --load              Run load tests"
    echo "  -j, --parallel          Run tests in parallel"
    echo "  --no-coverage           Disable coverage reporting"
    echo "  -v, --verbose           Verbose output"
    echo "  -x, --fail-fast         Stop on first failure"
    echo "  --clean                 Clean previous reports"
    echo ""
    echo "Examples:"
    echo "  $0                      # Run unit tests with coverage"
    echo "  $0 -a                   # Run all test types"
    echo "  $0 -u -i                # Run unit and integration tests"
    echo "  $0 -s --verbose         # Run security tests with verbose output"
    echo "  $0 -p -j                # Run performance tests in parallel"
    echo ""
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        -a|--all)
            RUN_UNIT=true
            RUN_INTEGRATION=true
            RUN_E2E=true
            RUN_SECURITY=true
            RUN_PERFORMANCE=true
            shift
            ;;
        -u|--unit)
            RUN_UNIT=true
            shift
            ;;
        -i|--integration)
            RUN_INTEGRATION=true
            shift
            ;;
        -e|--e2e)
            RUN_E2E=true
            shift
            ;;
        -s|--security)
            RUN_SECURITY=true
            shift
            ;;
        -p|--performance)
            RUN_PERFORMANCE=true
            shift
            ;;
        -l|--load)
            RUN_LOAD=true
            shift
            ;;
        -j|--parallel)
            PARALLEL=true
            shift
            ;;
        --no-coverage)
            COVERAGE=false
            shift
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        -x|--fail-fast)
            FAIL_FAST=true
            shift
            ;;
        --clean)
            CLEAN=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Print header
print_header() {
    echo -e "${BLUE}"
    echo "============================================================================"
    echo " DDC Test Suite Runner"
    echo "============================================================================"
    echo -e "${NC}"
}

# Print section
print_section() {
    echo -e "${YELLOW}=== $1 ===${NC}"
}

# Print success
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

# Print error
print_error() {
    echo -e "${RED}✗ $1${NC}"
}

# Print info
print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

# Setup environment
setup_environment() {
    print_section "Setting up test environment"
    
    cd "$PROJECT_ROOT"
    
    # Create reports directory
    mkdir -p "$REPORTS_DIR"
    
    # Clean previous reports if requested
    if [ "$CLEAN" = true ]; then
        print_info "Cleaning previous test reports"
        rm -rf "$REPORTS_DIR"/*
        rm -rf htmlcov/
        rm -f .coverage
    fi
    
    # Check if virtual environment is active
    if [[ -z "$VIRTUAL_ENV" ]] && [[ ! -f "venv/bin/activate" ]]; then
        print_info "No virtual environment detected. Consider using one."
    fi
    
    # Install test dependencies if requirements-test.txt exists
    if [[ -f "requirements-test.txt" ]]; then
        print_info "Installing test dependencies"
        if command -v pip3 >/dev/null 2>&1; then
            pip3 install -q -r requirements-test.txt
        elif command -v pip >/dev/null 2>&1; then
            pip install -q -r requirements-test.txt
        elif which python3 >/dev/null 2>&1; then
            python3 -m pip install -q -r requirements-test.txt
        elif which python >/dev/null 2>&1; then
            python -m pip install -q -r requirements-test.txt
        else
            print_error "No Python or pip found. Please install Python."
            exit 1
        fi
    fi
    
    print_success "Environment setup complete"
}

# Build pytest command
build_pytest_command() {
    local test_path="$1"
    local markers="$2"
    local extra_args="$3"
    
    local cmd="python -m pytest"
    
    # Test path
    cmd="$cmd $test_path"
    
    # Markers
    if [[ -n "$markers" ]]; then
        cmd="$cmd -m \"$markers\""
    fi
    
    # Verbose output
    if [ "$VERBOSE" = true ]; then
        cmd="$cmd -v"
    else
        cmd="$cmd -q"
    fi
    
    # Fail fast
    if [ "$FAIL_FAST" = true ]; then
        cmd="$cmd -x"
    fi
    
    # Parallel execution
    if [ "$PARALLEL" = true ] && command -v pytest-xdist >/dev/null 2>&1; then
        cmd="$cmd -n auto"
    fi
    
    # Coverage
    if [ "$COVERAGE" = true ]; then
        cmd="$cmd --cov=app --cov=cogs --cov=services --cov=utils"
        cmd="$cmd --cov-report=html:htmlcov"
        cmd="$cmd --cov-report=term-missing"
        cmd="$cmd --cov-report=xml:reports/coverage.xml"
    fi
    
    # HTML report
    cmd="$cmd --html=reports/pytest_report.html --self-contained-html"
    
    # JSON report
    if command -v pytest-json-report >/dev/null 2>&1; then
        cmd="$cmd --json-report --json-report-file=reports/pytest_report.json"
    fi
    
    # Extra arguments
    if [[ -n "$extra_args" ]]; then
        cmd="$cmd $extra_args"
    fi
    
    echo "$cmd"
}

# Run unit tests
run_unit_tests() {
    print_section "Running Unit Tests"
    
    local cmd=$(build_pytest_command "tests/unit/" "unit" "--tb=short")
    
    print_info "Command: $cmd"
    
    if eval "$cmd"; then
        print_success "Unit tests passed"
        return 0
    else
        print_error "Unit tests failed"
        return 1
    fi
}

# Run integration tests
run_integration_tests() {
    print_section "Running Integration Tests"
    
    # Check if Docker is available for Docker integration tests
    if ! command -v docker >/dev/null 2>&1; then
        print_info "Docker not available, skipping Docker integration tests"
        local markers="integration and not docker"
    else
        local markers="integration"
    fi
    
    local cmd=$(build_pytest_command "tests/integration/" "$markers" "--tb=short")
    
    print_info "Command: $cmd"
    
    if eval "$cmd"; then
        print_success "Integration tests passed"
        return 0
    else
        print_error "Integration tests failed"
        return 1
    fi
}

# Run E2E tests
run_e2e_tests() {
    print_section "Running End-to-End Tests"
    
    # Check if Chrome/Chromium is available for Selenium tests
    if ! command -v google-chrome >/dev/null 2>&1 && ! command -v chromium >/dev/null 2>&1; then
        print_info "Chrome not available, E2E tests may be skipped"
    fi
    
    local cmd=$(build_pytest_command "tests/e2e/" "e2e" "--tb=line")
    
    print_info "Command: $cmd"
    
    if eval "$cmd"; then
        print_success "E2E tests passed"
        return 0
    else
        print_error "E2E tests failed"
        return 1
    fi
}

# Run security tests
run_security_tests() {
    print_section "Running Security Tests"
    
    # Check if bandit is available
    if ! command -v bandit >/dev/null 2>&1; then
        print_info "Bandit not available, installing..."
        if command -v pip >/dev/null 2>&1; then
            pip install -q bandit
        else
            python3 -m pip install -q bandit
        fi
    fi
    
    local cmd=$(build_pytest_command "tests/security/" "security" "--tb=line")
    
    print_info "Command: $cmd"
    
    if eval "$cmd"; then
        print_success "Security tests passed"
        return 0
    else
        print_error "Security tests failed"
        return 1
    fi
}

# Run performance tests
run_performance_tests() {
    print_section "Running Performance Tests"
    
    local cmd=$(build_pytest_command "tests/performance/" "performance" "--benchmark-only --benchmark-sort=mean")
    
    print_info "Command: $cmd"
    
    if eval "$cmd"; then
        print_success "Performance tests passed"
        return 0
    else
        print_error "Performance tests failed"
        return 1
    fi
}

# Run load tests
run_load_tests() {
    print_section "Running Load Tests"
    
    if ! command -v locust >/dev/null 2>&1; then
        print_info "Locust not available, installing..."
        if command -v pip >/dev/null 2>&1; then
            pip install -q locust
        else
            python3 -m pip install -q locust
        fi
    fi
    
    print_info "Starting DDC web server for load testing..."
    
    # Start web server in background
    DDC_WEB_PORT=5001 python -m app.web_ui &
    local server_pid=$!
    
    # Wait for server to start
    sleep 5
    
    # Run load tests
    print_info "Running load tests..."
    locust -f tests/load/locustfile.py --host=http://localhost:5001 \
           --users=20 --spawn-rate=5 --run-time=60s --headless \
           --html=reports/load_test_report.html
    
    local load_result=$?
    
    # Stop web server
    kill $server_pid 2>/dev/null || true
    
    if [ $load_result -eq 0 ]; then
        print_success "Load tests completed"
        return 0
    else
        print_error "Load tests failed"
        return 1
    fi
}

# Generate test report
generate_test_report() {
    print_section "Generating Test Report"
    
    local report_file="$REPORTS_DIR/test_summary.md"
    
    cat > "$report_file" << EOF
# DDC Test Report

Generated on: $(date)

## Test Results Summary

EOF
    
    if [[ -f "$REPORTS_DIR/pytest_report.json" ]]; then
        print_info "Processing pytest results..."
        python3 -c "
import json
import sys

try:
    with open('$REPORTS_DIR/pytest_report.json') as f:
        data = json.load(f)
    
    summary = data.get('summary', {})
    print(f'- Total Tests: {summary.get(\"total\", \"N/A\")}')
    print(f'- Passed: {summary.get(\"passed\", \"N/A\")}')
    print(f'- Failed: {summary.get(\"failed\", \"N/A\")}')
    print(f'- Skipped: {summary.get(\"skipped\", \"N/A\")}')
    print(f'- Duration: {data.get(\"duration\", \"N/A\")}s')
except:
    print('Could not process pytest results')
" >> "$report_file"
    fi
    
    if [[ -f "htmlcov/index.html" ]]; then
        echo -e "\n## Coverage Report\n" >> "$report_file"
        echo "Coverage report available at: \`htmlcov/index.html\`" >> "$report_file"
    fi
    
    if [[ -f "$REPORTS_DIR/load_test_report.html" ]]; then
        echo -e "\n## Load Test Report\n" >> "$report_file"
        echo "Load test report available at: \`reports/load_test_report.html\`" >> "$report_file"
    fi
    
    print_success "Test report generated: $report_file"
}

# Main execution
main() {
    print_header
    
    local exit_code=0
    
    # Setup
    setup_environment
    
    # Run tests based on flags
    if [ "$RUN_UNIT" = true ]; then
        if ! run_unit_tests; then
            exit_code=1
            if [ "$FAIL_FAST" = true ]; then
                exit $exit_code
            fi
        fi
    fi
    
    if [ "$RUN_INTEGRATION" = true ]; then
        if ! run_integration_tests; then
            exit_code=1
            if [ "$FAIL_FAST" = true ]; then
                exit $exit_code
            fi
        fi
    fi
    
    if [ "$RUN_E2E" = true ]; then
        if ! run_e2e_tests; then
            exit_code=1
            if [ "$FAIL_FAST" = true ]; then
                exit $exit_code
            fi
        fi
    fi
    
    if [ "$RUN_SECURITY" = true ]; then
        if ! run_security_tests; then
            exit_code=1
            if [ "$FAIL_FAST" = true ]; then
                exit $exit_code
            fi
        fi
    fi
    
    if [ "$RUN_PERFORMANCE" = true ]; then
        if ! run_performance_tests; then
            exit_code=1
            if [ "$FAIL_FAST" = true ]; then
                exit $exit_code
            fi
        fi
    fi
    
    if [ "$RUN_LOAD" = true ]; then
        if ! run_load_tests; then
            exit_code=1
            if [ "$FAIL_FAST" = true ]; then
                exit $exit_code
            fi
        fi
    fi
    
    # Generate report
    generate_test_report
    
    # Final summary
    print_section "Test Run Complete"
    
    if [ $exit_code -eq 0 ]; then
        print_success "All tests passed!"
    else
        print_error "Some tests failed (exit code: $exit_code)"
    fi
    
    print_info "Reports available in: $REPORTS_DIR"
    
    exit $exit_code
}

# Run main function
main "$@"