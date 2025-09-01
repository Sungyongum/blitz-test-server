# Blitz_app/api_routes.py

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime
import hashlib
import time
import json

from .extensions import db
from .models import BotCommand, BotEvent, UserBot, User
from .utils import is_admin

api = Blueprint('api', __name__, url_prefix='/api')

def generate_idempotency_key(user_id: int, command_type: str, payload: dict = None) -> str:
    """Generate idempotency key for commands"""
    data = f"{user_id}:{command_type}:{json.dumps(payload or {}, sort_keys=True)}"
    return hashlib.md5(data.encode()).hexdigest()

def create_bot_command(user_id: int, command_type: str, payload: dict = None) -> dict:
    """Create a bot command with idempotency"""
    try:
        idempotency_key = f"{command_type}_{user_id}_{int(time.time() * 1000)}"
        
        # Check for existing command with same idempotency key
        existing = BotCommand.query.filter_by(idempotency_key=idempotency_key).first()
        if existing:
            return {
                'success': True,
                'command_id': existing.id,
                'status': existing.status,
                'message': 'Command already exists'
            }
        
        # Create new command
        command = BotCommand(
            user_id=user_id,
            type=command_type,
            payload=json.dumps(payload or {}),
            status='queued',
            idempotency_key=idempotency_key
        )
        db.session.add(command)
        db.session.commit()
        
        # Log event
        event = BotEvent(
            user_id=user_id,
            type='command_queued',
            payload=json.dumps({
                'command_id': command.id,
                'command_type': command_type,
                'payload': payload
            })
        )
        db.session.add(event)
        db.session.commit()
        
        return {
            'success': True,
            'command_id': command.id,
            'status': 'queued',
            'message': 'Command queued successfully'
        }
        
    except Exception as e:
        db.session.rollback()
        return {
            'success': False,
            'error': str(e),
            'message': 'Failed to create command'
        }

@api.route('/users/<int:user_id>/commands/recover_orders', methods=['POST'])
@login_required
def recover_orders(user_id):
    """주문 복구 명령"""
    if not is_admin() and current_user.id != user_id:
        return jsonify({'error': 'Forbidden'}), 403
    
    data = request.get_json() or {}
    payload = {
        'symbol': data.get('symbol'),
        'rounds': data.get('rounds'),
        'force': data.get('force', False)
    }
    
    result = create_bot_command(user_id, 'recover_orders', payload)
    return jsonify(result), 200 if result['success'] else 400

@api.route('/users/<int:user_id>/commands/restart_bot', methods=['POST'])
@login_required
def restart_bot(user_id):
    """봇 재시작 명령"""
    if not is_admin() and current_user.id != user_id:
        return jsonify({'error': 'Forbidden'}), 403
    
    result = create_bot_command(user_id, 'restart_bot')
    return jsonify(result), 200 if result['success'] else 400

@api.route('/users/<int:user_id>/commands/resync_tp', methods=['POST'])
@login_required
def resync_tp(user_id):
    """TP 재동기화 명령"""
    if not is_admin() and current_user.id != user_id:
        return jsonify({'error': 'Forbidden'}), 403
    
    data = request.get_json() or {}
    payload = {
        'symbol': data.get('symbol'),
        'recalc_from_position': data.get('recalc_from_position', True)
    }
    
    result = create_bot_command(user_id, 'resync_tp', payload)
    return jsonify(result), 200 if result['success'] else 400

@api.route('/users/<int:user_id>/commands/cancel_all', methods=['POST'])
@login_required
def cancel_all_orders(user_id):
    """전체 주문 취소 명령"""
    if not is_admin() and current_user.id != user_id:
        return jsonify({'error': 'Forbidden'}), 403
    
    data = request.get_json() or {}
    payload = {
        'symbol': data.get('symbol'),
        'force': data.get('force', False)
    }
    
    result = create_bot_command(user_id, 'cancel_all', payload)
    return jsonify(result), 200 if result['success'] else 400

@api.route('/users/<int:user_id>/commands/force_close', methods=['POST'])
@login_required
def force_close_position(user_id):
    """포지션 강제 청산 명령"""
    if not is_admin() and current_user.id != user_id:
        return jsonify({'error': 'Forbidden'}), 403
    
    data = request.get_json() or {}
    payload = {
        'symbol': data.get('symbol'),
        'market_close': data.get('market_close', True)
    }
    
    result = create_bot_command(user_id, 'force_close', payload)
    return jsonify(result), 200 if result['success'] else 400

@api.route('/users/<int:user_id>/commands/reset_plan', methods=['POST'])
@login_required
def reset_plan(user_id):
    """계획 초기화 명령"""
    if not is_admin() and current_user.id != user_id:
        return jsonify({'error': 'Forbidden'}), 403
    
    result = create_bot_command(user_id, 'reset_plan')
    return jsonify(result), 200 if result['success'] else 400

@api.route('/users/<int:user_id>/commands/unlock', methods=['POST'])
@login_required
def unlock_user(user_id):
    """사용자 잠금 해제 명령"""
    if not is_admin():
        return jsonify({'error': 'Admin access required'}), 403
    
    result = create_bot_command(user_id, 'unlock')
    return jsonify(result), 200 if result['success'] else 400

@api.route('/users/<int:user_id>/commands/update_rounds', methods=['POST'])
@login_required
def update_rounds(user_id):
    """진입 라운드/총 N 업데이트 명령"""
    if not is_admin():
        return jsonify({'error': 'Admin access required'}), 403
    
    data = request.get_json() or {}
    payload = {
        'rounds': data.get('rounds'),
        'entry_round': data.get('entry_round')
    }
    
    if not payload['rounds']:
        return jsonify({'error': 'rounds parameter required'}), 400
    
    result = create_bot_command(user_id, 'update_rounds', payload)
    return jsonify(result), 200 if result['success'] else 400

@api.route('/users/<int:user_id>/bot/start', methods=['POST'])
@login_required
def start_user_bot(user_id):
    """사용자 봇 시작"""
    if not is_admin() and current_user.id != user_id:
        return jsonify({'error': 'Forbidden'}), 403
    
    result = create_bot_command(user_id, 'start_bot')
    return jsonify(result), 200 if result['success'] else 400

@api.route('/users/<int:user_id>/bot/stop', methods=['POST'])
@login_required
def stop_user_bot(user_id):
    """사용자 봇 중지"""
    if not is_admin() and current_user.id != user_id:
        return jsonify({'error': 'Forbidden'}), 403
    
    result = create_bot_command(user_id, 'stop_bot')
    return jsonify(result), 200 if result['success'] else 400

@api.route('/users/<int:user_id>/status', methods=['GET'])
@login_required
def get_user_bot_status(user_id):
    """사용자 봇 상태 조회"""
    if not is_admin() and current_user.id != user_id:
        return jsonify({'error': 'Forbidden'}), 403
    
    try:
        # Get bot info
        bot_info = UserBot.query.get(user_id)
        
        # Get recent commands
        recent_commands = BotCommand.query.filter_by(user_id=user_id)\
            .order_by(BotCommand.created_at.desc())\
            .limit(5).all()
        
        # Get recent events
        recent_events = BotEvent.query.filter_by(user_id=user_id)\
            .order_by(BotEvent.created_at.desc())\
            .limit(10).all()
        
        return jsonify({
            'user_id': user_id,
            'bot_status': bot_info.status if bot_info else 'stopped',
            'bot_pid': bot_info.pid if bot_info else None,
            'last_heartbeat': bot_info.last_heartbeat_at.isoformat() if bot_info and bot_info.last_heartbeat_at else None,
            'restart_count': bot_info.restart_count if bot_info else 0,
            'recent_commands': [{
                'id': cmd.id,
                'type': cmd.type,
                'status': cmd.status,
                'created_at': cmd.created_at.isoformat(),
                'error_message': cmd.error_message
            } for cmd in recent_commands],
            'recent_events': [{
                'id': event.id,
                'type': event.type,
                'payload': event.payload_dict,
                'created_at': event.created_at.isoformat()
            } for event in recent_events]
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api.route('/users/<int:user_id>/commands/<int:command_id>/status', methods=['GET'])
@login_required
def get_command_status(user_id, command_id):
    """명령 상태 조회"""
    if not is_admin() and current_user.id != user_id:
        return jsonify({'error': 'Forbidden'}), 403
    
    try:
        command = BotCommand.query.filter_by(id=command_id, user_id=user_id).first()
        if not command:
            return jsonify({'error': 'Command not found'}), 404
        
        return jsonify({
            'command_id': command.id,
            'type': command.type,
            'status': command.status,
            'created_at': command.created_at.isoformat(),
            'picked_at': command.picked_at.isoformat() if command.picked_at else None,
            'done_at': command.done_at.isoformat() if command.done_at else None,
            'picked_by': command.picked_by,
            'error_message': command.error_message,
            'payload': command.payload_dict
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Admin-only endpoints
@api.route('/admin/health', methods=['GET'])
@login_required
def admin_health_check():
    """전체 시스템 헬스 체크"""
    if not is_admin():
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        # Get all user bots
        user_bots = UserBot.query.all()
        
        # Get pending commands count
        pending_commands = BotCommand.query.filter_by(status='queued').count()
        
        # Get recent errors
        recent_errors = BotEvent.query.filter_by(type='error')\
            .order_by(BotEvent.created_at.desc())\
            .limit(10).all()
        
        bot_status = {}
        for bot in user_bots:
            heartbeat_age = None
            if bot.last_heartbeat_at:
                heartbeat_age = (datetime.utcnow() - bot.last_heartbeat_at).total_seconds()
            
            bot_status[bot.user_id] = {
                'status': bot.status,
                'pid': bot.pid,
                'heartbeat_age_seconds': heartbeat_age,
                'restart_count': bot.restart_count,
                'last_error': bot.last_error
            }
        
        return jsonify({
            'total_bots': len(user_bots),
            'running_bots': len([b for b in user_bots if b.status == 'running']),
            'pending_commands': pending_commands,
            'bot_status': bot_status,
            'recent_errors': [{
                'user_id': event.user_id,
                'payload': event.payload_dict,
                'created_at': event.created_at.isoformat()
            } for event in recent_errors]
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api.route('/admin/users', methods=['GET'])
@login_required
def admin_list_users():
    """관리자 - 사용자 목록"""
    if not is_admin():
        return jsonify({'error': 'Admin access required'}), 403
    
    try:
        search = request.args.get('search', '').strip()
        
        query = User.query
        if search:
            query = query.filter(
                db.or_(
                    User.email.ilike(f'%{search}%'),
                    User.id == int(search) if search.isdigit() else False
                )
            )
        
        users = query.limit(50).all()
        
        result = []
        for user in users:
            bot_info = UserBot.query.get(user.id)
            result.append({
                'id': user.id,
                'email': user.email,
                'symbol': user.symbol,
                'side': user.side,
                'leverage': user.leverage,
                'rounds': user.rounds,
                'repeat': user.repeat,
                'bot_status': bot_info.status if bot_info else 'stopped',
                'bot_pid': bot_info.pid if bot_info else None
            })
        
        return jsonify({'users': result})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500