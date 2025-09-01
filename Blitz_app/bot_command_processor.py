# Blitz_app/bot_command_processor.py

import json
import time
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy import text

from .extensions import db
from .models import BotCommand, BotEvent, UserBot

logger = logging.getLogger(__name__)

class BotCommandProcessor:
    """
    Process bot commands from the database with SQLite concurrency handling.
    
    Uses command claiming algorithm:
    - BEGIN IMMEDIATE transaction
    - SELECT oldest queued command for user
    - UPDATE status='picked' where status='queued'
    - COMMIT
    """
    
    def __init__(self, user_id: int, bot_instance_id: str):
        self.user_id = user_id
        self.bot_instance_id = bot_instance_id
        
    def claim_next_command(self) -> Optional[BotCommand]:
        """Claim the next available command for this user with proper concurrency"""
        max_retries = 3
        retry_delay = 0.1
        
        for attempt in range(max_retries):
            try:
                # Use raw SQL for precise control over transaction
                result = db.session.execute(text("""
                    BEGIN IMMEDIATE;
                    
                    SELECT id FROM bot_commands 
                    WHERE user_id = :user_id AND status = 'queued'
                    ORDER BY created_at ASC 
                    LIMIT 1;
                """), {'user_id': self.user_id})
                
                row = result.fetchone()
                if not row:
                    db.session.execute(text("COMMIT;"))
                    return None
                
                command_id = row[0]
                
                # Try to claim it
                update_result = db.session.execute(text("""
                    UPDATE bot_commands 
                    SET status = 'picked', 
                        picked_at = :now,
                        picked_by = :instance_id
                    WHERE id = :command_id AND status = 'queued';
                """), {
                    'command_id': command_id,
                    'now': datetime.utcnow(),
                    'instance_id': self.bot_instance_id
                })
                
                db.session.execute(text("COMMIT;"))
                
                if update_result.rowcount > 0:
                    # Successfully claimed, fetch the command
                    command = BotCommand.query.get(command_id)
                    return command
                else:
                    # Someone else claimed it, try again
                    continue
                    
            except Exception as e:
                try:
                    db.session.execute(text("ROLLBACK;"))
                except:
                    pass
                
                logger.warning(f"Command claim attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (2 ** attempt))  # Exponential backoff
                else:
                    logger.error(f"Failed to claim command after {max_retries} attempts")
        
        return None
    
    def mark_command_done(self, command: BotCommand, success: bool = True, error_message: str = None):
        """Mark command as completed"""
        try:
            command.status = 'done' if success else 'failed'
            command.done_at = datetime.utcnow()
            if error_message:
                command.error_message = error_message
            db.session.commit()
            
            # Log completion event
            event = BotEvent(
                user_id=self.user_id,
                type='command_completed',
                payload=json.dumps({
                    'command_id': command.id,
                    'command_type': command.type,
                    'success': success,
                    'error_message': error_message
                })
            )
            db.session.add(event)
            db.session.commit()
            
        except Exception as e:
            logger.error(f"Failed to mark command {command.id} as done: {e}")
    
    def update_heartbeat(self):
        """Update bot heartbeat in database"""
        try:
            bot_info = UserBot.query.get(self.user_id)
            if bot_info:
                bot_info.last_heartbeat_at = datetime.utcnow()
                bot_info.status = 'running'
                db.session.commit()
        except Exception as e:
            logger.error(f"Failed to update heartbeat: {e}")
    
    def process_commands(self, bot_context: Dict[str, Any]) -> bool:
        """
        Process available commands for this user.
        
        Args:
            bot_context: Dictionary containing bot state (exchange, symbol, etc.)
            
        Returns:
            bool: True if any commands were processed
        """
        processed = False
        
        while True:
            command = self.claim_next_command()
            if not command:
                break
                
            try:
                logger.info(f"Processing command {command.id}: {command.type}")
                
                success = self._execute_command(command, bot_context)
                self.mark_command_done(command, success)
                processed = True
                
            except Exception as e:
                logger.error(f"Error processing command {command.id}: {e}")
                self.mark_command_done(command, success=False, error_message=str(e))
        
        return processed
    
    def _execute_command(self, command: BotCommand, bot_context: Dict[str, Any]) -> bool:
        """Execute a specific command"""
        payload = command.payload_dict
        
        try:
            if command.type == 'recover_orders':
                return self._cmd_recover_orders(payload, bot_context)
            elif command.type == 'restart_bot':
                return self._cmd_restart_bot(payload, bot_context)
            elif command.type == 'resync_tp':
                return self._cmd_resync_tp(payload, bot_context)
            elif command.type == 'cancel_all':
                return self._cmd_cancel_all(payload, bot_context)
            elif command.type == 'force_close':
                return self._cmd_force_close(payload, bot_context)
            elif command.type == 'reset_plan':
                return self._cmd_reset_plan(payload, bot_context)
            elif command.type == 'unlock':
                return self._cmd_unlock(payload, bot_context)
            elif command.type == 'update_rounds':
                return self._cmd_update_rounds(payload, bot_context)
            elif command.type == 'start_bot':
                return self._cmd_start_bot(payload, bot_context)
            elif command.type == 'stop_bot':
                return self._cmd_stop_bot(payload, bot_context)
            else:
                logger.warning(f"Unknown command type: {command.type}")
                return False
                
        except Exception as e:
            logger.error(f"Command {command.type} execution failed: {e}")
            return False
    
    def _cmd_recover_orders(self, payload: dict, bot_context: dict) -> bool:
        """주문 복구 명령 실행"""
        # This would integrate with existing order recovery logic
        logger.info(f"Recovering orders: {payload}")
        
        # TODO: Implement order recovery logic
        # - Check current position
        # - Recreate missing entry orders
        # - Recreate TP/SL orders
        
        return True
    
    def _cmd_restart_bot(self, payload: dict, bot_context: dict) -> bool:
        """봇 재시작 명령 실행"""
        logger.info("Bot restart requested via command")
        
        # Set a flag in bot context to trigger restart
        bot_context['restart_requested'] = True
        return True
    
    def _cmd_resync_tp(self, payload: dict, bot_context: dict) -> bool:
        """TP 재동기화 명령 실행"""
        logger.info(f"Resyncing TP orders: {payload}")
        
        # TODO: Implement TP resync logic
        # - Cancel existing TP orders
        # - Recalculate TP from current position
        # - Create new TP orders
        
        return True
    
    def _cmd_cancel_all(self, payload: dict, bot_context: dict) -> bool:
        """전체 주문 취소 명령 실행"""
        logger.info(f"Cancelling all orders: {payload}")
        
        try:
            exchange = bot_context.get('exchange')
            symbol = payload.get('symbol') or bot_context.get('symbol')
            
            if exchange and symbol:
                # Cancel all open orders
                orders = exchange.fetch_open_orders(symbol)
                for order in orders:
                    try:
                        exchange.cancel_order(order['id'], symbol)
                        logger.info(f"Cancelled order {order['id']}")
                    except Exception as e:
                        logger.warning(f"Failed to cancel order {order['id']}: {e}")
                
                return True
        except Exception as e:
            logger.error(f"Failed to cancel all orders: {e}")
            
        return False
    
    def _cmd_force_close(self, payload: dict, bot_context: dict) -> bool:
        """포지션 강제 청산 명령 실행"""
        logger.info(f"Force closing position: {payload}")
        
        try:
            exchange = bot_context.get('exchange')
            symbol = payload.get('symbol') or bot_context.get('symbol')
            
            if exchange and symbol:
                # Get current position
                positions = exchange.fetch_positions([symbol])
                for pos in positions:
                    if float(pos.get('contracts', 0)) > 0:
                        # Close position with market order
                        side = 'sell' if pos['side'] == 'long' else 'buy'
                        size = abs(float(pos['contracts']))
                        
                        order = exchange.create_market_order(symbol, side, size, None, {
                            'reduceOnly': True
                        })
                        logger.info(f"Force closed position with order {order['id']}")
                
                return True
        except Exception as e:
            logger.error(f"Failed to force close position: {e}")
            
        return False
    
    def _cmd_reset_plan(self, payload: dict, bot_context: dict) -> bool:
        """계획 초기화 명령 실행"""
        logger.info("Resetting trading plan")
        
        # TODO: Implement plan reset logic
        # - Clear existing order plans
        # - Reset bot state
        # - Cancel pending orders
        
        return True
    
    def _cmd_unlock(self, payload: dict, bot_context: dict) -> bool:
        """잠금 해제 명령 실행"""
        logger.info("Unlocking user")
        
        # TODO: Implement unlock logic
        # - Clear any locks or flags
        # - Reset error states
        
        return True
    
    def _cmd_update_rounds(self, payload: dict, bot_context: dict) -> bool:
        """라운드 업데이트 명령 실행"""
        rounds = payload.get('rounds')
        entry_round = payload.get('entry_round')
        
        logger.info(f"Updating rounds: {rounds}, entry_round: {entry_round}")
        
        # TODO: Implement rounds update logic
        # - Update user configuration
        # - Adjust current trading plan
        
        return True
    
    def _cmd_start_bot(self, payload: dict, bot_context: dict) -> bool:
        """봇 시작 명령 실행"""
        logger.info("Bot start requested via command")
        
        # This would be handled by the bot manager, not the bot itself
        return True
    
    def _cmd_stop_bot(self, payload: dict, bot_context: dict) -> bool:
        """봇 중지 명령 실행"""
        logger.info("Bot stop requested via command")
        
        # Set a flag in bot context to trigger shutdown
        bot_context['stop_requested'] = True
        return True