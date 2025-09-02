# tests/test_direct_integration.py
"""
Direct integration test bypassing problematic imports
"""

import os
import sys
sys.path.insert(0, '.')

from flask import Flask

def test_direct_integration():
    """Test operational features directly without going through package __init__"""
    
    # Create Flask app
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test-secret'
    
    with app.app_context():
        # Test individual modules directly
        
        # 1. Test health routes
        from Blitz_app.health_routes import health_bp
        app.register_blueprint(health_bp)
        print("✅ Health routes imported and registered")
        
        # 2. Test metrics routes  
        from Blitz_app.metrics_routes import metrics_bp
        app.register_blueprint(metrics_bp)
        print("✅ Metrics routes imported and registered")
        
        # 3. Test maintenance mode
        from Blitz_app.maintenance_mode import maintenance_bp
        app.register_blueprint(maintenance_bp)
        print("✅ Maintenance routes imported and registered")
        
        # 4. Test rate limiting config
        from Blitz_app.rate_limiting import RATE_LIMITS
        assert 'start' in RATE_LIMITS
        print("✅ Rate limiting configuration loaded")
        
        # 5. Test concurrency guard
        from Blitz_app.concurrency_guard import UserConcurrencyGuard
        guard = UserConcurrencyGuard()
        stats = guard.get_stats()
        assert 'active_users' in stats
        print("✅ Concurrency guard working")
        
        # Test endpoints
        client = app.test_client()
        
        # Test health
        response = client.get('/healthz')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'ok'
        print("✅ /healthz working")
        
        response = client.get('/livez')
        assert response.status_code == 200
        print("✅ /livez working")
        
        # Test maintenance status
        response = client.get('/api/status')
        assert response.status_code == 200
        data = response.get_json()
        assert 'maintenance_enabled' in data
        print("✅ Maintenance status working")
        
        # Test metrics (should be 404 when disabled)
        response = client.get('/metrics')
        assert response.status_code == 404
        print("✅ Metrics correctly disabled by default")
        
        print("🎉 All direct integration tests passed!")

if __name__ == '__main__':
    test_direct_integration()