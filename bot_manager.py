#!/usr/bin/env python3
# bot_manager.py - Bot manager process that supervises individual user bots

import os
import sys
import time
import logging
import signal
import subprocess
import psutil
from datetime import datetime, timedelta
from threading import Thread, Event

# Add parent directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Blitz_app import create_app
from Blitz_app.extensions import db
from Blitz_app.models import User
from Blitz_app.models.bot_command import BotCommand, BotStatus, OrderPersistence
from Blitz_app.services.bot_command_service import BotCommandService

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [BotManager] %(message)s',
    handlers=[
        logging.FileHandler("bot_manager.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class BotManager:
    """Manager for supervising individual user bot processes"""
    
    def __init__(self):
        self.app = create_app()
        self.stop_event = Event()
        self.bot_processes = {}  # user_id -> subprocess.Popen
        self.monitor_thread = None
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down bot manager")
        self.shutdown()
        
    def _get_active_users(self):
        """Get list of users that should have active bots"""
        with self.app.app_context():
            try:
                # Get users with pending start commands or running bots
                users_with_commands = db.session.query(BotCommand.user_id).filter(
                    BotCommand.status == 'pending',
                    BotCommand.command_type == 'start'
                ).distinct().all()
                
                users_with_running_bots = db.session.query(BotStatus.user_id).filter(
                    BotStatus.status.in_(['running', 'starting'])
                ).distinct().all()
                
                active_user_ids = set()
                active_user_ids.update([u[0] for u in users_with_commands])
                active_user_ids.update([u[0] for u in users_with_running_bots])
                
                return list(active_user_ids)
                
            except Exception as e:
                logger.error(f"Failed to get active users: {e}")
                return []
    
    def _start_bot_process(self, user_id: int):
        """Start a bot process for a user"""
        try:
            if user_id in self.bot_processes:
                # Check if process is still alive
                process = self.bot_processes[user_id]
                if process.poll() is None:  # Process is still running
                    logger.info(f"Bot process for user {user_id} is already running")
                    return process
                else:
                    # Process died, remove it
                    del self.bot_processes[user_id]
            
            # Start new bot process
            python_path = sys.executable
            bot_worker_path = os.path.join(os.path.dirname(__file__), 'bot_worker.py')
            
            logger.info(f"Starting bot process for user {user_id}")
            process = subprocess.Popen(
                [python_path, bot_worker_path, str(user_id)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid  # Create new process group
            )
            
            self.bot_processes[user_id] = process
            logger.info(f"Started bot process for user {user_id} with PID {process.pid}")
            
            return process
            
        except Exception as e:
            logger.error(f"Failed to start bot process for user {user_id}: {e}")
            return None
    
    def _stop_bot_process(self, user_id: int):
        """Stop a bot process for a user"""
        try:
            if user_id not in self.bot_processes:
                logger.info(f"No bot process found for user {user_id}")
                return
                
            process = self.bot_processes[user_id]
            
            if process.poll() is not None:  # Process already terminated
                del self.bot_processes[user_id]
                logger.info(f"Bot process for user {user_id} was already terminated")
                return
            
            logger.info(f"Stopping bot process for user {user_id} (PID {process.pid})")
            
            # Send SIGTERM to the process group
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass  # Process already died
            
            # Wait for graceful shutdown
            try:
                process.wait(timeout=30)
                logger.info(f"Bot process for user {user_id} terminated gracefully")
            except subprocess.TimeoutExpired:
                # Force kill if it doesn't shut down gracefully
                logger.warning(f"Force killing bot process for user {user_id}")
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    process.wait(timeout=10)
                except ProcessLookupError:
                    pass  # Process already died
            
            del self.bot_processes[user_id]
            
        except Exception as e:
            logger.error(f"Failed to stop bot process for user {user_id}: {e}")
    
    def _check_bot_health(self, user_id: int):
        """Check if a bot process is healthy"""
        with self.app.app_context():
            try:
                bot_status = BotCommandService.get_bot_status(user_id)
                if not bot_status:
                    return False
                
                # Check if heartbeat is recent (within last 2 minutes)
                if bot_status.last_heartbeat:
                    time_since_heartbeat = datetime.utcnow() - bot_status.last_heartbeat
                    if time_since_heartbeat > timedelta(minutes=2):
                        logger.warning(f"Bot for user {user_id} has stale heartbeat: {time_since_heartbeat}")
                        return False
                
                # Check if process is actually running
                if user_id in self.bot_processes:
                    process = self.bot_processes[user_id]
                    if process.poll() is not None:  # Process died
                        logger.warning(f"Bot process for user {user_id} died unexpectedly")
                        del self.bot_processes[user_id]
                        return False
                
                return True
                
            except Exception as e:
                logger.error(f"Failed to check bot health for user {user_id}: {e}")
                return False
    
    def _monitor_bots(self):
        """Monitor bot processes and restart if needed"""
        while not self.stop_event.is_set():
            try:
                with self.app.app_context():
                    # Get list of users that should have active bots
                    active_users = self._get_active_users()
                    
                    # Check each active user's bot
                    for user_id in active_users:
                        if not self._check_bot_health(user_id):
                            logger.info(f"Restarting unhealthy bot for user {user_id}")
                            self._stop_bot_process(user_id)
                            self._start_bot_process(user_id)
                    
                    # Get users with stop commands
                    stop_commands = BotCommand.query.filter(
                        BotCommand.status == 'pending',
                        BotCommand.command_type.in_(['stop', 'exit_and_stop'])
                    ).all()
                    
                    for command in stop_commands:
                        user_id = command.user_id
                        if user_id in self.bot_processes:
                            logger.info(f"Stopping bot for user {user_id} due to stop command")
                            self._stop_bot_process(user_id)
                        
                        # Mark command as completed
                        BotCommandService.mark_command_completed(command.id)
                    
                    # Clean up dead processes
                    dead_processes = []
                    for user_id, process in self.bot_processes.items():
                        if process.poll() is not None:
                            dead_processes.append(user_id)
                    
                    for user_id in dead_processes:
                        logger.info(f"Cleaning up dead process for user {user_id}")
                        del self.bot_processes[user_id]
                        # Update bot status to stopped
                        BotCommandService.update_bot_status(user_id, 'stopped')
                
            except Exception as e:
                logger.error(f"Error in bot monitoring: {e}")
            
            # Sleep before next check
            time.sleep(10)
    
    def _cleanup_old_data(self):
        """Cleanup old commands and update stale statuses"""
        while not self.stop_event.is_set():
            try:
                with self.app.app_context():
                    # Cleanup old commands (older than 7 days)
                    BotCommandService.cleanup_old_commands(days_old=7)
                    
                    # Mark bots with very old heartbeats as stopped
                    stale_cutoff = datetime.utcnow() - timedelta(hours=1)
                    stale_bots = BotStatus.query.filter(
                        BotStatus.status.in_(['running', 'starting']),
                        BotStatus.last_heartbeat < stale_cutoff
                    ).all()
                    
                    for bot_status in stale_bots:
                        logger.warning(f"Marking bot {bot_status.user_id} as stopped due to stale heartbeat")
                        BotCommandService.update_bot_status(
                            bot_status.user_id, 
                            'stopped',
                            error_message="Stale heartbeat - marked as stopped by manager"
                        )
                
            except Exception as e:
                logger.error(f"Error in cleanup: {e}")
            
            # Sleep for 30 minutes before next cleanup
            for _ in range(180):  # 30 minutes = 180 * 10 seconds
                if self.stop_event.is_set():
                    break
                time.sleep(10)
    
    def run(self):
        """Main bot manager loop"""
        logger.info("Starting bot manager")
        
        try:
            # Start monitor thread
            self.monitor_thread = Thread(target=self._monitor_bots, daemon=True)
            self.monitor_thread.start()
            
            # Start cleanup thread
            cleanup_thread = Thread(target=self._cleanup_old_data, daemon=True)
            cleanup_thread.start()
            
            # Main loop - just keep the manager alive
            while not self.stop_event.is_set():
                time.sleep(60)  # Check every minute
                logger.debug("Bot manager heartbeat")
                
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        except Exception as e:
            logger.error(f"Unexpected error in bot manager: {e}")
        finally:
            self.shutdown()
    
    def shutdown(self):
        """Shutdown the bot manager"""
        logger.info("Shutting down bot manager")
        
        # Signal shutdown
        self.stop_event.set()
        
        # Stop all bot processes
        for user_id in list(self.bot_processes.keys()):
            self._stop_bot_process(user_id)
        
        # Wait for monitor thread to finish
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=10)
        
        logger.info("Bot manager shutdown complete")
        sys.exit(0)


def main():
    """Main entry point"""
    manager = BotManager()
    manager.run()


if __name__ == '__main__':
    main()