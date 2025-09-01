# Blitz_app/services/bot_command_service.py

from datetime import datetime, timedelta
from ..extensions import db
from ..models.bot_command import BotCommand, BotStatus, OrderPersistence
from ..models import User
import logging

logger = logging.getLogger(__name__)


class BotCommandService:
    """Service for managing bot commands via database"""
    
    @staticmethod
    def queue_command(user_id: int, command_type: str, command_data: dict = None):
        """Queue a bot command for execution"""
        try:
            # Cancel any pending commands of the same type for this user
            BotCommand.query.filter_by(
                user_id=user_id, 
                command_type=command_type, 
                status='pending'
            ).update({'status': 'cancelled'})
            
            # Create new command
            command = BotCommand(
                user_id=user_id,
                command_type=command_type,
                command_data=command_data or {}
            )
            db.session.add(command)
            db.session.commit()
            logger.info(f"Queued {command_type} command for user {user_id}")
            return command
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to queue command {command_type} for user {user_id}: {e}")
            raise
    
    @staticmethod
    def get_pending_commands(user_id: int = None, limit: int = 10):
        """Get pending commands, optionally filtered by user"""
        query = BotCommand.query.filter_by(status='pending')
        if user_id:
            query = query.filter_by(user_id=user_id)
        return query.order_by(BotCommand.created_at).limit(limit).all()
    
    @staticmethod
    def mark_command_processing(command_id: int):
        """Mark a command as being processed"""
        try:
            command = BotCommand.query.get(command_id)
            if command and command.status == 'pending':
                command.status = 'processing'
                command.processed_at = datetime.utcnow()
                db.session.commit()
                return True
            return False
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to mark command {command_id} as processing: {e}")
            return False
    
    @staticmethod
    def mark_command_completed(command_id: int, error_message: str = None):
        """Mark a command as completed or failed"""
        try:
            command = BotCommand.query.get(command_id)
            if command:
                command.status = 'failed' if error_message else 'completed'
                command.error_message = error_message
                if not command.processed_at:
                    command.processed_at = datetime.utcnow()
                db.session.commit()
                return True
            return False
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to mark command {command_id} as completed: {e}")
            return False
    
    @staticmethod
    def update_bot_status(user_id: int, status: str, pid: int = None, bot_data: dict = None, error_message: str = None):
        """Update bot status for a user"""
        try:
            bot_status = BotStatus.query.filter_by(user_id=user_id).first()
            if not bot_status:
                bot_status = BotStatus(user_id=user_id)
                db.session.add(bot_status)
            
            bot_status.status = status
            bot_status.last_heartbeat = datetime.utcnow()
            bot_status.updated_at = datetime.utcnow()
            
            if pid is not None:
                bot_status.pid = pid
            if bot_data is not None:
                bot_status.bot_data = bot_data
            if error_message is not None:
                bot_status.last_error = error_message
                
            db.session.commit()
            return bot_status
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to update bot status for user {user_id}: {e}")
            raise
    
    @staticmethod
    def get_bot_status(user_id: int):
        """Get current bot status for a user"""
        return BotStatus.query.filter_by(user_id=user_id).first()
    
    @staticmethod
    def get_all_bot_statuses():
        """Get all bot statuses"""
        return BotStatus.query.all()
    
    @staticmethod
    def heartbeat(user_id: int, bot_data: dict = None):
        """Update bot heartbeat"""
        try:
            bot_status = BotStatus.query.filter_by(user_id=user_id).first()
            if bot_status:
                bot_status.last_heartbeat = datetime.utcnow()
                if bot_data:
                    bot_status.bot_data = bot_data
                db.session.commit()
                return True
            return False
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to update heartbeat for user {user_id}: {e}")
            return False
    
    @staticmethod
    def cleanup_old_commands(days_old: int = 7):
        """Clean up old completed/failed commands"""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days_old)
            old_commands = BotCommand.query.filter(
                BotCommand.created_at < cutoff_date,
                BotCommand.status.in_(['completed', 'failed', 'cancelled'])
            ).all()
            
            for command in old_commands:
                db.session.delete(command)
            
            db.session.commit()
            logger.info(f"Cleaned up {len(old_commands)} old commands")
            return len(old_commands)
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to cleanup old commands: {e}")
            return 0