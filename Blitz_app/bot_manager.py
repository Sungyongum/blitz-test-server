# Blitz_app/bot_manager.py

import os
import sys
import time
import json
import logging
import signal
import subprocess
from datetime import datetime, timedelta
from threading import Thread, Event
from typing import Dict, Optional
import psutil

from .extensions import db
from .models import User, UserBot, BotCommand, BotEvent
from .telegram import send_telegram

logger = logging.getLogger(__name__)

class BotManager:
    """
    Bot Manager for supervising per-user bot processes.
    
    Responsibilities:
    - Watch users table for active users
    - Ensure exactly one isolated bot process per user
    - Maintain heartbeat/pid tracking in user_bots table
    - Auto-restart with backoff on crash
    - Health checks and anomaly detection
    - Telegram alerts with emojis and user identification
    - Structured JSON logging with remediation suggestions
    """
    
    def __init__(self, app):
        self.app = app
        self.stop_event = Event()
        self.managed_bots: Dict[int, dict] = {}  # user_id -> bot_info
        self.restart_backoff = {}  # user_id -> next_restart_time
        self.health_check_interval = 30  # seconds
        self.max_restart_attempts = 5
        self.restart_backoff_base = 60  # base backoff in seconds
        
        # Admin telegram for alerts
        self.admin_telegram_token = None
        self.admin_chat_id = None
        self._load_admin_config()
        
    def _load_admin_config(self):
        """Load admin telegram config for alerts"""
        try:
            with self.app.app_context():
                admin = User.query.filter_by(email='admin@admin.com').first()
                if admin and admin.telegram_token and admin.telegram_chat_id:
                    self.admin_telegram_token = admin.telegram_token
                    self.admin_chat_id = admin.telegram_chat_id
        except Exception as e:
            logger.warning(f"Could not load admin config: {e}")
    
    def _log_structured(self, level: str, event_type: str, user_id: int, message: str, 
                       remediation: Optional[str] = None, **kwargs):
        """Log structured JSON with remediation suggestions"""
        log_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': level,
            'event_type': event_type,
            'user_id': user_id,
            'message': message,
            'remediation': remediation,
            **kwargs
        }
        
        log_level = getattr(logging, level.upper(), logging.INFO)
        logger.log(log_level, json.dumps(log_data, ensure_ascii=False))
    
    def _send_admin_alert(self, message: str, user_id: Optional[int] = None):
        """Send Telegram alert to admin with emojis and user identification"""
        if not self.admin_telegram_token or not self.admin_chat_id:
            return
        
        try:
            # Add user identification if provided
            if user_id:
                with self.app.app_context():
                    user = User.query.get(user_id)
                    if user:
                        user_info = f" (User: {user.email} / ID: {user_id})"
                        message += user_info
            
            send_telegram(self.admin_telegram_token, self.admin_chat_id, message)
        except Exception as e:
            logger.error(f"Failed to send admin alert: {e}")
    
    def _get_bot_process_info(self, user_id: int) -> Optional[dict]:
        """Get bot process information"""
        try:
            with self.app.app_context():
                bot_info = UserBot.query.get(user_id)
                if not bot_info or not bot_info.pid:
                    return None
                
                # Check if process exists and is our bot
                try:
                    proc = psutil.Process(bot_info.pid)
                    if proc.is_running():
                        return {
                            'pid': bot_info.pid,
                            'status': bot_info.status,
                            'last_heartbeat': bot_info.last_heartbeat_at,
                            'process': proc
                        }
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    # Process doesn't exist, clean up DB
                    bot_info.pid = None
                    bot_info.status = 'stopped'
                    db.session.commit()
                    
        except Exception as e:
            logger.error(f"Error getting bot process info for user {user_id}: {e}")
        
        return None
    
    def _start_bot_process(self, user_id: int) -> bool:
        """Start a new bot process for the user"""
        try:
            with self.app.app_context():
                user = User.query.get(user_id)
                if not user:
                    logger.error(f"User {user_id} not found")
                    return False
                
                # Create bot startup script
                script_path = f"/tmp/bot_runner_{user_id}.py"
                with open(script_path, 'w') as f:
                    f.write(f"""
import sys
import os
sys.path.insert(0, '{os.getcwd()}')

from Blitz_app import create_app
from Blitz_app.bot import run_bot
from threading import Event

app = create_app()
with app.app_context():
    from Blitz_app.models import User
    user = User.query.get({user_id})
    if user:
        config = user.to_dict()
        config['api_key'] = user.api_key
        config['api_secret'] = user.api_secret
        config['telegram_token'] = user.telegram_token
        config['telegram_chat_id'] = user.telegram_chat_id
        
        stop_event = Event()
        try:
            run_bot(config, stop_event, {user_id}, user.exchange or 'bybit')
        except Exception as e:
            print(f"Bot error: {{e}}")
            sys.exit(1)
    else:
        print("User not found")
        sys.exit(1)
""")
                
                # Start the process
                proc = subprocess.Popen([
                    sys.executable, script_path
                ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                
                # Update database
                bot_info = UserBot.query.get(user_id)
                if not bot_info:
                    bot_info = UserBot(user_id=user_id)
                    db.session.add(bot_info)
                
                bot_info.pid = proc.pid
                bot_info.status = 'running'
                bot_info.last_heartbeat_at = datetime.utcnow()
                bot_info.restart_count += 1
                db.session.commit()
                
                # Log event
                event = BotEvent(
                    user_id=user_id,
                    type='bot_started',
                    payload=json.dumps({'pid': proc.pid, 'restart_count': bot_info.restart_count})
                )
                db.session.add(event)
                db.session.commit()
                
                self._log_structured(
                    'info', 'bot_started', user_id,
                    f"Bot process started with PID {proc.pid}",
                    f"Monitor process health via PID {proc.pid}"
                )
                
                self._send_admin_alert(f"🚀 Bot started for user {user_id} (PID: {proc.pid})", user_id)
                
                return True
                
        except Exception as e:
            self._log_structured(
                'error', 'bot_start_failed', user_id,
                f"Failed to start bot process: {e}",
                "Check user configuration and system resources"
            )
            self._send_admin_alert(f"❌ Failed to start bot for user {user_id}: {e}", user_id)
            return False
    
    def _stop_bot_process(self, user_id: int, force: bool = False) -> bool:
        """Stop bot process for the user"""
        try:
            bot_info = self._get_bot_process_info(user_id)
            if not bot_info:
                return True  # Already stopped
            
            proc = bot_info['process']
            
            if not force:
                # Try graceful shutdown first
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    force = True
            
            if force:
                proc.kill()
                proc.wait()
            
            # Update database
            with self.app.app_context():
                bot_record = UserBot.query.get(user_id)
                if bot_record:
                    bot_record.pid = None
                    bot_record.status = 'stopped'
                    db.session.commit()
                
                # Log event
                event = BotEvent(
                    user_id=user_id,
                    type='bot_stopped',
                    payload=json.dumps({'forced': force})
                )
                db.session.add(event)
                db.session.commit()
            
            self._log_structured(
                'info', 'bot_stopped', user_id,
                f"Bot process stopped (forced: {force})"
            )
            
            return True
            
        except Exception as e:
            self._log_structured(
                'error', 'bot_stop_failed', user_id,
                f"Failed to stop bot process: {e}",
                "Manual process termination may be required"
            )
            return False
    
    def _check_bot_health(self, user_id: int) -> bool:
        """Check bot health and take action if needed"""
        try:
            bot_info = self._get_bot_process_info(user_id)
            if not bot_info:
                return False  # Bot not running
            
            # Check heartbeat age
            if bot_info['last_heartbeat']:
                heartbeat_age = datetime.utcnow() - bot_info['last_heartbeat']
                if heartbeat_age > timedelta(minutes=5):  # 5 minutes without heartbeat
                    self._log_structured(
                        'warning', 'bot_heartbeat_stale', user_id,
                        f"Bot heartbeat is {heartbeat_age.total_seconds():.0f}s old",
                        "Consider restarting the bot process"
                    )
                    self._send_admin_alert(f"💔 Bot heartbeat stale for user {user_id}", user_id)
                    return False
            
            # Check if process is responsive (could add more checks here)
            proc = bot_info['process']
            if proc.status() == psutil.STATUS_ZOMBIE:
                self._log_structured(
                    'error', 'bot_process_zombie', user_id,
                    "Bot process is in zombie state",
                    "Restart bot process immediately"
                )
                self._send_admin_alert(f"🧟 Bot process zombie for user {user_id}", user_id)
                return False
            
            return True
            
        except Exception as e:
            self._log_structured(
                'error', 'health_check_failed', user_id,
                f"Health check failed: {e}",
                "Manual intervention may be required"
            )
            return False
    
    def _should_restart_bot(self, user_id: int) -> bool:
        """Check if bot should be restarted (respecting backoff)"""
        if user_id in self.restart_backoff:
            if time.time() < self.restart_backoff[user_id]:
                return False
        
        try:
            with self.app.app_context():
                bot_info = UserBot.query.get(user_id)
                if bot_info and bot_info.restart_count >= self.max_restart_attempts:
                    self._log_structured(
                        'error', 'bot_max_restarts', user_id,
                        f"Bot exceeded max restart attempts ({self.max_restart_attempts})",
                        "Manual intervention required - check user configuration"
                    )
                    self._send_admin_alert(f"🚨 Bot exceeded max restarts for user {user_id}", user_id)
                    return False
        except Exception:
            pass
        
        return True
    
    def _set_restart_backoff(self, user_id: int):
        """Set exponential backoff for bot restart"""
        try:
            with self.app.app_context():
                bot_info = UserBot.query.get(user_id)
                restart_count = bot_info.restart_count if bot_info else 0
                
            backoff_time = min(self.restart_backoff_base * (2 ** restart_count), 300)  # max 5 minutes
            self.restart_backoff[user_id] = time.time() + backoff_time
            
            self._log_structured(
                'info', 'restart_backoff_set', user_id,
                f"Restart backoff set to {backoff_time}s"
            )
        except Exception as e:
            logger.error(f"Error setting restart backoff for user {user_id}: {e}")
    
    def _manage_user_bot(self, user_id: int, should_run: bool):
        """Manage individual user bot (start/stop/restart as needed)"""
        bot_info = self._get_bot_process_info(user_id)
        is_running = bot_info is not None
        
        if should_run and not is_running:
            # Should be running but isn't - start it
            if self._should_restart_bot(user_id):
                if self._start_bot_process(user_id):
                    self.restart_backoff.pop(user_id, None)  # Clear backoff on success
                else:
                    self._set_restart_backoff(user_id)
                    
        elif should_run and is_running:
            # Should be running and is - check health
            if not self._check_bot_health(user_id):
                # Health check failed, restart
                self._stop_bot_process(user_id)
                if self._should_restart_bot(user_id):
                    if self._start_bot_process(user_id):
                        self.restart_backoff.pop(user_id, None)
                    else:
                        self._set_restart_backoff(user_id)
                        
        elif not should_run and is_running:
            # Shouldn't be running but is - stop it
            self._stop_bot_process(user_id)
    
    def _get_active_users(self) -> list:
        """Get list of users who should have bots running"""
        try:
            with self.app.app_context():
                # Users with valid config who want bots running
                users = User.query.filter(
                    User.api_key.isnot(None),
                    User.api_secret.isnot(None),
                    User.telegram_token.isnot(None),
                    User.repeat == True  # User wants bot to run
                ).all()
                return [user.id for user in users]
        except Exception as e:
            logger.error(f"Error getting active users: {e}")
            return []
    
    def run(self):
        """Main bot manager loop"""
        logger.info("🎯 Bot Manager starting up")
        self._send_admin_alert("🎯 Bot Manager started")
        
        while not self.stop_event.is_set():
            try:
                # Get users who should have bots running
                active_users = self._get_active_users()
                
                # Get currently managed bots
                current_bots = set(self.managed_bots.keys())
                
                # Determine which bots to start/stop
                should_run = set(active_users)
                
                # Stop bots that shouldn't be running
                for user_id in current_bots - should_run:
                    self._manage_user_bot(user_id, False)
                    self.managed_bots.pop(user_id, None)
                
                # Start/check bots that should be running
                for user_id in should_run:
                    self._manage_user_bot(user_id, True)
                    self.managed_bots[user_id] = {'last_checked': time.time()}
                
                # Wait before next check
                time.sleep(self.health_check_interval)
                
            except Exception as e:
                logger.error(f"Error in bot manager main loop: {e}")
                self._send_admin_alert(f"❌ Bot Manager error: {e}")
                time.sleep(30)  # Wait longer on error
        
        logger.info("🛑 Bot Manager shutting down")
        self._send_admin_alert("🛑 Bot Manager shutting down")
        
        # Stop all managed bots
        for user_id in list(self.managed_bots.keys()):
            self._stop_bot_process(user_id)
    
    def stop(self):
        """Stop the bot manager"""
        self.stop_event.set()


def run_bot_manager(app):
    """Entry point for bot manager process"""
    manager = BotManager(app)
    
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, stopping bot manager")
        manager.stop()
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        manager.run()
    except KeyboardInterrupt:
        logger.info("Bot manager interrupted")
    finally:
        manager.stop()


if __name__ == '__main__':
    # Allow running bot manager standalone
    from Blitz_app import create_app
    app = create_app()
    run_bot_manager(app)