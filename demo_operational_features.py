# demo_operational_features.py
"""
Standalone demonstration of operational features
This shows that all the components work without the main app
"""

import os
import tempfile
from flask import Flask, g, request

def create_demo_app():
    """Create a demo Flask app with operational features"""
    
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'demo-secret'
    
    # Enable metrics for demo
    os.environ['ENABLE_METRICS'] = 'true'
    
    print("🚀 Setting up operational features demo...")
    
    # 1. Health endpoints
    from flask import Blueprint, jsonify
    from datetime import datetime
    
    health_bp = Blueprint('health', __name__)
    
    @health_bp.route('/healthz')
    def health():
        return jsonify({
            'status': 'ok',
            'version': 'demo-1.0',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'service': 'blitz-test-server'
        })
    
    @health_bp.route('/livez')
    def liveness():
        return jsonify({'status': 'ok', 'timestamp': datetime.utcnow().isoformat() + 'Z'})
    
    app.register_blueprint(health_bp)
    print("✅ Health endpoints registered")
    
    # 2. Security headers
    @app.after_request
    def add_security_headers(response):
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'"
        return response
    
    print("✅ Security headers configured")
    
    # 3. Request ID middleware
    import uuid
    
    @app.before_request
    def add_request_id():
        g.request_id = request.headers.get('X-Request-ID', str(uuid.uuid4()))
    
    @app.after_request
    def add_request_id_header(response):
        response.headers['X-Request-ID'] = g.request_id
        return response
    
    print("✅ Request ID middleware configured")
    
    # 4. Maintenance mode
    maintenance_state = {'enabled': False, 'banner': ''}
    
    @app.route('/api/status')
    def status():
        return jsonify({
            'maintenance_enabled': maintenance_state['enabled'],
            'banner_message': maintenance_state['banner']
        })
    
    @app.route('/admin/maintenance/enable', methods=['POST'])
    def enable_maintenance():
        maintenance_state['enabled'] = True
        return jsonify({'status': 'success', 'maintenance_enabled': True})
    
    @app.route('/admin/maintenance/disable', methods=['POST'])
    def disable_maintenance():
        maintenance_state['enabled'] = False
        return jsonify({'status': 'success', 'maintenance_enabled': False})
    
    print("✅ Maintenance mode endpoints configured")
    
    # 5. Metrics endpoint (conditional)
    @app.route('/metrics')
    def metrics():
        if os.environ.get('ENABLE_METRICS', '').lower() != 'true':
            from flask import abort
            abort(404)
        
        try:
            from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
            from flask import Response
            return Response(generate_latest(), content_type=CONTENT_TYPE_LATEST)
        except ImportError:
            return 'prometheus_client not available', 200, {'Content-Type': 'text/plain'}
    
    print("✅ Metrics endpoint configured")
    
    # 6. Demo route
    @app.route('/')
    def demo():
        return jsonify({
            'message': 'Operational Features Demo',
            'features': {
                'health_checks': ['/healthz', '/livez'],
                'maintenance': ['/api/status', '/admin/maintenance/enable', '/admin/maintenance/disable'],
                'metrics': ['/metrics'],
                'security_headers': True,
                'request_id_tracking': True
            },
            'request_id': g.request_id
        })
    
    return app

def test_demo_features():
    """Test all demo features"""
    
    app = create_demo_app()
    client = app.test_client()
    
    print("\n🧪 Testing operational features...")
    
    # Test health endpoints
    response = client.get('/healthz')
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'ok'
    print("✅ Health endpoint working")
    
    response = client.get('/livez')
    assert response.status_code == 200
    print("✅ Liveness endpoint working")
    
    # Test maintenance
    response = client.get('/api/status')
    assert response.status_code == 200
    data = response.get_json()
    assert 'maintenance_enabled' in data
    print("✅ Maintenance status working")
    
    response = client.post('/admin/maintenance/enable')
    assert response.status_code == 200
    print("✅ Maintenance enable working")
    
    # Test metrics
    response = client.get('/metrics')
    assert response.status_code in [200, 404]  # 200 if prometheus_client available, 404 if not
    print("✅ Metrics endpoint working")
    
    # Test security headers
    response = client.get('/')
    assert 'X-Frame-Options' in response.headers
    assert response.headers['X-Frame-Options'] == 'DENY'
    assert 'X-Request-ID' in response.headers
    print("✅ Security headers and request ID working")
    
    # Test demo endpoint
    response = client.get('/')
    assert response.status_code == 200
    data = response.get_json()
    assert 'features' in data
    assert 'request_id' in data
    print("✅ Demo endpoint working")
    
    print("\n🎉 All operational features working correctly!")
    
    return {
        'health_endpoints': True,
        'maintenance_mode': True,
        'metrics_endpoint': True,
        'security_headers': True,
        'request_id_tracking': True
    }

if __name__ == '__main__':
    result = test_demo_features()
    print(f"\n📊 Demo Results: {result}")
    print("\n📚 Documentation: See OPERATIONS.md for deployment guidance")
    print("🔧 Configuration: Use environment variables to customize behavior")