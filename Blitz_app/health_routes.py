# Blitz_app/health_routes.py
"""
Health and observability endpoints for operational monitoring
"""

import os
import time
import json
from datetime import datetime
from flask import Blueprint, jsonify, request, current_app
from werkzeug.exceptions import NotFound

from .extensions import db

health_bp = Blueprint('health', __name__)

@health_bp.route('/healthz', methods=['GET'])
def health_check():
    """
    Fast, in-process health check - returns ok + version + time
    This should always be fast and not depend on external services.
    """
    return jsonify({
        'status': 'ok',
        'version': os.environ.get('APP_VERSION', 'unknown'),
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'service': 'blitz-test-server'
    })

@health_bp.route('/livez', methods=['GET'])
def liveness_check():
    """
    Liveness check - always returns ok if process is alive
    Kubernetes uses this to determine if container should be restarted.
    """
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    })

@health_bp.route('/readyz', methods=['GET'])
def readiness_check():
    """
    Readiness check - checks if app is ready to serve traffic
    Verifies DB connectivity, SimpleBotManager registry integrity.
    """
    checks = {
        'database': False,
        'bot_manager': False
    }
    overall_status = 'ok'
    
    # Check database connectivity
    try:
        # Simple SELECT 1 query
        db.session.execute(db.text('SELECT 1'))
        checks['database'] = True
    except Exception as e:
        current_app.logger.error(f"Database health check failed: {e}")
        checks['database'] = False
        overall_status = 'error'
    
    # Check SimpleBotManager thread registry integrity
    try:
        from simple_bot_manager import get_simple_bot_manager
        manager = get_simple_bot_manager()
        if manager is not None:
            # Check if manager is responsive
            manager.get_all_bot_statuses()
            checks['bot_manager'] = True
        else:
            checks['bot_manager'] = False
            overall_status = 'error'
    except Exception as e:
        current_app.logger.error(f"Bot manager health check failed: {e}")
        checks['bot_manager'] = False
        overall_status = 'error'
    
    response_data = {
        'status': overall_status,
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'checks': checks
    }
    
    status_code = 200 if overall_status == 'ok' else 503
    return jsonify(response_data), status_code