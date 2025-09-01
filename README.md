# SimpleBotManager Lite Server

A lightweight trading bot management server implementing the SimpleBotManager 1:1 model with minimal endpoints and DB-backed user credentials.

## Overview

This is a **LITE** version of the blitz trading bot server that focuses on simplicity, safety, and production readiness. It implements a direct-call model where HTTP routes communicate directly with the SimpleBotManager without requiring a separate daemon process.

### Key Features

- **1:1 Bot Management**: One bot thread per user with strict duplicate start rejection
- **DB-Backed Credentials**: All user API keys and settings loaded from database (NO .env secrets)
- **Idempotent Order Tags**: Standardized order IDs for reliable order management
- **Minimal API**: Just 4 user endpoints + 1 admin endpoint
- **Thread-Based**: Lightweight threading instead of heavy subprocess management
- **SQLite + WAL**: High-performance database with proper concurrency support

## API Endpoints

### User Endpoints

#### `POST /api/bot/start`
Start a bot for the authenticated user. Duplicate starts are rejected.

**Response:**
```json
{
  "success": true,
  "message": "Bot started successfully",
  "status": "started"
}
```

#### `POST /api/bot/stop`
Stop the bot for the authenticated user.

**Response:**
```json
{
  "success": true,
  "message": "Bot stopped successfully", 
  "status": "stopped"
}
```

#### `GET /api/bot/status`
Get the current bot status for the authenticated user.

**Response:**
```json
{
  "running": true,
  "status": "running",
  "uptime": 1234,
  "message": "Bot is running"
}
```

#### `POST /api/bot/recover`
Recover missing orders (create missing TP and ladder legs only). No destructive resets.

**Response:**
```json
{
  "success": true,
  "message": "Recovery process completed",
  "actions": ["checked_positions", "created_tp"]
}
```

### Admin Endpoint

#### `GET /admin/simple/status`
Get overview of all managed bots (admin only).

**Response:**
```json
{
  "users": {
    "123": {
      "running": true,
      "status": "running", 
      "uptime": 1234
    }
  },
  "totals": {
    "total_managed": 1,
    "total_running": 1,
    "timestamp": "2025-01-01T12:00:00"
  }
}
```

### Debug Endpoint

#### `GET /__debug/db`
Database diagnostic information.

**Response:**
```json
{
  "cwd": "/app",
  "instance_path": "/app/instance",
  "db_uri": "sqlite:////app/instance/users.db",
  "db_path": "/app/instance/users.db",
  "db_exists": true,
  "timestamp": "2025-01-01T12:00:00"
}
```

## Order Tag System

The SimpleBotManager uses standardized idempotent order tags to ensure reliable order management:

### Tag Patterns

- **Ladder Legs**: `sm_leg_{index}_{userId}_{symbolNoSep}`
  - Example: `sm_leg_0_123_BTCUSDT`
- **Take Profit**: `sm_tp_{userId}_{symbolNoSep}`  
  - Example: `sm_tp_123_BTCUSDT`

### Symbol Cleaning
Symbols are cleaned by removing `/` and `:` characters:
- `BTC/USDT:USDT` → `BTCUSDTUSDT`
- `ETH/USDT:USDT` → `ETHUSDTUSDT`

### CCXT Field Propagation
Tags are propagated to all possible CCXT order fields:
- `text`
- `clientOrderId`
- `clientOrderID`
- `newClientOrderId`
- `orderLinkId`
- `label`

## Environment Configuration

The `.env` file contains **ONLY** global settings. User credentials are stored in the database.

```bash
# Global settings only - NO user API keys
LOG_LEVEL=INFO
WEB_HOST=0.0.0.0
WEB_PORT=8000
# Optional: Override default DB path
# BLITZ_DB_PATH=/path/to/custom/users.db
```

## Database

### SQLite Configuration
- **File**: `instance/users.db` (absolute path)
- **Mode**: WAL (Write-Ahead Logging) for concurrency
- **Optimizations**: 
  - `journal_mode=WAL`
  - `busy_timeout=30000` 
  - `synchronous=NORMAL`
  - `temp_store=MEMORY`
  - `cache_size=-20000` (~20MB)
  - `foreign_keys=ON`

### User Model
Users are stored in the database with their trading credentials:
- `api_key` / `api_secret`: Exchange API credentials
- `telegram_token` / `telegram_chat_id`: Telegram notifications
- `exchange`: Trading exchange ('bybit', 'bingx', etc.)
- `symbol`: Trading pair (e.g., 'BTC/USDT:USDT')
- `side`: Position side ('long', 'short')
- `leverage`: Trading leverage
- Additional trading parameters...

## Web Interface

### User Interface (`/`)
Simplified control panel with 4 core buttons for bot management:
- **🚀 Start Bot**: Start the trading bot for current user
- **🛑 Stop Bot**: Stop the trading bot for current user  
- **📊 Get Status**: Check bot status and uptime
- **🔧 Recover Orders**: Recover missing orders (idempotent, safe to retry)

The interface now mirrors blitz-test styling and focuses on the essential bot control functions with CSRF-protected API calls for security.

### Admin Interface (`/admin/lite`)
Basic management console for admins:
- Overview of all users and bot statuses
- Per-user controls: Force Start, Force Stop, Reconcile
- Real-time status updates

## Security

### Credential Handling
- ✅ No plaintext API keys in logs (masked as `***XXXX`)
- ✅ All user credentials stored in database only
- ✅ No environment variables with sensitive data
- ✅ Proper session management with Flask-Login

### Logging
- **INFO**: State transitions (start, stop, recover)
- **ERROR**: Exceptions and failures
- **No secrets**: API keys are masked in all log output

## Architecture

### SimpleBotManager Class
```python
class SimpleBotManager:
    def start_bot_for_user(user_id: int) -> dict
    def stop_bot_for_user(user_id: int) -> dict  
    def get_bot_status(user_id: int) -> dict
    def recover_orders_for_user(user_id: int) -> dict
    def get_all_bot_statuses() -> dict  # Admin only
```

### Thread Management
- **managed_bots**: `Dict[int, dict]` mapping user_id to bot info
- **Bot Info**: `{thread, stop_event, start_time, status}`
- **Thread Safety**: All operations protected by threading.Lock()

### Bot Lifecycle
1. **Start**: Create thread, validate credentials, update DB status
2. **Run**: Execute trading logic with standardized order tags
3. **Stop**: Signal stop event, wait for graceful shutdown
4. **Cleanup**: Remove from managed_bots, update DB status

## Removed Features

For the LITE version, the following heavy features were removed:
- ❌ Subprocess-based bot management
- ❌ Polling daemon architecture  
- ❌ Admin telegram/email alerts
- ❌ Complex proxy management alerts
- ❌ Force refresh mechanisms
- ❌ Random order tag generation
- ❌ Environment-based user credentials
- ❌ Redis session dependency (uses filesystem)

## Recent Improvements

### v1.1 - Unified Bot Management & Security Enhancements

#### Fixed Global Start Bug
- **Issue**: Legacy routes could potentially conflict with SimpleBotManager
- **Fix**: All bot start/stop operations now use SimpleBotManager exclusively
- **Verification**: Added regression test `test_no_global_start_regression`

#### Enhanced Security
- **CSRF Protection**: Added CSRF token validation for all POST requests
- **API Security**: API endpoints properly exempted from CSRF (intended for programmatic access)
- **Template Security**: CSRF tokens automatically included in UI fetch calls

#### Recovery Flow Improvements  
- **Idempotence**: `recover_orders_for_user` can be safely called multiple times
- **Testing**: Added `test_recover_orders_idempotence` for verification
- **UI Feedback**: Clear success/error messages with detailed actions taken

#### Template Refinements
- **Simplified UI**: Index page focused on 4 core control buttons
- **Improved UX**: Better status indicators and real-time feedback
- **Consistent Styling**: Enhanced visual consistency across the interface

#### Testing Coverage
- ✅ No global start regression test
- ✅ Recovery idempotence test  
- ✅ Thread safety validation
- ✅ Duplicate start rejection
- ✅ Order tag consistency


Run the test suite to validate functionality:

```bash
cd /path/to/blitz-test-server
python tests/test_simple_manager_lite.py
```

### Test Coverage
- ✅ SimpleBotManager duplicate start rejection
- ✅ Idempotent order tag patterns
- ✅ Recovery operation safety
- ✅ Thread safety and concurrency
- ✅ Status reporting accuracy

## Production Considerations

### Performance
- SQLite WAL mode supports multiple concurrent readers
- Thread-based architecture is lightweight and efficient
- Minimal memory footprint compared to subprocess model

### Monitoring
- Use `/__debug/db` for database health checks
- Monitor `/admin/simple/status` for bot overview
- Check logs for state transitions and errors

### Scaling
- Current design supports moderate user loads
- For high scale, consider upgrading to PostgreSQL
- Bot daemon can be added later if needed (architecture ready)

## Future Enhancements

The LITE architecture is designed to support future additions:
- **Bot Daemon**: Separate daemon process for advanced monitoring
- **Advanced Analytics**: Detailed performance tracking
- **Multi-Exchange**: Enhanced exchange support
- **Load Balancing**: Horizontal scaling capabilities

## Troubleshooting

### Common Issues

1. **Database locked**: Check WAL mode is enabled
2. **Bot won't start**: Verify user credentials in DB
3. **Permission denied**: Check file permissions on instance/
4. **Port in use**: Change WEB_PORT in .env

### Debug Commands

```bash
# Check database status
curl http://localhost:8000/__debug/db

# Check bot status (requires login)
curl -b cookies.txt http://localhost:8000/api/bot/status

# View logs
tail -f logs/app.log
```