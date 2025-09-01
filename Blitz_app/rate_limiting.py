# Blitz_app/rate_limiting.py
"""
Rate limiting configuration using Flask-Limiter with Redis backend and fallback
"""

import os
from flask import current_app
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import current_user

# Rate limiting configuration from environment variables
RATE_LIMITS = {
    'start': os.environ.get('RATE_LIMITS_START', '10/minute'),
    'stop': os.environ.get('RATE_LIMITS_STOP', '10/minute'), 
    'recover': os.environ.get('RATE_LIMITS_RECOVER', '10/minute'),
    'status': os.environ.get('RATE_LIMITS_STATUS', '30/minute'),
    'global_ceiling': os.environ.get('RATE_LIMITS_GLOBAL', '200/minute')
}

def get_user_id():
    """Get current user ID for rate limiting key"""
    try:
        if current_user.is_authenticated:
            return f"user:{current_user.id}"
    except:
        pass
    # Fallback to IP address
    return get_remote_address()

def setup_rate_limiting(app):
    """Setup Flask-Limiter with Redis backend and fallback"""
    
    # Configure storage backend
    redis_url = os.environ.get('RATE_LIMIT_REDIS_URL')
    storage_uri = None
    
    if redis_url:
        storage_uri = redis_url
        app.logger.info("Rate limiting using Redis backend", extra={'redis_url': redis_url})
    else:
        # Fallback to in-memory storage
        storage_uri = "memory://"
        app.logger.warning("Rate limiting using in-memory storage - not suitable for production")
    
    # Create limiter instance
    limiter = Limiter(
        app=app,
        key_func=get_user_id,
        storage_uri=storage_uri,
        default_limits=[RATE_LIMITS['global_ceiling']],
        default_limits_deduct_when=lambda: True,
        default_limits_exempt_when=lambda: current_user.is_authenticated and getattr(current_user, 'email', '') == 'admin@admin.com'
    )
    
    return limiter