# Blitz LITE Trading Bot Server

A lightweight Flask server for cryptocurrency trading bot management with thread-based 1:1 bot control and standardized order tagging.

## Features

- **LITE SimpleBotManager**: Thread-based bot management (1:1 user-to-bot mapping)
- **Standardized Order Tags**: Idempotent order identification with `sm_leg_{i}_{userId}_{symbolNoSep}` and `sm_tp_{userId}_{symbolNoSep}` patterns
- **4 Core Endpoints**: Simple API for bot control
- **Admin Console**: Web-based monitoring and management
- **SQLite with WAL**: High-performance database with proper PRAGMA optimizations
- **No User Secrets in .env**: All user credentials stored securely in database

## API Endpoints

### Bot Control (User)
- `POST /api/bot/start` - Start bot for current user (409 on duplicate)
- `POST /api/bot/stop` - Stop bot for current user
- `GET /api/bot/status` - Get bot status for current user
- `POST /api/bot/recover` - Recover orders (idempotent, creates missing TP/ladder legs)

### Admin
- `GET /admin/simple/status` - JSON overview of all managed users

### Diagnostics
- `GET /__debug/db` - Database path and connection info

## Web Interface

- **GET /** - Simple user control page with 4 buttons
- **GET /admin/console** - Admin console with user management and status polling

## Configuration

### Environment Variables
The `.env` file should contain only global settings:

```bash
# Optional database path override
BLITZ_DB_PATH=/custom/path/to/users.db

# Optional security settings
BLITZ_SECRET_KEY=your-secret-key-here

# Optional logging level
LOG_LEVEL=INFO
```

### Database
- **Default Path**: `instance/users.db` (absolute path)
- **Override**: Set `BLITZ_DB_PATH` environment variable
- **SQLite PRAGMAs**: Automatically configured for performance
  - `journal_mode=WAL` (concurrent reads)
  - `busy_timeout=30000` (30 second wait)
  - `synchronous=NORMAL` (balanced performance)
  - `temp_store=MEMORY` (faster temporary operations)
  - `cache_size=-20000` (~20MB cache)
  - `foreign_keys=ON` (referential integrity)

## Order Tag Patterns

All orders use standardized idempotent tags for reliable identification:

- **Entry/Ladder Orders**: `sm_leg_{leg_index}_{user_id}_{symbol_clean}`
- **Take Profit Orders**: `sm_tp_{user_id}_{symbol_clean}`

Where:
- `{leg_index}`: Grid/ladder position (1, 2, 3, ...)
- `{user_id}`: Database user ID
- `{symbol_clean}`: Symbol with `/` and `:` removed (e.g., `BTCUSDT`)

Tags are propagated to all CCXT order fields: `text`, `clientOrderId`, `clientOrderID`, `newClientOrderId`, `orderLinkId`, `label`.

## Installation & Setup

1. **Clone repository**:
   ```bash
   git clone https://github.com/Sungyongum/blitz-test-server.git
   cd blitz-test-server
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Initialize database**:
   ```bash
   python -c "from Blitz_app import create_app; app = create_app(); app.app_context().push(); from Blitz_app.extensions import db; db.create_all()"
   ```

4. **Run the server**:
   ```bash
   python run.py
   ```

## Development

### Running Tests
```bash
python -m unittest tests.test_simple_manager_lite -v
```

### Testing Endpoints
```bash
# Check database info
curl http://localhost:8000/__debug/db

# Get bot status (requires authentication)
curl -b cookies.txt http://localhost:8000/api/bot/status

# Start bot (requires authentication)
curl -X POST -b cookies.txt http://localhost:8000/api/bot/start

# Admin status (requires admin authentication)
curl -b admin_cookies.txt http://localhost:8000/admin/simple/status
```

## Security Notes

- **No User Secrets in Environment**: All user API keys/secrets are stored in the database only
- **Admin Access**: Restricted to `admin@admin.com` user
- **CSRF Protection**: Enabled for web interface
- **Thread Safety**: All bot operations are protected with locks

## Legacy Endpoint Migration

The following legacy endpoints are deprecated and redirect to LITE controls:
- `/force_refresh` → Use `/api/bot/start`
- `/single_refresh` → Use `/api/bot/recover`
- `/clear_force_refresh` → Use `/api/bot/stop`
- `/exit_and_stop` → Use `/api/bot/stop`

## Architecture

- **SimpleBotManager**: Thread-based manager with 1:1 user mapping
- **Standardized Tags**: Consistent order identification across exchanges
- **LITE Design**: Minimal endpoints, reduced complexity
- **Database-First**: User credentials and state stored in SQLite
- **Thread-Safe**: Proper locking for concurrent operations

## Supported Exchanges

- Bybit (primary)
- BingX (with hedge mode support)

For detailed deployment instructions, see [DEPLOYMENT.md](DEPLOYMENT.md).