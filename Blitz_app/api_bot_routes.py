# Blitz_app/api_bot_routes.py
"""
SimpleBotManager API Routes

Provides the 4 core endpoints for bot control and 1 admin endpoint:
- POST /api/bot/start
- POST /api/bot/stop  
- GET  /api/bot/status
- POST /api/bot/recover
- GET  /admin/simple/status (admin only)
"""

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from simple_bot_manager import get_simple_bot_manager
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

api_bot = Blueprint('api_bot', __name__)

@api_bot.route('/api/bot/start', methods=['POST'])
@login_required
def start_bot():
    """
    Start bot for current user. Duplicate starts are rejected.
    Returns: {"success": bool, "message": str, "status": str}
    """
    try:
        manager = get_simple_bot_manager()
        if not manager:
            return jsonify({
                "success": False,
                "message": "Bot manager not initialized",
                "status": "error"
            }), 500
        
        result = manager.start_bot_for_user(current_user.id)
        
        # Log the start attempt
        logger.info(f"Bot start request for user {current_user.id}: {result['message']}")
        
        # Return appropriate HTTP status
        if result['success']:
            return jsonify(result), 200
        elif result['status'] == 'already_running':
            return jsonify(result), 409  # Conflict
        else:
            return jsonify(result), 400  # Bad Request
            
    except Exception as e:
        logger.error(f"Error in start_bot for user {current_user.id}: {e}")
        return jsonify({
            "success": False,
            "message": f"Internal error: {str(e)}",
            "status": "error"
        }), 500

@api_bot.route('/api/bot/stop', methods=['POST'])
@login_required
def stop_bot():
    """
    Stop bot for current user.
    Returns: {"success": bool, "message": str, "status": str}
    """
    try:
        manager = get_simple_bot_manager()
        if not manager:
            return jsonify({
                "success": False,
                "message": "Bot manager not initialized",
                "status": "error"
            }), 500
        
        result = manager.stop_bot_for_user(current_user.id)
        
        # Log the stop attempt
        logger.info(f"Bot stop request for user {current_user.id}: {result['message']}")
        
        # Return appropriate HTTP status
        if result['success']:
            return jsonify(result), 200
        else:
            return jsonify(result), 400  # Bad Request
            
    except Exception as e:
        logger.error(f"Error in stop_bot for user {current_user.id}: {e}")
        return jsonify({
            "success": False,
            "message": f"Internal error: {str(e)}",
            "status": "error"
        }), 500

@api_bot.route('/api/bot/status', methods=['GET'])
@login_required
def get_bot_status():
    """
    Get bot status for current user.
    Returns: {"running": bool, "status": str, "uptime": int, "message": str}
    """
    try:
        manager = get_simple_bot_manager()
        if not manager:
            return jsonify({
                "running": False,
                "status": "error",
                "uptime": 0,
                "message": "Bot manager not initialized"
            }), 500
        
        result = manager.get_bot_status(current_user.id)
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Error in get_bot_status for user {current_user.id}: {e}")
        return jsonify({
            "running": False,
            "status": "error", 
            "uptime": 0,
            "message": f"Internal error: {str(e)}"
        }), 500

@api_bot.route('/api/bot/recover', methods=['POST'])
@login_required
def recover_bot_orders():
    """
    Recover missing orders for current user (create missing TP and ladder legs only).
    No destructive resets.
    Returns: {"success": bool, "message": str, "actions": list}
    """
    try:
        manager = get_simple_bot_manager()
        if not manager:
            return jsonify({
                "success": False,
                "message": "Bot manager not initialized", 
                "actions": []
            }), 500
        
        result = manager.recover_orders_for_user(current_user.id)
        
        # Log the recovery attempt
        logger.info(f"Bot recovery request for user {current_user.id}: {result['message']}")
        
        # Return appropriate HTTP status
        if result['success']:
            return jsonify(result), 200
        else:
            return jsonify(result), 400  # Bad Request
            
    except Exception as e:
        logger.error(f"Error in recover_bot_orders for user {current_user.id}: {e}")
        return jsonify({
            "success": False,
            "message": f"Internal error: {str(e)}",
            "actions": []
        }), 500

@api_bot.route('/admin/simple/status', methods=['GET'])
@login_required
def admin_bot_status():
    """
    Admin-only endpoint to get status of all managed bots.
    Returns: {"users": {user_id: {...}}, "totals": {...}}
    """
    try:
        # Check admin permission
        if current_user.email != 'admin@admin.com':
            return jsonify({
                "error": "Admin access required"
            }), 403
        
        manager = get_simple_bot_manager()
        if not manager:
            return jsonify({
                "users": {},
                "totals": {
                    "total_managed": 0,
                    "total_running": 0,
                    "error": "Bot manager not initialized"
                }
            }), 500
        
        result = manager.get_all_bot_statuses()
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Error in admin_bot_status: {e}")
        return jsonify({
            "users": {},
            "totals": {
                "total_managed": 0,
                "total_running": 0,
                "error": f"Internal error: {str(e)}"
            }
        }), 500

@api_bot.route('/__debug/db', methods=['GET'])
def debug_db():
    """
    Lightweight diagnostic route for database troubleshooting.
    Returns: {"cwd": str, "instance_path": str, "db_uri": str, "db_path": str, "db_exists": bool}
    """
    try:
        import os
        from pathlib import Path
        from flask import current_app
        
        # Get current working directory
        cwd = os.getcwd()
        
        # Get Flask instance path
        instance_path = current_app.instance_path
        
        # Get database URI from config
        db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', 'Not configured')
        
        # Extract actual file path from SQLite URI
        db_path = "N/A"
        db_exists = False
        
        if db_uri.startswith('sqlite:///'):
            db_path = db_uri.replace('sqlite:///', '')
            if not os.path.isabs(db_path):
                db_path = os.path.join(instance_path, db_path)
            db_exists = os.path.exists(db_path)
        
        return jsonify({
            "cwd": cwd,
            "instance_path": instance_path,
            "db_uri": db_uri,
            "db_path": db_path,
            "db_exists": db_exists,
            "timestamp": str(datetime.utcnow())
        }), 200
        
    except Exception as e:
        return jsonify({
            "error": f"Debug error: {str(e)}"
        }), 500