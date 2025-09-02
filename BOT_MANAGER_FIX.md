# Bot Manager /tmp Permission Fix

## Problem Summary

After restarting the server, the Bot Manager logs showed permission errors when trying to start per-user bot runner scripts under `/tmp`:

- ❌ Failed to start bot for user 2: [Errno 13] Permission denied: '/tmp/bot_runner_2.py'
- ❌ Failed to start bot for user 3: [Errno 13] Permission denied: '/tmp/bot_runner_3.py'

This was a regression to the old behavior where the manager generated an executable script in `/tmp` and attempted to execute it directly. On some systems `/tmp` may be mounted with `noexec` or scripts may lack the execute bit, causing Permission denied errors.

## Solution Implemented

### Key Changes

1. **Eliminated `/tmp` dependency**: Bot runner scripts are now created in a configurable directory under the project path
2. **Use Python interpreter**: Scripts are executed via `python -u script.py` instead of direct execution, eliminating the need for execute permissions
3. **Configurable paths**: Both the runner directory and Python executable are configurable via environment variables
4. **Enhanced logging**: Comprehensive logging with file system diagnostics for troubleshooting
5. **Automatic cleanup**: Stale runner scripts are cleaned up automatically

### New Environment Variables

```bash
# Bot runner script directory (default: ./runtime/bot_runners)
BOT_RUNNER_DIR=/srv/blitz-test-server/runtime/bot_runners

# Python executable for bot processes (default: .venv/bin/python or sys.executable)
BLITZ_PYTHON=/usr/bin/python3
```

### Code Changes Made

**File: `Blitz_app/bot_manager.py`**

1. **Configuration Setup** (lines 51-102):
   - Added `_init_bot_runner_dir()` method with fallback logic
   - Added `_init_python_executable()` method with virtual environment detection
   - Directory creation with proper permissions (0o770)

2. **Script Execution Fix** (lines 188-243):
   - Changed from `/tmp/bot_runner_{user_id}.py` to `{bot_runner_dir}/bot_runner_{user_id}.py`
   - Changed from `[sys.executable, script_path]` to `[python_executable, '-u', script_path]`
   - Set script permissions to 0o640 (read-only, no execute needed)

3. **Enhanced Logging** (lines 290-310):
   - Added file system diagnostics in error cases
   - Include mount options detection for troubleshooting
   - Log Python executable and script paths

4. **Cleanup Implementation** (lines 462-487):
   - `_cleanup_stale_runner_scripts()` method
   - Periodic cleanup in main loop (every 5 minutes)
   - Cleanup on bot process stop and manager shutdown

## Deployment

### 1. Update Configuration

Add to your `.env` file:

```bash
# Recommended for production
BOT_RUNNER_DIR=/srv/blitz-test-server/runtime/bot_runners
BLITZ_PYTHON=/usr/bin/python3
```

### 2. Create Runtime Directory

```bash
sudo mkdir -p /srv/blitz-test-server/runtime/bot_runners
sudo chown blitzbot:blitzbot /srv/blitz-test-server/runtime/bot_runners
sudo chmod 770 /srv/blitz-test-server/runtime/bot_runners
```

### 3. Restart Bot Manager

```bash
sudo systemctl restart blitz-bot-manager
```

### 4. Verify Fix

Use the provided verification script:

```bash
./scripts/verify_bot_manager_fix.sh
```

Or check logs manually:

```bash
journalctl -u blitz-bot-manager -f
```

Look for:
- ✅ `Bot runner directory: /srv/blitz-test-server/runtime/bot_runners`
- ✅ `Python executable: /usr/bin/python3`
- ✅ No more "Permission denied: '/tmp/bot_runner_*.py'" errors

## Testing Results

The fix has been tested to verify:

- ✅ Scripts execute successfully via Python interpreter without execute permissions
- ✅ Permission denied errors eliminated (verified by simulating noexec mount)
- ✅ Configurable directories with proper fallback handling
- ✅ Environment variable configuration works correctly
- ✅ Script cleanup logic is functional and safe

## Backward Compatibility

- **Fully backward compatible**: No changes to existing functionality or API
- **Safe fallbacks**: If configured directory is not accessible, falls back to `./runtime/bot_runners`
- **Default behavior**: Without configuration, uses secure project-local paths instead of `/tmp`

## Files Modified

- `Blitz_app/bot_manager.py` - Main implementation
- `.env.example` - Documentation of new environment variables
- `scripts/verify_bot_manager_fix.sh` - Deployment verification script (new)

## Future Enhancements

- Consider adding a scheduled job to clean up old runner scripts
- Add metrics for bot manager performance and errors
- Consider using systemd user sessions for even better isolation