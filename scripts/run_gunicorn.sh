#!/bin/bash
# =============================================================================
# Blitz Test Server - Production Startup Script
# =============================================================================
# Convenience script to start the server with proper environment loading
#
# Usage:
#   ./scripts/run_gunicorn.sh                    # Start with default settings
#   ./scripts/run_gunicorn.sh --config custom.py # Start with custom config
#
# This script:
# 1. Loads environment variables from .env if present
# 2. Sets up Prometheus multiprocess directory if metrics are enabled
# 3. Starts Gunicorn with the configured settings
# =============================================================================

set -euo pipefail

# Script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Configuration
DEFAULT_CONFIG="gunicorn.conf.py"
ENV_FILE="$PROJECT_ROOT/.env"
PROMETHEUS_MULTIPROC_DIR="${PROMETHEUS_MULTIPROC_DIR:-/tmp/prometheus_multiproc}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# =============================================================================
# Utility Functions
# =============================================================================

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

show_usage() {
    cat << EOF
Blitz Test Server - Production Startup Script

Usage:
    $0 [OPTIONS]

Options:
    -c, --config FILE    Use custom Gunicorn config file (default: gunicorn.conf.py)
    -e, --env FILE      Use custom environment file (default: .env)
    -h, --help          Show this help message
    --no-env            Don't load environment file
    --dry-run           Show what would be executed without running

Examples:
    $0                           # Start with defaults
    $0 -c custom.conf.py         # Use custom config
    $0 -e production.env         # Use custom env file
    $0 --dry-run                 # Preview command

Environment Variables:
    ENABLE_METRICS               Set to 'true' to enable Prometheus metrics
    PROMETHEUS_MULTIPROC_DIR     Directory for multiprocess metrics
    GUNICORN_CMD_ARGS           Additional Gunicorn arguments

EOF
}

# =============================================================================
# Configuration Parsing
# =============================================================================

CONFIG_FILE="$DEFAULT_CONFIG"
LOAD_ENV=true
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -c|--config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        -e|--env)
            ENV_FILE="$2"
            shift 2
            ;;
        --no-env)
            LOAD_ENV=false
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# =============================================================================
# Environment Setup
# =============================================================================

log_info "Blitz Test Server - Starting production deployment"
log_info "Project root: $PROJECT_ROOT"

# Change to project directory
cd "$PROJECT_ROOT"

# Load environment file if requested and exists
if [[ "$LOAD_ENV" == "true" && -f "$ENV_FILE" ]]; then
    log_info "Loading environment from: $ENV_FILE"
    
    # Export variables from .env file (skip comments and empty lines)
    set -a
    source <(grep -v '^#' "$ENV_FILE" | grep -v '^$' | sed 's/^/export /')
    set +a
    
    log_success "Environment loaded successfully"
else
    if [[ "$LOAD_ENV" == "true" ]]; then
        log_warning "Environment file not found: $ENV_FILE"
        log_warning "Continuing with system environment variables"
    else
        log_info "Skipping environment file loading"
    fi
fi

# =============================================================================
# Prometheus Metrics Setup
# =============================================================================

if [[ "${ENABLE_METRICS:-false}" == "true" ]]; then
    log_info "Metrics enabled - setting up Prometheus multiprocess directory"
    
    # Clean and create prometheus multiprocess directory
    if [[ -d "$PROMETHEUS_MULTIPROC_DIR" ]]; then
        log_info "Cleaning existing metrics directory: $PROMETHEUS_MULTIPROC_DIR"
        rm -rf "$PROMETHEUS_MULTIPROC_DIR"/*
    fi
    
    mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
    export PROMETHEUS_MULTIPROC_DIR
    
    log_success "Prometheus metrics directory ready: $PROMETHEUS_MULTIPROC_DIR"
else
    log_info "Metrics disabled (ENABLE_METRICS not set to 'true')"
fi

# =============================================================================
# Pre-flight Checks
# =============================================================================

log_info "Running pre-flight checks..."

# Check if config file exists
if [[ ! -f "$CONFIG_FILE" ]]; then
    log_error "Gunicorn config file not found: $CONFIG_FILE"
    exit 1
fi

# Check if app module exists
if [[ ! -f "run.py" ]]; then
    log_error "Application entry point not found: run.py"
    exit 1
fi

# Check if virtual environment is activated
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    log_warning "No virtual environment detected"
    log_warning "Make sure you have activated your virtual environment or using system Python"
fi

# Check if gunicorn is available
if ! command -v gunicorn &> /dev/null; then
    log_error "Gunicorn not found in PATH"
    log_error "Install with: pip install gunicorn"
    exit 1
fi

log_success "Pre-flight checks passed"

# =============================================================================
# Build Gunicorn Command
# =============================================================================

GUNICORN_CMD="gunicorn"
GUNICORN_ARGS=("-c" "$CONFIG_FILE" "run:app")

# Add any additional arguments from environment
if [[ -n "${GUNICORN_CMD_ARGS:-}" ]]; then
    log_info "Adding extra Gunicorn arguments: $GUNICORN_CMD_ARGS"
    # Split on spaces and add to array
    read -ra EXTRA_ARGS <<< "$GUNICORN_CMD_ARGS"
    GUNICORN_ARGS+=("${EXTRA_ARGS[@]}")
fi

# =============================================================================
# Display Configuration Summary
# =============================================================================

log_info "Configuration Summary:"
echo "  Config file: $CONFIG_FILE"
echo "  Environment file: ${ENV_FILE} (loaded: $LOAD_ENV)"
echo "  Metrics enabled: ${ENABLE_METRICS:-false}"
echo "  Working directory: $PROJECT_ROOT"
echo "  Command: $GUNICORN_CMD ${GUNICORN_ARGS[*]}"

if [[ "${ENABLE_METRICS:-false}" == "true" ]]; then
    echo "  Metrics directory: $PROMETHEUS_MULTIPROC_DIR"
fi

# =============================================================================
# Execute or Display Command
# =============================================================================

if [[ "$DRY_RUN" == "true" ]]; then
    log_info "DRY RUN - Would execute:"
    echo "  cd $PROJECT_ROOT"
    echo "  $GUNICORN_CMD ${GUNICORN_ARGS[*]}"
    exit 0
fi

# =============================================================================
# Signal Handling
# =============================================================================

# Function to handle cleanup on script termination
cleanup() {
    log_info "Received termination signal, cleaning up..."
    # Kill gunicorn if it's running
    if [[ -n "${GUNICORN_PID:-}" ]]; then
        kill -TERM "$GUNICORN_PID" 2>/dev/null || true
        wait "$GUNICORN_PID" 2>/dev/null || true
    fi
    log_info "Cleanup completed"
    exit 0
}

# Set up signal handlers
trap cleanup SIGTERM SIGINT SIGQUIT

# =============================================================================
# Start Gunicorn
# =============================================================================

log_success "Starting Blitz Test Server..."
log_info "Use Ctrl+C to stop the server"

# Start gunicorn in background to capture PID
exec "$GUNICORN_CMD" "${GUNICORN_ARGS[@]}" &
GUNICORN_PID=$!

# Wait for gunicorn to finish
wait "$GUNICORN_PID"

log_info "Blitz Test Server stopped"