# Blitz_app/metrics_setup.py
"""
Prometheus metrics setup and initialization
"""

import os
from flask import current_app

def setup_metrics(app):
    """Setup Prometheus metrics if enabled"""
    
    if not os.environ.get('ENABLE_METRICS', '').lower() == 'true':
        app.logger.info("Metrics disabled - set ENABLE_METRICS=true to enable")
        return None
    
    try:
        from prometheus_client import Counter, Histogram, Gauge, Info, generate_latest
        import time
        
        # Initialize application metrics
        app._metrics = {
            # Request metrics
            'request_count': Counter(
                'http_requests_total',
                'Total HTTP requests',
                ['method', 'endpoint', 'status']
            ),
            'request_latency': Histogram(
                'http_request_duration_seconds',
                'HTTP request latency',
                ['method', 'endpoint']
            ),
            
            # Bot operation metrics
            'bot_starts_total': Counter(
                'bot_starts_total',
                'Total bot starts',
                ['user_id', 'status']
            ),
            'bot_stops_total': Counter(
                'bot_stops_total', 
                'Total bot stops',
                ['user_id', 'status']
            ),
            'bot_recovers_total': Counter(
                'bot_recovers_total',
                'Total bot recoveries', 
                ['user_id', 'status']
            ),
            'errors_total': Counter(
                'errors_total',
                'Total application errors',
                ['type', 'component']
            ),
            
            # System metrics
            'active_bots': Gauge(
                'active_bots_total',
                'Number of currently active bots'
            ),
            'app_info': Info(
                'app_info',
                'Application information'
            )
        }
        
        # Set application info
        app._metrics['app_info'].info({
            'version': os.environ.get('APP_VERSION', 'unknown'),
            'environment': os.environ.get('FLASK_ENV', 'unknown')
        })
        
        # Setup request metrics middleware
        @app.before_request
        def before_request():
            import time
            from flask import g, request
            g.start_time = time.time()
        
        @app.after_request
        def after_request(response):
            from flask import g, request
            
            if hasattr(g, 'start_time'):
                duration = time.time() - g.start_time
                
                # Record request metrics
                app._metrics['request_count'].labels(
                    method=request.method,
                    endpoint=request.endpoint or 'unknown',
                    status=response.status_code
                ).inc()
                
                app._metrics['request_latency'].labels(
                    method=request.method,
                    endpoint=request.endpoint or 'unknown'
                ).observe(duration)
            
            return response
        
        # Update active bots metric periodically
        def update_active_bots():
            try:
                from simple_bot_manager import get_simple_bot_manager
                manager = get_simple_bot_manager()
                if manager:
                    status = manager.get_all_bot_statuses()
                    active_count = status.get('totals', {}).get('running', 0)
                    app._metrics['active_bots'].set(active_count)
            except Exception as e:
                app.logger.warning(f"Failed to update active bots metric: {e}")
        
        # Schedule periodic updates (in a real app, use a background scheduler)
        app.update_active_bots = update_active_bots
        
        app.logger.info("Prometheus metrics initialized")
        
        # Setup multiprocess mode if configured
        multiproc_dir = os.environ.get('PROMETHEUS_MULTIPROC_DIR')
        if multiproc_dir:
            app.logger.info(f"Prometheus multiprocess mode configured: {multiproc_dir}")
        
        return app._metrics
        
    except ImportError:
        app.logger.warning("prometheus_client not installed - metrics unavailable")
        return None
    except Exception as e:
        app.logger.error(f"Failed to setup metrics: {e}")
        return None