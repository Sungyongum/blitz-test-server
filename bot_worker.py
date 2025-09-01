#!/usr/bin/env python3
# bot_worker.py - Individual bot process for a single user

import os
import sys
import time
import logging
import signal
import json
from datetime import datetime, timedelta

# Add parent directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Blitz_app.single_file_app import app
# Import models from single_file_app since they're integrated there
import Blitz_app.single_file_app as app_module
from Blitz_app.single_file_app import BotCommand, BotStatus, OrderPersistence, BotCommandService
from Blitz_app.bot import run_bot
from threading import Event

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [BotWorker-%(process)d] %(message)s',
    handlers=[
        logging.FileHandler("bot_worker.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class BotWorker:
    """Individual bot worker process for a single user"""
    
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.app = app  # Use the app from single_file_app
        self.stop_event = Event()
        self.bot_thread = None
        self.current_config = None
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down bot worker for user {self.user_id}")
        self.shutdown()
        
    def _update_status(self, status: str, bot_data: dict = None, error_message: str = None):
        """Update bot status in database"""
        with self.app.app_context():
            try:
                BotCommandService.update_bot_status(
                    self.user_id, 
                    status, 
                    pid=os.getpid(),
                    bot_data=bot_data,
                    error_message=error_message
                )
            except Exception as e:
                logger.error(f"Failed to update status to {status}: {e}")
    
    def _heartbeat(self, bot_data: dict = None):
        """Send heartbeat to indicate bot is alive"""
        with self.app.app_context():
            try:
                BotCommandService.heartbeat(self.user_id, bot_data)
            except Exception as e:
                logger.error(f"Failed to send heartbeat: {e}")
    
    def _get_user_config(self):
        """Get user configuration from database"""
        with self.app.app_context():
            try:
                User = app_module.User  # Get User from single_file_app
                user = User.query.get(self.user_id)
                if not user:
                    raise ValueError(f"User {self.user_id} not found")
                    
                return {
                    'telegram_token': user.telegram_token,
                    'telegram_chat_id': user.telegram_chat_id,
                    'api_key': user.api_key,
                    'api_secret': user.api_secret,
                    'symbol': user.symbol,
                    'side': user.side,
                    'take_profit': user.take_profit,
                    'stop_loss': user.stop_loss,
                    'repeat': user.repeat,
                    'leverage': user.leverage,
                    'rounds': user.rounds,
                    'grids': user.grids,
                }
            except Exception as e:
                logger.error(f"Failed to get user config: {e}")
                raise
    
    def _execute_start_command(self, command_data: dict):
        """Execute start bot command"""
        try:
            # Stop any existing bot
            if self.bot_thread and not self.stop_event.is_set():
                logger.info("Stopping existing bot before starting new one")
                self.stop_event.set()
                self.bot_thread.join(timeout=10)
            
            # Reset stop event for new bot
            self.stop_event.clear()
            
            # Get user config
            user_config = command_data.get('user_config', {})
            if not user_config:
                user_config = self._get_user_config()
            
            # Add grids from command data if available
            if 'grids' in command_data:
                user_config['grids'] = command_data['grids']
            
            self.current_config = user_config
            
            # Update status to starting
            self._update_status('starting')
            
            # Start bot in separate thread using existing bot logic
            import threading
            from Blitz_app.bot import run_bot
            self.bot_thread = threading.Thread(
                target=run_bot,
                args=(user_config, self.stop_event, self.user_id),
                daemon=False
            )
            self.bot_thread.start()
            
            # Update status to running
            self._update_status('running', {'config': user_config})
            logger.info(f"Started bot for user {self.user_id}")
            
        except Exception as e:
            logger.error(f"Failed to start bot: {e}")
            self._update_status('error', error_message=str(e))
            raise
    
    def _execute_stop_command(self):
        """Execute stop bot command"""
        try:
            if self.bot_thread and not self.stop_event.is_set():
                logger.info(f"Stopping bot for user {self.user_id}")
                self.stop_event.set()
                self.bot_thread.join(timeout=30)
                self._update_status('stopped')
            else:
                logger.info(f"Bot for user {self.user_id} was not running")
                self._update_status('stopped')
                
        except Exception as e:
            logger.error(f"Failed to stop bot: {e}")
            self._update_status('error', error_message=str(e))
            raise
    
    def _execute_exit_and_stop_command(self):
        """Execute exit and stop command"""
        try:
            # First stop the bot
            self._execute_stop_command()
            
            # Then liquidate position using the trading logic
            # This would need to be implemented similar to the web app's exit_and_stop
            # For now, just log and mark as completed
            logger.info(f"Exit and stop command executed for user {self.user_id}")
            
        except Exception as e:
            logger.error(f"Failed to execute exit and stop: {e}")
            self._update_status('error', error_message=str(e))
            raise
    
    def process_commands(self):
        """Process pending commands for this user"""
        with self.app.app_context():
            try:
                commands = BotCommandService.get_pending_commands(self.user_id, limit=5)
                
                for command in commands:
                    logger.info(f"Processing command {command.id}: {command.command_type}")
                    
                    # Mark as processing
                    if not BotCommandService.mark_command_processing(command.id):
                        continue
                    
                    try:
                        # Execute command based on type
                        if command.command_type == 'start':
                            self._execute_start_command(command.command_data or {})
                        elif command.command_type == 'stop':
                            self._execute_stop_command()
                        elif command.command_type == 'exit_and_stop':
                            self._execute_exit_and_stop_command()
                        else:
                            logger.warning(f"Unknown command type: {command.command_type}")
                            
                        # Mark as completed
                        BotCommandService.mark_command_completed(command.id)
                        
                    except Exception as e:
                        logger.error(f"Failed to execute command {command.id}: {e}")
                        BotCommandService.mark_command_completed(command.id, str(e))
                        
            except Exception as e:
                logger.error(f"Failed to process commands: {e}")
    
    def run(self):
        """Main bot worker loop"""
        logger.info(f"Starting bot worker for user {self.user_id}")
        
        # Initial status update
        self._update_status('stopped')
        
        try:
            while not self.stop_event.is_set():
                # Process pending commands
                self.process_commands()
                
                # Send heartbeat if bot is running
                if self.bot_thread and self.bot_thread.is_alive():
                    self._heartbeat({'thread_alive': True})
                else:
                    # Check if thread died unexpectedly
                    if self.bot_thread and not self.bot_thread.is_alive():
                        logger.warning(f"Bot thread for user {self.user_id} died unexpectedly")
                        self._update_status('error', error_message="Bot thread died unexpectedly")
                        self.bot_thread = None
                
                # Sleep before next iteration
                time.sleep(5)
                
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        except Exception as e:
            logger.error(f"Unexpected error in bot worker: {e}")
            self._update_status('error', error_message=str(e))
        finally:
            self.shutdown()
    
    def shutdown(self):
        """Shutdown the bot worker"""
        logger.info(f"Shutting down bot worker for user {self.user_id}")
        
        # Stop the bot if running
        if self.bot_thread and not self.stop_event.is_set():
            self.stop_event.set()
            self.bot_thread.join(timeout=30)
        
        # Update final status
        self._update_status('stopped')
        
        # Exit
        sys.exit(0)


def main():
    """Main entry point"""
    if len(sys.argv) != 2:
        print("Usage: python bot_worker.py <user_id>")
        sys.exit(1)
    
    try:
        user_id = int(sys.argv[1])
    except ValueError:
        print("Error: user_id must be an integer")
        sys.exit(1)
    
    # Create and run bot worker
    worker = BotWorker(user_id)
    worker.run()


if __name__ == '__main__':
    main()