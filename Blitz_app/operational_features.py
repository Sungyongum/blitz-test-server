# Blitz_app/operational_features.py
"""
Integration module for all operational features
This module can be imported and initialized independently of the main app
"""

import os
from flask import Flask

def setup_operational_features(app: Flask):
    """
    Setup all operational features for the Flask app
    This function integrates all the new operational capabilities
    """
    
    # 1. Setup structured logging and request ID propagation
    try:
        from .logging_config import setup_logging, setup_request_id_middleware
        setup_logging(app)
        setup_request_id_middleware(app)
        app.logger.info("✅ Structured logging and request ID middleware configured")
    except Exception as e:
        app.logger.warning(f"Failed to setup logging: {e}")
    
    # 2. Setup security middleware
    try:
        from .security_middleware import setup_security_middleware
        setup_security_middleware(app)
        app.logger.info("✅ Security middleware configured")
    except Exception as e:
        app.logger.warning(f"Failed to setup security middleware: {e}")
    
    # 3. Setup rate limiting
    try:
        from .rate_limiting import setup_rate_limiting
        limiter = setup_rate_limiting(app)
        app.logger.info("✅ Rate limiting configured")
        
        # Store limiter for use in enhanced bot routes
        app.limiter = limiter
    except Exception as e:
        app.logger.warning(f"Failed to setup rate limiting: {e}")
        app.limiter = None
    
    # 4. Setup metrics if enabled
    try:
        from .metrics_setup import setup_metrics
        metrics = setup_metrics(app)
        if metrics:
            app.logger.info("✅ Prometheus metrics configured")
        else:
            app.logger.info("ℹ️ Metrics disabled or unavailable")
    except Exception as e:
        app.logger.warning(f"Failed to setup metrics: {e}")
    
    # 5. Setup maintenance mode
    try:
        from .maintenance_mode import setup_maintenance_middleware
        setup_maintenance_middleware(app)
        app.logger.info("✅ Maintenance mode middleware configured")
    except Exception as e:
        app.logger.warning(f"Failed to setup maintenance mode: {e}")
    
    # 6. Register health endpoints
    try:
        from .health_routes import health_bp
        app.register_blueprint(health_bp)
        app.logger.info("✅ Health endpoints registered (/healthz, /livez, /readyz)")
    except Exception as e:
        app.logger.warning(f"Failed to register health endpoints: {e}")
    
    # 7. Register metrics endpoint
    try:
        from .metrics_routes import metrics_bp
        app.register_blueprint(metrics_bp)
        app.logger.info("✅ Metrics endpoint registered (/metrics)")
    except Exception as e:
        app.logger.warning(f"Failed to register metrics endpoint: {e}")
    
    # 8. Register maintenance mode endpoints
    try:
        from .maintenance_mode import maintenance_bp
        app.register_blueprint(maintenance_bp)
        app.logger.info("✅ Maintenance mode endpoints registered")
    except Exception as e:
        app.logger.warning(f"Failed to register maintenance endpoints: {e}")
    
    # 9. Register enhanced bot routes (if rate limiter available)
    try:
        if hasattr(app, 'limiter') and app.limiter:
            from .enhanced_bot_routes import setup_enhanced_bot_routes
            enhanced_bot_bp = setup_enhanced_bot_routes(app.limiter)
            app.register_blueprint(enhanced_bot_bp)
            app.logger.info("✅ Enhanced bot routes registered with rate limiting")
        else:
            app.logger.info("ℹ️ Enhanced bot routes skipped (rate limiter not available)")
    except Exception as e:
        app.logger.warning(f"Failed to register enhanced bot routes: {e}")
    
    # 10. Setup database optimizations
    try:
        from .db_utils import setup_database_optimizations
        # Note: This should be called after db.create_all()
        app.setup_db_optimizations = lambda: setup_database_optimizations(app)
        app.logger.info("✅ Database optimization function prepared")
    except Exception as e:
        app.logger.warning(f"Failed to prepare database optimizations: {e}")
    
    app.logger.info("🚀 Operational features setup complete!")
    
    # Return summary
    return {
        'logging': True,
        'security': True, 
        'rate_limiting': hasattr(app, 'limiter'),
        'metrics': os.environ.get('ENABLE_METRICS', '').lower() == 'true',
        'maintenance_mode': True,
        'health_endpoints': True,
        'enhanced_bot_routes': hasattr(app, 'limiter')
    }

def get_operational_status():
    """Get status of operational features"""
    return {
        'health_endpoints': ['/healthz', '/livez', '/readyz'],
        'metrics_endpoint': '/metrics' if os.environ.get('ENABLE_METRICS', '').lower() == 'true' else None,
        'maintenance_endpoints': ['/admin/maintenance/enable', '/admin/maintenance/disable', '/admin/banner'],
        'enhanced_bot_endpoints': ['/api/bot/start', '/api/bot/stop', '/api/bot/status', '/api/bot/recover'],
        'environment_variables': {
            'ENABLE_METRICS': os.environ.get('ENABLE_METRICS', 'false'),
            'RATE_LIMIT_REDIS_URL': 'configured' if os.environ.get('RATE_LIMIT_REDIS_URL') else 'not configured',
            'LOG_LEVEL': os.environ.get('LOG_LEVEL', 'INFO'),
            'MAX_REQUEST_BYTES': os.environ.get('MAX_REQUEST_BYTES', '1048576'),
        }
    }