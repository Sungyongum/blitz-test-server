# Operations Guide for Blitz Test Server

This guide covers operational aspects of running Blitz Test Server at scale (5k+ users).

## Table of Contents

- [Health Monitoring](#health-monitoring)
- [Metrics and Observability](#metrics-and-observability)
- [Rate Limiting](#rate-limiting)
- [Concurrency Control](#concurrency-control)
- [Maintenance Mode](#maintenance-mode)
- [Security Configuration](#security-configuration)
- [Database Optimization](#database-optimization)
- [Deployment at Scale](#deployment-at-scale)
- [Environment Variables](#environment-variables)

## Health Monitoring

The application provides three health endpoints for monitoring:

### Health Endpoints

- **`GET /healthz`** - Fast health check
  - Returns: `{"status": "ok", "version": "...", "timestamp": "...", "service": "blitz-test-server"}`
  - Use for: Load balancer health checks, uptime monitoring
  - Always fast, no external dependencies

- **`GET /livez`** - Liveness check  
  - Returns: `{"status": "ok", "timestamp": "..."}`
  - Use for: Kubernetes liveness probe
  - Indicates if process should be restarted

- **`GET /readyz`** - Readiness check
  - Returns: `{"status": "ok|error", "timestamp": "...", "checks": {...}}`
  - Use for: Kubernetes readiness probe, traffic routing decisions
  - Checks database connectivity and bot manager integrity
  - Returns 503 if not ready to serve traffic

### Example Health Check Configuration

**Kubernetes:**
```yaml
livenessProbe:
  httpGet:
    path: /livez
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10

readinessProbe:
  httpGet:
    path: /readyz
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 5
```

**Nginx:**
```nginx
upstream backend {
    server app1:8000;
    server app2:8000;
}

# Health check (requires nginx_upstream_check_module)
check interval=3000 rise=2 fall=3 timeout=1000 type=http;
check_http_send "GET /healthz HTTP/1.0\r\n\r\n";
check_http_expect_alive http_2xx;
```

## Metrics and Observability

### Prometheus Metrics

Enable metrics with `ENABLE_METRICS=true`. Available at `GET /metrics`.

**Default Metrics:**
- `http_requests_total{method, endpoint, status}` - Total HTTP requests
- `http_request_duration_seconds{method, endpoint}` - Request latency histogram
- `bot_starts_total{user_id, status}` - Bot start operations
- `bot_stops_total{user_id, status}` - Bot stop operations  
- `bot_recovers_total{user_id, status}` - Bot recovery operations
- `errors_total{type, component}` - Application errors
- `active_bots_total` - Currently active bots
- `app_info{version, environment}` - Application metadata

**Plus default Python/process metrics from prometheus_client**

### Multiprocess Mode

For Gunicorn deployment, configure multiprocess metrics:

```bash
export PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc
mkdir -p $PROMETHEUS_MULTIPROC_DIR

# Start with Gunicorn
gunicorn --workers 4 --bind 0.0.0.0:8000 run:app
```

### Example Prometheus Configuration

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'blitz-test-server'
    static_configs:
      - targets: ['app:8000']
    metrics_path: '/metrics'
    scrape_interval: 15s
```

### Grafana Dashboard Example

Key metrics to monitor:
- Request rate: `rate(http_requests_total[5m])`
- Request latency: `histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))`
- Error rate: `rate(http_requests_total{status=~"5.."}[5m])`
- Active bots: `active_bots_total`
- Bot operation success rate: `rate(bot_starts_total{status="success"}[5m])`

## Rate Limiting

### Configuration

Rate limits are configured via environment variables:

```bash
# Per-user limits (per user per time window)
RATE_LIMITS_START=10/minute      # Bot start operations
RATE_LIMITS_STOP=10/minute       # Bot stop operations  
RATE_LIMITS_RECOVER=10/minute    # Recovery operations
RATE_LIMITS_STATUS=30/minute     # Status checks

# Global ceiling (applies to all users combined)
RATE_LIMITS_GLOBAL=200/minute    # Total requests per route group
```

### Redis Backend (Recommended for Production)

```bash
# Use Redis for distributed rate limiting
RATE_LIMIT_REDIS_URL=redis://redis:6379/1

# Without Redis, falls back to in-memory (single instance only)
```

### Rate Limit Responses

When rate limited, API returns:
```json
{
  "error": "Rate limit exceeded",
  "retry_after": 60
}
```
HTTP Status: `429 Too Many Requests`

### Exemptions

Admin users (`admin@admin.com`) are exempt from rate limits.

## Concurrency Control

### Per-User Concurrency Guards

The application ensures bot operations serialize per user to prevent conflicts:

- Only one bot operation (start/stop/recover) per user at a time
- Cross-user operations can run in parallel
- Operations that would conflict return `429 Too Many Requests` with `retry_after`

### Example Response for Concurrent Operation

```json
{
  "success": false,
  "message": "Bot operation already in progress for this user. Please wait.",
  "retry_after": 30
}
```

## Maintenance Mode

### Admin Controls

**Enable maintenance mode:**
```bash
curl -X POST /admin/maintenance/enable \
  -H "Authorization: Bearer <admin-token>"
```

**Disable maintenance mode:**
```bash
curl -X POST /admin/maintenance/disable \
  -H "Authorization: Bearer <admin-token>"
```

### Effects During Maintenance

- Non-admin POST requests to `/api/bot/*` return `503 Service Unavailable`
- GET requests and health checks continue to work
- Admin users can still perform all operations
- UI shows maintenance banner

### Global Banner

**Set banner message:**
```bash
curl -X POST /admin/banner \
  -H "Content-Type: application/json" \
  -d '{"message": "Scheduled maintenance 2-4 PM UTC"}'
```

**Clear banner:**
```bash
curl -X POST /admin/banner/clear
```

**Check status (public endpoint):**
```bash
curl /api/status
# Returns: {"maintenance_enabled": false, "banner_message": ""}
```

## Security Configuration

### Environment Variables

```bash
# Content Security Policy
SECURITY_CSP="default-src 'self'; script-src 'self' 'unsafe-inline' cdn.jsdelivr.net"

# Request size limits  
MAX_REQUEST_BYTES=1048576  # 1MB

# Session security
SESSION_SECURE=true        # Enable for HTTPS
CSRF_SSL_STRICT=true       # Enable for HTTPS

# Logging
LOG_LEVEL=INFO            # DEBUG, INFO, WARNING, ERROR
```

### Headers Applied

- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`  
- `Referrer-Policy: no-referrer`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`
- `Content-Security-Policy: <configurable>`

### Session Security

- `HttpOnly` cookies
- `Secure` flag when `SESSION_SECURE=true`
- `SameSite=Lax`
- 24-hour session lifetime

## Database Optimization

### Automatic Optimizations

The application automatically configures SQLite for better performance:

**SQLite Settings:**
- `PRAGMA journal_mode=WAL` - Write-Ahead Logging for concurrency
- `PRAGMA synchronous=NORMAL` - Balance safety/performance
- `PRAGMA cache_size=10000` - 10MB cache
- `PRAGMA temp_store=MEMORY` - Memory temp tables
- `PRAGMA mmap_size=268435456` - 256MB memory mapping

**Indices Created:**
- `idx_users_email` - User email lookups
- `idx_users_verification_token` - Email verification
- `idx_trades_user_id` - User trade queries
- `idx_bot_events_user_id` - Bot event queries
- `idx_user_bots_status` - Bot status filtering

### Manual Database Maintenance

```bash
# Check database file
sqlite3 instance/database.db ".schema"

# Analyze query performance
sqlite3 instance/database.db "EXPLAIN QUERY PLAN SELECT * FROM user WHERE email = ?"

# Vacuum database (reclaim space)
sqlite3 instance/database.db "VACUUM;"
```

## Deployment at Scale

### Gunicorn Configuration

**For 5k+ concurrent users:**

```bash
# Calculate workers: (2 x CPU cores) + 1
WORKERS=9  # For 4-core server

gunicorn \
  --workers $WORKERS \
  --worker-class sync \
  --worker-connections 1000 \
  --max-requests 1000 \
  --max-requests-jitter 100 \
  --bind 0.0.0.0:8000 \
  --access-logfile - \
  --error-logfile - \
  --log-level info \
  run:app
```

### System Tuning

**Kernel parameters:**
```bash
# /etc/sysctl.conf
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 5000
net.ipv4.tcp_max_syn_backlog = 8192
fs.file-max = 100000

# Apply
sysctl -p
```

**Process limits:**
```bash
# /etc/security/limits.conf
* soft nofile 65535
* hard nofile 65535
```

### Nginx Configuration

```nginx
upstream blitz_backend {
    server app1:8000 max_fails=3 fail_timeout=30s;
    server app2:8000 max_fails=3 fail_timeout=30s;
    server app3:8000 max_fails=3 fail_timeout=30s;
    keepalive 32;
}

server {
    listen 80;
    client_max_body_size 1M;
    client_body_timeout 60s;
    client_header_timeout 60s;
    keepalive_timeout 65s;
    
    location / {
        proxy_pass http://blitz_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Timeouts
        proxy_connect_timeout 10s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
        
        # Connection reuse
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
    
    # Health checks bypass caching
    location ~ ^/(healthz|livez|readyz)$ {
        proxy_pass http://blitz_backend;
        proxy_cache off;
    }
    
    # Metrics endpoint (if exposed)
    location /metrics {
        proxy_pass http://blitz_backend;
        proxy_cache off;
        # Restrict access
        allow 10.0.0.0/8;
        deny all;
    }
}
```

### Log Shipping

**Vector configuration (vector.toml):**
```toml
[sources.blitz_logs]
type = "file"
include = ["/var/log/blitz/*.log"]
read_from = "beginning"

[transforms.parse_json]
type = "json_parser"
inputs = ["blitz_logs"]

[sinks.elasticsearch]
type = "elasticsearch"
inputs = ["parse_json"]
endpoint = "https://elasticsearch:9200"
index = "blitz-logs-%Y.%m.%d"
```

**Fluent Bit configuration:**
```ini
[SERVICE]
    Flush 1
    Log_Level info

[INPUT]
    Name tail
    Path /var/log/blitz/*.log
    Parser json
    Tag blitz.*

[OUTPUT]
    Name es
    Match blitz.*
    Host elasticsearch
    Port 9200
    Index blitz-logs
    Type _doc
```

## Environment Variables

### Core Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `FLASK_ENV` | `production` | Environment mode |
| `APP_VERSION` | `unknown` | Application version for metrics |
| `LOG_LEVEL` | `INFO` | Logging level |

### Health & Metrics

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_METRICS` | `false` | Enable Prometheus metrics |
| `PROMETHEUS_MULTIPROC_DIR` | - | Directory for multiprocess metrics |

### Rate Limiting

| Variable | Default | Description |
|----------|---------|-------------|
| `RATE_LIMIT_REDIS_URL` | - | Redis URL for distributed limiting |
| `RATE_LIMITS_START` | `10/minute` | Bot start rate limit |
| `RATE_LIMITS_STOP` | `10/minute` | Bot stop rate limit |
| `RATE_LIMITS_RECOVER` | `10/minute` | Bot recover rate limit |
| `RATE_LIMITS_STATUS` | `30/minute` | Status check rate limit |
| `RATE_LIMITS_GLOBAL` | `200/minute` | Global rate limit ceiling |

### Security

| Variable | Default | Description |
|----------|---------|-------------|
| `SECURITY_CSP` | (see code) | Content Security Policy |
| `MAX_REQUEST_BYTES` | `1048576` | Max request size (1MB) |
| `SESSION_SECURE` | `false` | Secure session cookies |
| `CSRF_SSL_STRICT` | `false` | Strict CSRF over SSL |

### Maintenance

| Variable | Default | Description |
|----------|---------|-------------|
| `MAINTENANCE_MODE_DEFAULT` | `false` | Default maintenance state |
| `BROADCAST_BANNER` | - | Default banner message |

## Troubleshooting

### High CPU Usage
- Check active bot count: `curl /metrics | grep active_bots`
- Review rate limit settings
- Consider adding more worker processes

### High Memory Usage  
- Monitor SQLite cache settings
- Check for memory leaks in bot threads
- Review Prometheus metrics retention

### Database Locks
- Ensure WAL mode is enabled
- Check for long-running transactions
- Monitor database connection pool

### Rate Limit Issues
- Verify Redis connectivity if configured
- Check rate limit configuration
- Review user distribution across limits

### Connection Issues
- Verify Nginx upstream configuration
- Check Gunicorn worker count
- Monitor system file descriptor limits