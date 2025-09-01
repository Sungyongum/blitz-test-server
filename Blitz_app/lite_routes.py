# Blitz_app/lite_routes.py

from flask import Blueprint, request, jsonify, render_template, redirect, url_for
from flask_login import login_required, current_user
from werkzeug.exceptions import BadRequest
import logging
import os

from .simple_bot_manager import get_simple_bot_manager
from .utils import is_admin

logger = logging.getLogger(__name__)

lite = Blueprint('lite', __name__)

@lite.route('/api/bot/start', methods=['POST'])
@login_required
def start_bot():
    """Start bot for current user. Rejects duplicates with 409."""
    try:
        bot_manager = get_simple_bot_manager()
        if not bot_manager:
            return jsonify({'error': 'Bot manager not initialized'}), 500
            
        success, message = bot_manager.start_bot_for_user(current_user.id)
        
        if success:
            logger.info(f"✅ Bot start successful for user {current_user.id}")
            return jsonify({
                'success': True,
                'message': message,
                'user_id': current_user.id
            }), 200
        else:
            if "already running" in message.lower():
                logger.warning(f"❌ Duplicate start attempt for user {current_user.id}")
                return jsonify({
                    'success': False,
                    'message': message,
                    'user_id': current_user.id
                }), 409  # Conflict
            else:
                logger.error(f"❌ Bot start failed for user {current_user.id}: {message}")
                return jsonify({
                    'success': False,
                    'message': message,
                    'user_id': current_user.id
                }), 400
                
    except Exception as e:
        logger.error(f"❌ Bot start error for user {current_user.id}: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Internal error: {str(e)}',
            'user_id': current_user.id
        }), 500

@lite.route('/api/bot/stop', methods=['POST'])
@login_required  
def stop_bot():
    """Stop bot for current user."""
    try:
        bot_manager = get_simple_bot_manager()
        if not bot_manager:
            return jsonify({'error': 'Bot manager not initialized'}), 500
            
        success, message = bot_manager.stop_bot_for_user(current_user.id)
        
        logger.info(f"✅ Bot stop for user {current_user.id}: {message}")
        return jsonify({
            'success': success,
            'message': message,
            'user_id': current_user.id
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Bot stop error for user {current_user.id}: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Internal error: {str(e)}',
            'user_id': current_user.id
        }), 500

@lite.route('/api/bot/status', methods=['GET'])
@login_required
def get_bot_status():
    """Get bot status for current user."""
    try:
        bot_manager = get_simple_bot_manager()
        if not bot_manager:
            return jsonify({'error': 'Bot manager not initialized'}), 500
            
        status = bot_manager.get_bot_status(current_user.id)
        return jsonify(status), 200
        
    except Exception as e:
        logger.error(f"❌ Bot status error for user {current_user.id}: {str(e)}")
        return jsonify({
            'error': f'Internal error: {str(e)}',
            'user_id': current_user.id
        }), 500

@lite.route('/api/bot/recover', methods=['POST'])
@login_required
def recover_orders():
    """Recover orders for current user (idempotent - creates missing TP and ladder legs only)."""
    try:
        bot_manager = get_simple_bot_manager()
        if not bot_manager:
            return jsonify({'error': 'Bot manager not initialized'}), 500
            
        success, message = bot_manager.recover_orders_for_user(current_user.id)
        
        if success:
            logger.info(f"✅ Order recovery successful for user {current_user.id}")
        else:
            logger.error(f"❌ Order recovery failed for user {current_user.id}: {message}")
            
        return jsonify({
            'success': success,
            'message': message,
            'user_id': current_user.id
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Order recovery error for user {current_user.id}: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Internal error: {str(e)}',
            'user_id': current_user.id
        }), 500

@lite.route('/admin/simple/status', methods=['GET'])
@login_required
def admin_status():
    """Admin overview - JSON with all managed users status and totals."""
    if not is_admin():
        return jsonify({'error': 'Admin access required'}), 403
        
    try:
        bot_manager = get_simple_bot_manager()
        if not bot_manager:
            return jsonify({'error': 'Bot manager not initialized'}), 500
            
        status = bot_manager.get_all_statuses()
        return jsonify(status), 200
        
    except Exception as e:
        logger.error(f"❌ Admin status error: {str(e)}")
        return jsonify({'error': f'Internal error: {str(e)}'}), 500

@lite.route('/__debug/db', methods=['GET'])
@login_required
def debug_db():
    """Diagnostic route - returns cwd, instance_path, db_uri, db_path, exists."""
    from flask import current_app
    
    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    db_path = db_uri.replace('sqlite:///', '') if db_uri.startswith('sqlite:///') else db_uri
    
    return jsonify({
        'cwd': os.getcwd(),
        'instance_path': current_app.instance_path,
        'db_uri': db_uri,
        'db_path': db_path,
        'exists': os.path.exists(db_path) if db_path.startswith('/') else False
    }), 200

# Template routes for the LITE UI
@lite.route('/', methods=['GET'])
@login_required  
def user_simple():
    """Simple user page with 4 buttons: Start, Stop, Status, Recover."""
    return render_template('user_simple.html', user=current_user)

@lite.route('/admin/console', methods=['GET'])
@login_required
def admin_console():
    """Admin console page with user management and status polling."""
    if not is_admin():
        return redirect(url_for('lite.user_simple'))
    return render_template('admin_console.html')