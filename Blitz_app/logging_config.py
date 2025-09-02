# Blitz_app/logging_config.py
"""
Structured JSON logging configuration with request ID propagation and secret filtering
"""

import re
import logging
import os
import uuid
from flask import request, g, current_app
from pythonjsonlogger import jsonlogger


class SecretMaskingFilter(logging.Filter):
    """Filter to mask secrets in log messages"""
    
    # Pattern to match secret-like field names (case insensitive)
    SECRET_PATTERNS = [
        re.compile(r'(api_key|secret|password|token|authorization|auth|key)[\'"]*\s*[:=]\s*[\'"]?([^\'",\s]+)', re.IGNORECASE),
        re.compile(r'("api_key"|"secret"|"password"|"token"|"authorization"|"auth"|"key")\s*:\s*"([^"]+)"', re.IGNORECASE),
    ]
    
    def filter(self, record):
        """Mask secrets in log record"""
        if hasattr(record, 'msg'):
            msg = str(record.msg)
            for pattern in self.SECRET_PATTERNS:
                msg = pattern.sub(r'\1: ****', msg)
            record.msg = msg
        
        # Also check args for formatting
        if hasattr(record, 'args') and record.args:
            masked_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    for pattern in self.SECRET_PATTERNS:
                        arg = pattern.sub(r'\1: ****', arg)
                masked_args.append(arg)
            record.args = tuple(masked_args)
        
        return True


class RequestIDFormatter(jsonlogger.JsonFormatter):
    """Custom JSON formatter that includes request context"""
    
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        
        # Add timestamp
        log_record['timestamp'] = self.formatTime(record, self.datefmt)
        
        # Add request context if available
        if request:
            log_record['request_id'] = getattr(g, 'request_id', None)
            log_record['path'] = request.path
            log_record['method'] = request.method
            log_record['remote_addr'] = request.remote_addr
            
            # Add user context if available
            try:
                from flask_login import current_user
                if current_user.is_authenticated:
                    log_record['user_id'] = current_user.id
            except:
                pass


def setup_logging(app):
    """Setup structured JSON logging for the application"""
    
    # Create JSON formatter
    formatter = RequestIDFormatter(
        '%(timestamp)s %(level)s %(name)s %(message)s',
        rename_fields={
            'levelname': 'level',
            'name': 'logger',
            'module': 'module',
            'funcName': 'func',
            'lineno': 'line'
        }
    )
    
    # Get or create handler
    handler = None
    if app.logger.handlers:
        handler = app.logger.handlers[0]
    else:
        handler = logging.StreamHandler()
        app.logger.addHandler(handler)
    
    # Configure handler
    handler.setFormatter(formatter)
    
    # Add secret masking filter
    secret_filter = SecretMaskingFilter()
    handler.addFilter(secret_filter)
    
    # Set log level from environment
    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    app.logger.setLevel(getattr(logging, log_level, logging.INFO))
    handler.setLevel(getattr(logging, log_level, logging.INFO))
    
    app.logger.info("Structured JSON logging configured", extra={
        'log_level': log_level,
        'handler_class': handler.__class__.__name__
    })


def generate_request_id():
    """Generate a unique request ID"""
    return str(uuid.uuid4())


def setup_request_id_middleware(app):
    """Setup middleware to generate and propagate request IDs"""
    
    @app.before_request
    def before_request():
        # Generate or extract request ID
        request_id = request.headers.get('X-Request-ID')
        if not request_id:
            request_id = generate_request_id()
        
        # Store in Flask g for access throughout request
        g.request_id = request_id
    
    @app.after_request
    def after_request(response):
        # Add request ID to response headers
        if hasattr(g, 'request_id'):
            response.headers['X-Request-ID'] = g.request_id
        return response