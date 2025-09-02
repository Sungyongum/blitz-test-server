#!/usr/bin/env python3
"""
Gunicorn configuration for Blitz Test Server - Single Server Deployment

Usage:
    gunicorn -c gunicorn.conf.py run:app

This configuration is optimized for single-server production deployment.
"""

import multiprocessing
import os

# =============================================================================
# Server Configuration
# =============================================================================

# Bind to localhost only - use nginx reverse proxy for external access
bind = "127.0.0.1:8000"

# =============================================================================
# Worker Configuration
# =============================================================================

# Worker calculation: (2 x CPU cores) + 1
# For single server, use conservative settings
workers = min(multiprocessing.cpu_count() * 2 + 1, 4)

# Worker class - sync is most compatible with Flask applications
worker_class = "sync"

# Threads per worker - helps with I/O bound operations
threads = 2

# Worker connections (only used with async workers)
worker_connections = 1000

# =============================================================================
# Worker Lifecycle Management
# =============================================================================

# Restart workers after handling this many requests (prevents memory leaks)
max_requests = 1000
max_requests_jitter = 100

# Worker timeout in seconds
timeout = 60

# Keep-alive connections
keepalive = 5

# Worker restart settings
preload_app = True

# =============================================================================
# Logging Configuration
# =============================================================================

# Access log format for production monitoring
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Log to stdout/stderr for systemd/Docker compatibility
accesslog = "-"
errorlog = "-"

# Log level
loglevel = "info"

# Disable access log for health checks to reduce noise
def skip_health_checks(record):
    """Skip logging for health check endpoints"""
    if hasattr(record, 'args') and len(record.args) >= 1:
        request_line = record.args[0] if record.args else ""
        if any(endpoint in request_line for endpoint in ['/healthz', '/livez', '/readyz']):
            return False
    return True

# Apply the filter
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# =============================================================================
# Process Configuration
# =============================================================================

# Process name for easier identification
proc_name = "blitz-test-server"

# Process user (set by systemd service, don't override here)
# user = "blitzbot"
# group = "blitzbot"

# =============================================================================
# Security and Resource Limits
# =============================================================================

# Limit request line size
limit_request_line = 4094

# Limit request header field size  
limit_request_field_size = 8190

# Limit number of request header fields
limit_request_fields = 100

# =============================================================================
# Performance Tuning
# =============================================================================

# Preload the application code before forking workers
preload_app = True

# Enable reusing of sockets
reuse_port = True

# =============================================================================
# Environment and Monitoring Setup
# =============================================================================

def on_starting(server):
    """Called just before the master process is initialized."""
    server.log.info("Starting Blitz Test Server")
    
    # Set up Prometheus multiprocess directory if metrics are enabled
    if os.environ.get('ENABLE_METRICS', '').lower() == 'true':
        multiproc_dir = os.environ.get('PROMETHEUS_MULTIPROC_DIR', '/tmp/prometheus_multiproc')
        os.makedirs(multiproc_dir, exist_ok=True)
        server.log.info(f"Prometheus multiprocess directory: {multiproc_dir}")

def when_ready(server):
    """Called just after the server is started."""
    server.log.info("Blitz Test Server is ready to accept connections")

def on_exit(server):
    """Called just before the master process exits."""
    server.log.info("Blitz Test Server is shutting down")

def worker_int(worker):
    """Called when a worker receives the SIGINT or SIGQUIT signal."""
    worker.log.info("Worker received interrupt signal")

# =============================================================================
# Health Check Configuration
# =============================================================================

# Graceful timeout for worker restart
graceful_timeout = 30

# =============================================================================
# Production Recommendations
# =============================================================================

# For high-traffic deployments, consider:
# - Increasing workers based on load testing
# - Using nginx upstream with multiple Gunicorn instances
# - Monitoring worker memory usage and adjusting max_requests
# - Setting up proper log rotation
# - Configuring systemd for automatic restart

# Example systemd service configuration is provided in:
# systemd/blitz-test-server.service