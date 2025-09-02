# Blitz_app/enhanced_bot_routes.py
"""
Enhanced bot API routes with rate limiting, concurrency guards, and monitoring
"""

from flask import Blueprint, jsonify, request, current_app, g
from flask_login import login_required, current_user
from functools import wraps
import time

from .rate_limiting import RATE_LIMITS

enhanced_bot_bp = Blueprint('enhanced_bot', __name__)

def with_metrics(operation_name):
    """Decorator to track metrics for bot operations"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            start_time = time.time()
            
            try:
                # Import metrics only if enabled
                try:
                    import os
                    if os.environ.get('ENABLE_METRICS', '').lower() == 'true':
                        from prometheus_client import Counter, Histogram
                        
                        # Initialize metrics if they don't exist
                        if not hasattr(current_app, '_bot_metrics'):
                            current_app._bot_metrics = {
                                'operations_total': Counter('bot_operations_total', 'Total bot operations', ['operation', 'status', 'user_id']),
                                'operation_duration': Histogram('bot_operation_duration_seconds', 'Bot operation duration', ['operation'])
                            }
                        
                        metrics = current_app._bot_metrics
                except (ImportError, Exception):
                    metrics = None
                
                result = f(*args, **kwargs)
                
                # Record success metrics
                if metrics:
                    duration = time.time() - start_time
                    user_id = str(current_user.id) if current_user.is_authenticated else 'anonymous'
                    metrics['operations_total'].labels(operation=operation_name, status='success', user_id=user_id).inc()
                    metrics['operation_duration'].labels(operation=operation_name).observe(duration)
                
                # Add timing to response if it's JSON
                if isinstance(result, tuple) and len(result) == 2:
                    response_data, status_code = result
                    if isinstance(response_data, dict):
                        response_data = jsonify(response_data)
                else:
                    response_data = result
                    status_code = 200
                
                return response_data, status_code
                
            except Exception as e:
                # Record error metrics
                if metrics:
                    user_id = str(current_user.id) if current_user.is_authenticated else 'anonymous'
                    metrics['operations_total'].labels(operation=operation_name, status='error', user_id=user_id).inc()
                
                # Log the error
                current_app.logger.error(f"Bot operation {operation_name} failed", extra={
                    'operation': operation_name,
                    'user_id': current_user.id if current_user.is_authenticated else None,
                    'error': str(e),
                    'request_id': getattr(g, 'request_id', None)
                })
                raise
                
        return decorated_function
    return decorator

def check_user_concurrency():
    """Check if user already has a bot operation in progress"""
    from simple_bot_manager import get_simple_bot_manager
    
    manager = get_simple_bot_manager()
    if not manager:
        return True  # Allow if manager not available
    
    # Check if user has operations in progress
    # This is a simple implementation - in production you'd want a more sophisticated queue
    user_id = current_user.id
    
    # For now, we'll use a simple check based on the existing bot status
    try:
        status = manager.get_bot_status(user_id)
        if status.get('success') and 'already running' in status.get('message', ''):
            return False  # User has bot running, reject concurrent start
    except:
        pass
    
    return True

# Apply rate limiting to the blueprint
def setup_enhanced_bot_routes(limiter):
    """Setup enhanced bot routes with rate limiting"""
    
    @enhanced_bot_bp.route('/api/bot/start', methods=['POST'])
    @limiter.limit(RATE_LIMITS['start'])
    @login_required
    @with_metrics('start')
    def enhanced_start_bot():
        """Enhanced start bot with concurrency guard and metrics"""
        
        # Check for concurrent operations
        if not check_user_concurrency():
            current_app.logger.warning("Concurrent bot start rejected", extra={
                'user_id': current_user.id,
                'request_id': getattr(g, 'request_id', None)
            })
            return jsonify({
                'success': False,
                'message': 'Bot operation already in progress for this user. Please wait.',
                'retry_after': 30
            }), 429
        
        # Use SimpleBotManager
        from simple_bot_manager import get_simple_bot_manager
        manager = get_simple_bot_manager()
        
        if not manager:
            return jsonify({
                'success': False,
                'message': 'Bot manager not available'
            }), 503
        
        result = manager.start_bot_for_user(current_user.id)
        
        current_app.logger.info("Bot start requested", extra={
            'user_id': current_user.id,
            'success': result.get('success'),
            'request_id': getattr(g, 'request_id', None)
        })
        
        return jsonify(result)

    @enhanced_bot_bp.route('/api/bot/stop', methods=['POST'])
    @limiter.limit(RATE_LIMITS['stop'])
    @login_required
    @with_metrics('stop')
    def enhanced_stop_bot():
        """Enhanced stop bot with metrics"""
        
        from simple_bot_manager import get_simple_bot_manager
        manager = get_simple_bot_manager()
        
        if not manager:
            return jsonify({
                'success': False,
                'message': 'Bot manager not available'
            }), 503
        
        result = manager.stop_bot_for_user(current_user.id)
        
        current_app.logger.info("Bot stop requested", extra={
            'user_id': current_user.id,
            'success': result.get('success'),
            'request_id': getattr(g, 'request_id', None)
        })
        
        return jsonify(result)

    @enhanced_bot_bp.route('/api/bot/status', methods=['GET'])
    @limiter.limit(RATE_LIMITS['status'])
    @login_required
    @with_metrics('status')
    def enhanced_bot_status():
        """Enhanced bot status with metrics"""
        
        from simple_bot_manager import get_simple_bot_manager
        manager = get_simple_bot_manager()
        
        if not manager:
            return jsonify({
                'success': False,
                'message': 'Bot manager not available'
            }), 503
        
        result = manager.get_bot_status(current_user.id)
        return jsonify(result)

    @enhanced_bot_bp.route('/api/bot/recover', methods=['POST'])
    @limiter.limit(RATE_LIMITS['recover'])
    @login_required
    @with_metrics('recover')
    def enhanced_recover_bot():
        """Enhanced bot recovery with metrics"""
        
        from simple_bot_manager import get_simple_bot_manager
        manager = get_simple_bot_manager()
        
        if not manager:
            return jsonify({
                'success': False,
                'message': 'Bot manager not available'
            }), 503
        
        result = manager.recover_orders_for_user(current_user.id)
        
        current_app.logger.info("Bot recovery requested", extra={
            'user_id': current_user.id,
            'success': result.get('success'),
            'request_id': getattr(g, 'request_id', None)
        })
        
        return jsonify(result)

    return enhanced_bot_bp