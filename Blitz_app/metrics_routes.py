# Blitz_app/metrics_routes.py
"""
Prometheus metrics endpoint for monitoring and observability
"""

import os
from flask import Blueprint, Response, current_app
from werkzeug.exceptions import NotFound

metrics_bp = Blueprint('metrics', __name__)

@metrics_bp.route('/metrics', methods=['GET'])
def prometheus_metrics():
    """
    Prometheus metrics endpoint - opt-in via ENABLE_METRICS=true
    Returns 404 if metrics are disabled.
    """
    if not os.environ.get('ENABLE_METRICS', '').lower() == 'true':
        raise NotFound("Metrics endpoint is disabled")
    
    try:
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        return Response(generate_latest(), content_type=CONTENT_TYPE_LATEST)
    except ImportError:
        current_app.logger.warning("prometheus_client not installed, metrics endpoint unavailable")
        raise NotFound("Metrics endpoint not available - prometheus_client not installed")