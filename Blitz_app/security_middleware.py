# Blitz_app/security_middleware.py
"""
Security headers and middleware for hardening the application
"""

import os
from flask import request, abort, current_app

def setup_security_headers(app):
    """Setup security headers middleware"""
    
    @app.after_request
    def add_security_headers(response):
        """Add security headers to all responses"""
        
        # Basic security headers
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        
        # Content Security Policy - customizable via environment
        csp = os.environ.get('SECURITY_CSP', 
                           "default-src 'self'; script-src 'self' 'unsafe-inline' cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' cdn.jsdelivr.net; img-src 'self' data:; font-src 'self' cdn.jsdelivr.net")
        response.headers['Content-Security-Policy'] = csp
        
        return response

def setup_request_size_limits(app):
    """Setup request size limiting middleware"""
    
    max_content_length = int(os.environ.get('MAX_REQUEST_BYTES', 1024 * 1024))  # 1MB default
    app.config['MAX_CONTENT_LENGTH'] = max_content_length
    
    @app.before_request
    def limit_request_size():
        """Check request size before processing"""
        if request.content_length and request.content_length > max_content_length:
            abort(413, "Request entity too large")

def setup_session_security(app):
    """Setup secure session configuration"""
    
    # Session security settings
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=os.environ.get('SESSION_SECURE', 'false').lower() == 'true',
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=3600 * 24,  # 24 hours
    )
    
    # CSRF protection settings
    app.config.update(
        WTF_CSRF_TIME_LIMIT=3600,  # 1 hour
        WTF_CSRF_SSL_STRICT=os.environ.get('CSRF_SSL_STRICT', 'false').lower() == 'true'
    )

def setup_security_middleware(app):
    """Setup all security middleware"""
    setup_security_headers(app)
    setup_request_size_limits(app)
    setup_session_security(app)
    
    app.logger.info("Security middleware configured", extra={
        'max_request_bytes': app.config.get('MAX_CONTENT_LENGTH'),
        'session_secure': app.config.get('SESSION_COOKIE_SECURE'),
        'csrf_ssl_strict': app.config.get('WTF_CSRF_SSL_STRICT')
    })