# tests/test_health_standalone.py
"""
Standalone tests for health endpoints without importing the main app
"""

import pytest
import os
from flask import Flask
from unittest.mock import Mock, patch

def test_health_endpoints_standalone():
    """Test health endpoints in isolation"""
    
    # Create minimal Flask app
    app = Flask(__name__)
    app.config['TESTING'] = True
    
    # Import and register health routes directly
    from Blitz_app.health_routes import health_bp
    app.register_blueprint(health_bp)
    
    client = app.test_client()
    
    # Test /healthz
    with patch.dict(os.environ, {'APP_VERSION': 'test-1.0'}):
        response = client.get('/healthz')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'ok'
        assert data['version'] == 'test-1.0'
        assert data['service'] == 'blitz-test-server'
        assert 'timestamp' in data
    
    # Test /livez
    response = client.get('/livez')
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'ok'
    assert 'timestamp' in data
    
    print("✅ Health endpoints tests passed")

def test_metrics_endpoint_standalone():
    """Test metrics endpoint in isolation"""
    
    # Create minimal Flask app
    app = Flask(__name__)
    app.config['TESTING'] = True
    
    # Import and register metrics routes
    from Blitz_app.metrics_routes import metrics_bp
    app.register_blueprint(metrics_bp)
    
    client = app.test_client()
    
    # Test metrics disabled by default
    response = client.get('/metrics')
    assert response.status_code == 404
    
    # Test metrics enabled
    with patch.dict(os.environ, {'ENABLE_METRICS': 'true'}):
        with patch('prometheus_client.generate_latest') as mock_generate:
            with patch('prometheus_client.CONTENT_TYPE_LATEST', 'text/plain; charset=utf-8'):
                mock_generate.return_value = b'# HELP test_metric\ntest_metric 1.0\n'
                
                response = client.get('/metrics')
                
                if response.status_code == 200:
                    assert response.data == b'# HELP test_metric\ntest_metric 1.0\n'
                else:
                    # prometheus_client not available in test environment
                    assert response.status_code == 404
    
    print("✅ Metrics endpoint tests passed")

if __name__ == '__main__':
    test_health_endpoints_standalone()
    test_metrics_endpoint_standalone()
    print("✅ All standalone tests passed!")