# SimpleBotManager Deployment Guide

Complete server setup instructions for deploying the SimpleBotManager lite server on Ubuntu.

## Prerequisites

- Ubuntu 20.04+ or similar Linux distribution
- Python 3.8+ installed
- sudo access for system configuration
- Basic familiarity with systemd services

## Step 1: System Preparation

### Update System
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git curl
```

### Create User (Optional but Recommended)
```bash
sudo useradd -m -s /bin/bash blitzbot
sudo usermod -aG sudo blitzbot
su - blitzbot
```

## Step 2: Application Setup

### Clone Repository
```bash
cd /home/blitzbot
git clone https://github.com/Sungyongum/blitz-test-server.git
cd blitz-test-server
```

### Create Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Install Additional Dependencies
```bash
pip install flask-session psutil redis
```

## Step 3: Database Setup

### Create Instance Directory
```bash
mkdir -p instance
chmod 755 instance
```

### Initialize Database
```bash
# Set environment for database creation
export FLASK_APP=run.py

# Create database tables
python -c "
from Blitz_app import create_app
app = create_app()
with app.app_context():
    from Blitz_app.extensions import db
    db.create_all()
    print('✅ Database initialized successfully')
"
```

### Verify Database Creation
```bash
ls -la instance/
# Should show users.db file
```

### Test Database Connection
```bash
python -c "
from Blitz_app import create_app
app = create_app()
with app.app_context():
    from Blitz_app.models import User
    count = User.query.count()
    print(f'✅ Database connected. Users: {count}')
"
```

## Step 4: Configuration

### Environment Configuration
```bash
cat > .env << 'EOF'
# Global settings for SimpleBotManager lite server
LOG_LEVEL=INFO
WEB_HOST=0.0.0.0
WEB_PORT=8000

# Optional: Custom database path
# BLITZ_DB_PATH=/home/blitzbot/blitz-test-server/instance/users.db

# Flask settings
FLASK_SECRET_KEY=your-secure-secret-key-here-change-this
EOF
```

### Generate Secure Secret Key
```bash
python -c "import secrets; print('FLASK_SECRET_KEY=' + secrets.token_urlsafe(32))" >> .env.tmp
grep FLASK_SECRET_KEY .env.tmp >> .env
rm .env.tmp
```

### Set File Permissions
```bash
chmod 600 .env
chmod 644 instance/users.db
chmod 755 instance/
```

## Step 5: Initial User Setup

### Create Admin User
```bash
python -c "
from Blitz_app import create_app
from Blitz_app.models import User
from Blitz_app.extensions import db

app = create_app()
with app.app_context():
    # Check if admin exists
    admin = User.query.filter_by(email='admin@admin.com').first()
    if not admin:
        print('Admin user already exists')
    else:
        print('✅ Admin user created during app initialization')
        print('   Email: admin@admin.com')
        print('   Password: djatjddyd86')
        print('   ⚠️  Change this password immediately!')
"
```

### Create Sample Trading User
```bash
python -c "
from Blitz_app import create_app
from Blitz_app.models import User
from Blitz_app.extensions import db

app = create_app()
with app.app_context():
    # Create sample user
    user = User(
        email='trader@example.com',
        telegram_token='YOUR_TELEGRAM_BOT_TOKEN',
        telegram_chat_id='YOUR_TELEGRAM_CHAT_ID',
        api_key='YOUR_EXCHANGE_API_KEY',
        api_secret='YOUR_EXCHANGE_API_SECRET',
        uid='EXCHANGE_UID',
        symbol='BTC/USDT:USDT',
        side='long',
        take_profit='1%',
        stop_loss='0.5%',
        leverage=10,
        rounds=5,
        repeat=True,
        grids=[],
        exchange='bybit',
        skip_uid_check=False
    )
    user.set_password('secure_password_123')
    
    db.session.add(user)
    db.session.commit()
    print('✅ Sample trading user created')
    print('   Email: trader@example.com')
    print('   Password: secure_password_123')
"
```

## Step 6: Test Application

### Manual Test
```bash
# Activate virtual environment
source venv/bin/activate

# Start application
python run.py
```

### Test Endpoints (in another terminal)
```bash
# Test debug endpoint
curl http://localhost:8000/__debug/db

# Test web interface (should redirect to login)
curl -I http://localhost:8000/

# Expected output: HTTP 302 redirect to login
```

### Stop Test Server
```bash
# Press Ctrl+C in the terminal running the app
```

## Step 7: Systemd Service Setup

### Create Service File
```bash
sudo tee /etc/systemd/system/blitz-bot-web.service << 'EOF'
[Unit]
Description=SimpleBotManager Web Server
After=network.target

[Service]
Type=simple
User=blitzbot
Group=blitzbot
WorkingDirectory=/home/blitzbot/blitz-test-server
Environment=PATH=/home/blitzbot/blitz-test-server/venv/bin
ExecStart=/home/blitzbot/blitz-test-server/venv/bin/python run.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=blitz-bot-web

# Security settings
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/home/blitzbot/blitz-test-server

[Install]
WantedBy=multi-user.target
EOF
```

### Enable and Start Service
```bash
sudo systemctl daemon-reload
sudo systemctl enable blitz-bot-web
sudo systemctl start blitz-bot-web
```

### Check Service Status
```bash
sudo systemctl status blitz-bot-web
```

### View Service Logs
```bash
sudo journalctl -u blitz-bot-web -f
```

## Step 8: Firewall Configuration

### UFW Setup (if using UFW)
```bash
# Enable firewall
sudo ufw enable

# Allow SSH (adjust port if needed)
sudo ufw allow 22/tcp

# Allow web server
sudo ufw allow 8000/tcp

# Check status
sudo ufw status
```

### iptables Alternative
```bash
# Allow incoming connections on port 8000
sudo iptables -A INPUT -p tcp --dport 8000 -j ACCEPT

# Save rules (Ubuntu/Debian)
sudo iptables-save > /etc/iptables/rules.v4
```

## Step 9: Nginx Reverse Proxy (Optional)

### Install Nginx
```bash
sudo apt install -y nginx
```

### Configure Reverse Proxy
```bash
sudo tee /etc/nginx/sites-available/blitz-bot << 'EOF'
server {
    listen 80;
    server_name your-domain.com;  # Change this
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support (if needed)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
EOF
```

### Enable Site
```bash
sudo ln -s /etc/nginx/sites-available/blitz-bot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

## Step 10: SSL/TLS Setup with Certbot (Optional)

### Install Certbot
```bash
sudo apt install -y certbot python3-certbot-nginx
```

### Obtain Certificate
```bash
sudo certbot --nginx -d your-domain.com
```

### Auto-renewal Test
```bash
sudo certbot renew --dry-run
```

## Step 11: Monitoring and Maintenance

### Log Rotation
```bash
sudo tee /etc/logrotate.d/blitz-bot << 'EOF'
/var/log/blitz-bot/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0644 blitzbot blitzbot
}
EOF
```

### Create Log Directory
```bash
sudo mkdir -p /var/log/blitz-bot
sudo chown blitzbot:blitzbot /var/log/blitz-bot
```

### Health Check Script
```bash
tee /home/blitzbot/health-check.sh << 'EOF'
#!/bin/bash
# SimpleBotManager Health Check

echo "=== SimpleBotManager Health Check ==="
echo "Date: $(date)"
echo

# Check service status
echo "Service Status:"
systemctl is-active blitz-bot-web
echo

# Check database
echo "Database Status:"
curl -s http://localhost:8000/__debug/db | python3 -m json.tool | grep -E '"db_exists|db_path"'
echo

# Check port
echo "Port Status:"
ss -tlnp | grep :8000
echo

# Check logs for errors
echo "Recent Errors:"
journalctl -u blitz-bot-web --since "1 hour ago" | grep -i error | tail -5
echo

echo "=== Health Check Complete ==="
EOF

chmod +x /home/blitzbot/health-check.sh
```

### Backup Script
```bash
tee /home/blitzbot/backup-db.sh << 'EOF'
#!/bin/bash
# Database backup script

BACKUP_DIR="/home/blitzbot/backups"
DATE=$(date +%Y%m%d_%H%M%S)
DB_FILE="/home/blitzbot/blitz-test-server/instance/users.db"

mkdir -p $BACKUP_DIR

# SQLite backup
sqlite3 $DB_FILE ".backup $BACKUP_DIR/users_$DATE.db"

# Compress
gzip "$BACKUP_DIR/users_$DATE.db"

# Keep only last 7 days
find $BACKUP_DIR -name "users_*.db.gz" -mtime +7 -delete

echo "Backup completed: users_$DATE.db.gz"
EOF

chmod +x /home/blitzbot/backup-db.sh
```

### Cron Jobs
```bash
# Add to crontab
crontab -e

# Add these lines:
# Daily database backup at 2 AM
0 2 * * * /home/blitzbot/backup-db.sh

# Health check every 30 minutes
*/30 * * * * /home/blitzbot/health-check.sh >> /var/log/blitz-bot/health.log
```

## Step 12: Smoke Tests

### Basic Functionality Test
```bash
#!/bin/bash
echo "=== SimpleBotManager Smoke Tests ==="

# Test 1: Database connection
echo "Test 1: Database connection"
response=$(curl -s http://localhost:8000/__debug/db)
if echo "$response" | grep -q '"db_exists": true'; then
    echo "✅ Database is accessible"
else
    echo "❌ Database not accessible"
fi

# Test 2: Web server response
echo "Test 2: Web server response"
http_code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/)
if [ "$http_code" = "302" ]; then
    echo "✅ Web server responding (redirecting to login)"
else
    echo "❌ Web server not responding correctly (HTTP $http_code)"
fi

# Test 3: Service status
echo "Test 3: Service status"
if systemctl is-active --quiet blitz-bot-web; then
    echo "✅ Service is running"
else
    echo "❌ Service is not running"
fi

echo "=== Smoke Tests Complete ==="
```

## Troubleshooting

### Common Issues

1. **Port already in use**
   ```bash
   sudo ss -tlnp | grep :8000
   # Kill process or change port in .env
   ```

2. **Permission denied on database**
   ```bash
   sudo chown blitzbot:blitzbot instance/users.db
   chmod 644 instance/users.db
   ```

3. **Service won't start**
   ```bash
   sudo journalctl -u blitz-bot-web -n 50
   # Check for Python import errors or missing dependencies
   ```

4. **Database locked errors**
   ```bash
   # Check for multiple processes accessing DB
   ps aux | grep python
   # Ensure WAL mode is enabled (it should be automatic)
   ```

### Performance Tuning

1. **SQLite Optimizations** (already configured)
   - WAL mode enabled
   - Proper cache sizing
   - Timeout handling

2. **System Limits**
   ```bash
   # Increase file descriptor limits if needed
   echo "blitzbot soft nofile 65536" | sudo tee -a /etc/security/limits.conf
   echo "blitzbot hard nofile 65536" | sudo tee -a /etc/security/limits.conf
   ```

## Bot Daemon (Future Enhancement)

The lite server is designed to support an optional bot daemon for advanced features. Here's the preparation:

### Daemon Service Template
```bash
# /etc/systemd/system/blitz-bot-daemon.service (future use)
[Unit]
Description=SimpleBotManager Bot Daemon
After=network.target blitz-bot-web.service

[Service]
Type=simple
User=blitzbot
Group=blitzbot
WorkingDirectory=/home/blitzbot/blitz-test-server
Environment=PATH=/home/blitzbot/blitz-test-server/venv/bin
ExecStart=/home/blitzbot/blitz-test-server/venv/bin/python -m bot_daemon
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=blitz-bot-daemon

[Install]
WantedBy=multi-user.target
```

## Security Hardening

### File Permissions
```bash
# Secure configuration files
chmod 600 .env
chmod 700 instance/
chmod 600 instance/users.db

# Secure application directory
chown -R blitzbot:blitzbot /home/blitzbot/blitz-test-server
```

### Fail2ban (Optional)
```bash
sudo apt install -y fail2ban

# Create jail for repeated login failures
sudo tee /etc/fail2ban/jail.d/blitz-bot.conf << 'EOF'
[blitz-bot]
enabled = true
port = 8000
filter = blitz-bot
logpath = /var/log/blitz-bot/access.log
maxretry = 5
bantime = 3600
findtime = 600
EOF
```

This completes the deployment guide for SimpleBotManager. The server should now be running securely with proper monitoring and maintenance capabilities.

# Production Single-Server Deployment

This section provides production-ready configuration for single-server deployment using Gunicorn, systemd, and nginx reverse proxy.

## Overview

This deployment approach provides:
- **Production WSGI server**: Gunicorn with optimized worker configuration
- **Process management**: systemd service with automatic restart and monitoring
- **Reverse proxy**: nginx with security headers, rate limiting, and SSL support
- **Monitoring**: Health check endpoints and optional Prometheus metrics
- **Security**: Comprehensive security hardening and CSP headers

## Quick Start for Production

### Step 1: Environment Configuration

Choose and copy an environment template:

```bash
# For basic production deployment
cp .env.single-server.example .env

# OR for more comprehensive configuration
cp .env.example .env
```

**Generate a secure secret key:**
```bash
python -c "import secrets; print('FLASK_SECRET_KEY=' + secrets.token_urlsafe(32))" >> .env.tmp
grep FLASK_SECRET_KEY .env.tmp >> .env
rm .env.tmp
```

**Edit .env and configure key settings:**
```bash
# Required - replace with your secure key
FLASK_SECRET_KEY=your-generated-secure-key-here

# Enable metrics for production monitoring (optional)
ENABLE_METRICS=true

# Configure rate limits for your load requirements
RATE_LIMITS_START=5/minute
RATE_LIMITS_GLOBAL=100/minute
```

### Step 2: Gunicorn Production Server

**Start with Gunicorn directly:**
```bash
# Install gunicorn if not already installed
pip install gunicorn

# Start server using provided configuration
gunicorn -c gunicorn.conf.py run:app
```

**Or use the convenience script:**
```bash
# Make executable and run
chmod +x scripts/run_gunicorn.sh
./scripts/run_gunicorn.sh
```

**The Gunicorn configuration provides:**
- Optimal worker count: `(2 × CPU cores) + 1`, max 4 for single server
- 2 threads per worker for I/O concurrency
- 60-second timeouts with 5-second keepalive
- Automatic worker recycling after 1000 requests
- Logging to stdout/stderr for systemd compatibility

### Step 3: Systemd Service (Recommended)

**Install the service:**
```bash
# Copy and customize the service file
sudo cp systemd/blitz-test-server.service /etc/systemd/system/

# Edit paths and user settings
sudo nano /etc/systemd/system/blitz-test-server.service
```

**Update these sections in the service file:**
```ini
# Update user and paths
User=blitzbot
Group=blitzbot
WorkingDirectory=/home/blitzbot/blitz-test-server
EnvironmentFile=/etc/blitz-test-server/.env
ExecStart=/home/blitzbot/blitz-test-server/venv/bin/gunicorn -c gunicorn.conf.py run:app
```

**Copy environment file for systemd:**
```bash
sudo mkdir -p /etc/blitz-test-server
sudo cp .env /etc/blitz-test-server/.env
sudo chown root:root /etc/blitz-test-server/.env
sudo chmod 600 /etc/blitz-test-server/.env
```

**Enable and start the service:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable blitz-test-server
sudo systemctl start blitz-test-server

# Check status
sudo systemctl status blitz-test-server

# View logs
sudo journalctl -u blitz-test-server -f
```

### Step 4: Nginx Reverse Proxy

**Install nginx:**
```bash
sudo apt install nginx -y
```

**Configure the reverse proxy:**
```bash
# Copy nginx configuration
sudo cp nginx/blitz-test-server.conf /etc/nginx/sites-available/

# Edit server configuration
sudo nano /etc/nginx/sites-available/blitz-test-server.conf
```

**Update the server_name:**
```nginx
# Change this line to your domain
server_name your-domain.com www.your-domain.com;
```

**Enable the site:**
```bash
sudo ln -s /etc/nginx/sites-available/blitz-test-server.conf /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### Step 5: SSL/TLS Setup (Recommended)

**Install Certbot:**
```bash
sudo apt install certbot python3-certbot-nginx -y
```

**Obtain SSL certificate:**
```bash
sudo certbot --nginx -d your-domain.com -d www.your-domain.com
```

**Update environment for HTTPS:**
```bash
# Edit .env to enable secure cookies
echo "SESSION_SECURE=true" >> .env
echo "CSRF_SSL_STRICT=true" >> .env

# Restart service to apply changes
sudo systemctl restart blitz-test-server
```

## Health Monitoring

The application provides several monitoring endpoints:

### Health Check Endpoints

- `GET /healthz` - Basic health check (returns 200 if app is running)
- `GET /livez` - Liveness check (database connectivity)
- `GET /readyz` - Readiness check (all services ready)

### Prometheus Metrics (Optional)

When `ENABLE_METRICS=true`:
- `GET /metrics` - Prometheus metrics endpoint
- Includes request metrics, response times, error rates
- Multiprocess-safe for Gunicorn workers

### Log Monitoring

**Application logs (via systemd):**
```bash
# Real-time logs
sudo journalctl -u blitz-test-server -f

# Recent logs
sudo journalctl -u blitz-test-server --since "1 hour ago"

# Error logs only
sudo journalctl -u blitz-test-server -p err
```

**Nginx logs:**
```bash
# Access logs
sudo tail -f /var/log/nginx/blitz-test-server-access.log

# Error logs
sudo tail -f /var/log/nginx/blitz-test-server-error.log
```

## Performance Tuning

### Gunicorn Workers

Adjust worker count based on your server:
```python
# In gunicorn.conf.py
workers = min(multiprocessing.cpu_count() * 2 + 1, 4)  # Current setting
workers = 6  # For higher traffic
```

### Database Optimization

The app uses SQLite with optimized settings:
- WAL mode for concurrent reads
- 20MB cache size
- 30-second busy timeout
- Memory temp storage

For high traffic, consider PostgreSQL:
```bash
# Example environment for PostgreSQL
# DATABASE_URL=postgresql://user:pass@localhost/blitzdb
```

### Rate Limiting

Adjust rate limits in `.env`:
```bash
# More restrictive for high-security environments
RATE_LIMITS_START=3/minute
RATE_LIMITS_GLOBAL=50/minute

# More permissive for internal deployments  
RATE_LIMITS_START=20/minute
RATE_LIMITS_GLOBAL=500/minute
```

## Security Hardening

### File Permissions
```bash
# Secure application directory
sudo chown -R blitzbot:blitzbot /home/blitzbot/blitz-test-server
sudo chmod 600 .env
sudo chmod 700 instance/
```

### Firewall Configuration
```bash
# Allow only necessary ports
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable

# Deny direct access to application port
sudo ufw deny 8000/tcp
```

### Additional Security

The configuration includes:
- Security headers (X-Frame-Options, X-Content-Type-Options, CSP)
- Rate limiting at nginx level
- Session security with secure cookies (HTTPS)
- Process isolation via systemd security settings
- Request size limits

## Troubleshooting

### Common Issues

**Service won't start:**
```bash
# Check service status
sudo systemctl status blitz-test-server

# Check logs for errors
sudo journalctl -u blitz-test-server --since "10 minutes ago"

# Validate configuration
cd /home/blitzbot/blitz-test-server
./scripts/run_gunicorn.sh --dry-run
```

**Database errors:**
```bash
# Check database permissions
ls -la instance/
sudo -u blitzbot ls -la instance/

# Test database connectivity
sudo -u blitzbot python -c "
from Blitz_app import create_app
app = create_app()
with app.app_context():
    from Blitz_app.models import User
    print(f'Users: {User.query.count()}')
"
```

**Nginx issues:**
```bash
# Test nginx configuration
sudo nginx -t

# Check error logs
sudo tail -f /var/log/nginx/error.log

# Test backend connectivity
curl http://127.0.0.1:8000/healthz
```

### Performance Issues

**High memory usage:**
- Reduce Gunicorn workers or max_requests
- Check for memory leaks in application code
- Monitor with: `sudo systemctl status blitz-test-server`

**Slow response times:**
- Check database performance
- Review nginx access logs for slow requests
- Monitor with: `curl -w "@curl-format.txt" http://localhost/healthz`

**High CPU usage:**
- Reduce worker threads
- Check for inefficient database queries
- Monitor with: `top -p $(pgrep -f gunicorn)`

## Maintenance

### Regular Tasks

**Weekly:**
- Review application and nginx logs
- Check disk space: `df -h`
- Update system packages: `sudo apt update && sudo apt upgrade`

**Monthly:**
- Rotate logs if not using logrotate
- Review security headers and certificates
- Test backup and restore procedures

**Database Backup:**
```bash
# Backup SQLite database
sudo -u blitzbot cp instance/users.db instance/users.db.backup.$(date +%Y%m%d)

# Automated backup script
cat > backup_db.sh << 'EOF'
#!/bin/bash
sudo -u blitzbot cp instance/users.db instance/users.db.backup.$(date +%Y%m%d_%H%M%S)
find instance/ -name "users.db.backup.*" -mtime +7 -delete
EOF
chmod +x backup_db.sh
```

### Log Rotation

```bash
# Create logrotate configuration
sudo tee /etc/logrotate.d/blitz-test-server << 'EOF'
/var/log/nginx/blitz-test-server-*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    postrotate
        systemctl reload nginx
    endscript
}
EOF
```

This completes the production deployment guide. The server should now be running securely with proper monitoring, logging, and maintenance capabilities.