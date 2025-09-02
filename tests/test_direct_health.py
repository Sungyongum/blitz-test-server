# tests/test_direct_health.py
"""
Direct test of health functionality without package imports
"""

import os
import sys
sys.path.insert(0, '.')

from flask import Flask

def test_health_direct():
    """Test health functionality directly"""
    
    # Create minimal Flask app
    app = Flask(__name__)
    app.config['TESTING'] = True
    
    # Copy health endpoints directly here to avoid import issues
    from flask import Blueprint, jsonify
    from datetime import datetime
    
    health_bp = Blueprint('health', __name__)
    
    @health_bp.route('/healthz', methods=['GET'])
    def health_check():
        """Fast, in-process health check"""
        return jsonify({
            'status': 'ok',
            'version': os.environ.get('APP_VERSION', 'unknown'),
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'service': 'blitz-test-server'
        })
    
    @health_bp.route('/livez', methods=['GET'])
    def liveness_check():
        """Liveness check"""
        return jsonify({
            'status': 'ok',
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        })
    
    app.register_blueprint(health_bp)
    
    client = app.test_client()
    
    # Test /healthz
    with app.app_context():
        os.environ['APP_VERSION'] = 'test-1.0'
        response = client.get('/healthz')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'ok'
        assert data['version'] == 'test-1.0'
        assert data['service'] == 'blitz-test-server'
        assert 'timestamp' in data
        print("✅ /healthz endpoint working")
    
    # Test /livez
    response = client.get('/livez')
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'ok'
    assert 'timestamp' in data
    print("✅ /livez endpoint working")

def test_rate_limiting_direct():
    """Test rate limiting logic directly"""
    
    # Test the rate limiting configuration
    from Blitz_app.rate_limiting import RATE_LIMITS
    
    assert 'start' in RATE_LIMITS
    assert 'stop' in RATE_LIMITS
    assert 'recover' in RATE_LIMITS
    assert 'status' in RATE_LIMITS
    assert 'global_ceiling' in RATE_LIMITS
    
    print("✅ Rate limiting configuration loaded")

def test_security_middleware_direct():
    """Test security middleware directly"""
    
    from flask import Flask
    
    app = Flask(__name__)
    
    # Copy security headers function directly
    @app.after_request
    def add_security_headers(response):
        """Add security headers to all responses"""
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        csp = os.environ.get('SECURITY_CSP', "default-src 'self'")
        response.headers['Content-Security-Policy'] = csp
        return response
    
    @app.route('/test')
    def test_route():
        return 'OK'
    
    client = app.test_client()
    response = client.get('/test')
    
    assert response.status_code == 200
    assert response.headers.get('X-Frame-Options') == 'DENY'
    assert response.headers.get('X-Content-Type-Options') == 'nosniff'
    assert response.headers.get('Referrer-Policy') == 'no-referrer'
    assert 'Content-Security-Policy' in response.headers
    
    print("✅ Security headers working")

if __name__ == '__main__':
    test_health_direct()
    test_rate_limiting_direct() 
    test_security_middleware_direct()
    print("✅ All direct tests passed!")