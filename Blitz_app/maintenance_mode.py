# Blitz_app/maintenance_mode.py
"""
Maintenance mode functionality for admin control
"""

import os
from flask import Blueprint, jsonify, request, abort, current_app, g
from flask_login import login_required, current_user

# Global state - in production this should be in Redis or database
_maintenance_mode = {
    'enabled': os.environ.get('MAINTENANCE_MODE_DEFAULT', 'false').lower() == 'true',
    'banner_message': os.environ.get('BROADCAST_BANNER', '')
}

maintenance_bp = Blueprint('maintenance', __name__)

def is_admin():
    """Check if current user is admin"""
    try:
        return current_user.is_authenticated and current_user.email == 'admin@admin.com'
    except:
        return False

def is_maintenance_mode():
    """Check if maintenance mode is enabled"""
    return _maintenance_mode['enabled']

def get_banner_message():
    """Get current banner message"""
    return _maintenance_mode['banner_message']

@maintenance_bp.route('/admin/maintenance/enable', methods=['POST'])
@login_required
def enable_maintenance():
    """Enable maintenance mode (admin only)"""
    if not is_admin():
        abort(403, "Admin access required")
    
    _maintenance_mode['enabled'] = True
    current_app.logger.info("Maintenance mode enabled", extra={
        'admin_user': current_user.email,
        'request_id': getattr(g, 'request_id', None)
    })
    
    return jsonify({
        'status': 'success',
        'message': 'Maintenance mode enabled',
        'maintenance_enabled': True
    })

@maintenance_bp.route('/admin/maintenance/disable', methods=['POST'])
@login_required  
def disable_maintenance():
    """Disable maintenance mode (admin only)"""
    if not is_admin():
        abort(403, "Admin access required")
    
    _maintenance_mode['enabled'] = False
    current_app.logger.info("Maintenance mode disabled", extra={
        'admin_user': current_user.email,
        'request_id': getattr(g, 'request_id', None)
    })
    
    return jsonify({
        'status': 'success',
        'message': 'Maintenance mode disabled',
        'maintenance_enabled': False
    })

@maintenance_bp.route('/admin/banner', methods=['POST'])
@login_required
def set_banner():
    """Set global banner message (admin only)"""
    if not is_admin():
        abort(403, "Admin access required")
    
    data = request.get_json() or {}
    message = data.get('message', '').strip()
    
    _maintenance_mode['banner_message'] = message
    current_app.logger.info("Banner message updated", extra={
        'admin_user': current_user.email,
        'message_length': len(message),
        'request_id': getattr(g, 'request_id', None)
    })
    
    return jsonify({
        'status': 'success',
        'message': 'Banner updated',
        'banner_message': message
    })

@maintenance_bp.route('/admin/banner/clear', methods=['POST'])
@login_required
def clear_banner():
    """Clear global banner message (admin only)"""
    if not is_admin():
        abort(403, "Admin access required")
    
    _maintenance_mode['banner_message'] = ''
    current_app.logger.info("Banner message cleared", extra={
        'admin_user': current_user.email,
        'request_id': getattr(g, 'request_id', None)
    })
    
    return jsonify({
        'status': 'success',
        'message': 'Banner cleared',
        'banner_message': ''
    })

@maintenance_bp.route('/api/status', methods=['GET'])
def status():
    """Get current maintenance and banner status (public endpoint)"""
    return jsonify({
        'maintenance_enabled': _maintenance_mode['enabled'],
        'banner_message': _maintenance_mode['banner_message']
    })

def setup_maintenance_middleware(app):
    """Setup maintenance mode middleware"""
    
    @app.before_request
    def check_maintenance_mode():
        """Block non-admin POST requests to /api/bot/* during maintenance"""
        if not _maintenance_mode['enabled']:
            return  # Not in maintenance mode
        
        # Allow GET requests and health checks
        if request.method != 'POST':
            return
        
        # Allow admin users
        if is_admin():
            return
        
        # Block POST requests to bot API during maintenance
        if request.path.startswith('/api/bot/'):
            abort(503, "Service temporarily unavailable - maintenance mode enabled")
    
    # Register template context for banner display
    @app.context_processor
    def inject_maintenance_status():
        return {
            'maintenance_enabled': _maintenance_mode['enabled'],
            'banner_message': _maintenance_mode['banner_message']
        }