# Blitz LITE Server Deployment Guide

This guide covers deploying the Blitz LITE trading bot server from scratch on Ubuntu.

## Server Setup (Ubuntu 20.04+)

### 1. System Dependencies

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python and required packages
sudo apt install -y python3 python3-pip python3-venv nginx supervisor

# Install development tools (if needed)
sudo apt install -y build-essential python3-dev
```

### 2. Create Application User

```bash
# Create dedicated user for the application
sudo useradd -m -s /bin/bash blitzbot
sudo usermod -aG sudo blitzbot

# Switch to application user
sudo su - blitzbot
```

### 3. Application Setup

```bash
# Clone the repository
cd ~
git clone https://github.com/Sungyongum/blitz-test-server.git
cd blitz-test-server

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create instance directory and set permissions
mkdir -p instance
chmod 750 instance
```

### 4. Database Initialization

```bash
# Initialize the database with proper path
python -c "
from Blitz_app import create_app
app = create_app()
with app.app_context():
    from Blitz_app.extensions import db
    db.create_all()
    print('✅ Database initialized at:', app.config['SQLALCHEMY_DATABASE_URI'])
"
```

### 5. Environment Configuration

```bash
# Create .env file with global settings
cat > .env << 'EOF'
# Flask settings
BLITZ_SECRET_KEY=$(openssl rand -hex 32)
FLASK_ENV=production

# Optional: Custom database path
# BLITZ_DB_PATH=/home/blitzbot/blitz-test-server/instance/users.db

# Logging
LOG_LEVEL=INFO
EOF

# Secure the environment file
chmod 600 .env
```

## Production Deployment

### 1. Gunicorn Configuration

```bash
# Install gunicorn
pip install gunicorn

# Create gunicorn configuration
cat > gunicorn.conf.py << 'EOF'
bind = "127.0.0.1:8000"
workers = 2
worker_class = "sync"
worker_connections = 1000
timeout = 30
keepalive = 2
max_requests = 1000
max_requests_jitter = 100
preload_app = True
user = "blitzbot"
group = "blitzbot"
daemon = False
pidfile = "/home/blitzbot/blitz-test-server/gunicorn.pid"
accesslog = "/home/blitzbot/blitz-test-server/logs/access.log"
errorlog = "/home/blitzbot/blitz-test-server/logs/error.log"
loglevel = "info"
EOF

# Create logs directory
mkdir -p logs
```

### 2. Systemd Service

```bash
# Exit from blitzbot user
exit

# Create systemd service file
sudo tee /etc/systemd/system/blitz-lite.service << 'EOF'
[Unit]
Description=Blitz LITE Trading Bot Server
After=network.target

[Service]
Type=exec
User=blitzbot
Group=blitzbot
WorkingDirectory=/home/blitzbot/blitz-test-server
Environment=PATH=/home/blitzbot/blitz-test-server/venv/bin
ExecStart=/home/blitzbot/blitz-test-server/venv/bin/gunicorn -c gunicorn.conf.py run:app
ExecReload=/bin/kill -s HUP $MAINPID
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Enable and start the service
sudo systemctl daemon-reload
sudo systemctl enable blitz-lite.service
sudo systemctl start blitz-lite.service
```

### 3. Nginx Configuration

```bash
# Create nginx site configuration
sudo tee /etc/nginx/sites-available/blitz-lite << 'EOF'
server {
    listen 80;
    server_name your-domain.com;  # Change this to your domain

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }

    # Optional: Static files (if serving directly)
    location /static/ {
        alias /home/blitzbot/blitz-test-server/static/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
EOF

# Enable the site
sudo ln -s /etc/nginx/sites-available/blitz-lite /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 4. SSL Certificate (Optional, Recommended)

```bash
# Install certbot
sudo apt install -y certbot python3-certbot-nginx

# Get SSL certificate
sudo certbot --nginx -d your-domain.com

# Auto-renewal is typically set up automatically
sudo systemctl status certbot.timer
```

## Health Checks & Monitoring

### 1. Service Health Check

```bash
# Check service status
sudo systemctl status blitz-lite.service

# View logs
sudo journalctl -u blitz-lite.service -f

# Check database connectivity
curl -s http://localhost:8000/__debug/db | jq
```

### 2. Database Health

```bash
# Check database file
ls -la /home/blitzbot/blitz-test-server/instance/users.db*

# SQLite integrity check
sudo -u blitzbot sqlite3 /home/blitzbot/blitz-test-server/instance/users.db "PRAGMA integrity_check;"

# Check WAL mode
sudo -u blitzbot sqlite3 /home/blitzbot/blitz-test-server/instance/users.db "PRAGMA journal_mode;"
```

### 3. Performance Monitoring

```bash
# Create monitoring script
sudo -u blitzbot tee /home/blitzbot/monitor.sh << 'EOF'
#!/bin/bash
echo "=== Blitz LITE Server Status ==="
echo "Service Status:"
systemctl is-active blitz-lite.service

echo -e "\nDatabase Info:"
curl -s http://localhost:8000/__debug/db 2>/dev/null | python3 -m json.tool || echo "Service not responding"

echo -e "\nAdmin Status:"
# Note: This requires authentication, implement as needed
# curl -s -u admin:password http://localhost:8000/admin/simple/status

echo -e "\nSystem Resources:"
echo "Memory: $(free -h | grep ^Mem | awk '{print $3 "/" $2}')"
echo "Disk: $(df -h /home/blitzbot | tail -1 | awk '{print $3 "/" $2 " (" $5 " used)"}')"
echo "Load: $(uptime | awk -F'load average:' '{print $2}')"
EOF

chmod +x /home/blitzbot/monitor.sh
```

## Testing Deployment

### 1. Basic Functionality

```bash
# Test database endpoint
curl http://localhost:8000/__debug/db

# Expected response:
# {
#   "cwd": "/home/blitzbot/blitz-test-server",
#   "instance_path": "/home/blitzbot/blitz-test-server/instance",
#   "db_uri": "sqlite:////.../instance/users.db",
#   "db_path": "/home/blitzbot/blitz-test-server/instance/users.db",
#   "exists": true
# }
```

### 2. Web Interface

```bash
# Test web interface (should redirect to login)
curl -I http://localhost:8000/

# Expected: 302 redirect to login page
```

### 3. Load Test (Optional)

```bash
# Install apache bench
sudo apt install -y apache2-utils

# Simple load test
ab -n 100 -c 10 http://localhost:8000/__debug/db
```

## Maintenance

### 1. Updates

```bash
# Switch to application user
sudo su - blitzbot
cd blitz-test-server

# Pull updates
git pull origin main

# Update dependencies if needed
source venv/bin/activate
pip install -r requirements.txt

# Restart service
sudo systemctl restart blitz-lite.service
```

### 2. Backup

```bash
# Create backup script
cat > /home/blitzbot/backup.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/home/blitzbot/backups"
DATE=$(date +%Y%m%d_%H%M%S)
DB_PATH="/home/blitzbot/blitz-test-server/instance/users.db"

mkdir -p "$BACKUP_DIR"

# Backup database
sqlite3 "$DB_PATH" ".backup $BACKUP_DIR/users_$DATE.db"

# Keep last 7 days
find "$BACKUP_DIR" -name "users_*.db" -mtime +7 -delete

echo "Backup completed: users_$DATE.db"
EOF

chmod +x /home/blitzbot/backup.sh

# Add to crontab for daily backups
(crontab -l 2>/dev/null; echo "0 2 * * * /home/blitzbot/backup.sh") | crontab -
```

### 3. Log Rotation

```bash
# Create logrotate configuration
sudo tee /etc/logrotate.d/blitz-lite << 'EOF'
/home/blitzbot/blitz-test-server/logs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 644 blitzbot blitzbot
    postrotate
        systemctl reload blitz-lite.service
    endscript
}
EOF
```

## Troubleshooting

### Common Issues

1. **Service won't start**:
   ```bash
   sudo journalctl -u blitz-lite.service --no-pager
   ```

2. **Database permission errors**:
   ```bash
   sudo chown -R blitzbot:blitzbot /home/blitzbot/blitz-test-server/instance/
   ```

3. **Port already in use**:
   ```bash
   sudo netstat -tlnp | grep :8000
   sudo systemctl stop blitz-lite.service
   ```

4. **Memory issues**:
   ```bash
   free -h
   # Consider reducing gunicorn workers if low memory
   ```

### Support

For issues and support:
- Check logs: `sudo journalctl -u blitz-lite.service -f`
- Monitor health: `/home/blitzbot/monitor.sh`
- Database check: `curl http://localhost:8000/__debug/db`

## Security Considerations

1. **Firewall**: Configure ufw to only allow necessary ports
2. **User Permissions**: Never run as root
3. **Database**: Regular backups and integrity checks
4. **SSL**: Always use HTTPS in production
5. **Monitoring**: Set up alerts for service failures