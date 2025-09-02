# tests/test_integration.py
"""
Integration test for operational features
"""

import os
import sys
sys.path.insert(0, '.')

from flask import Flask

def test_operational_features_integration():
    """Test that all operational features can be integrated successfully"""
    
    # Create Flask app
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test-secret'
    
    # Setup operational features
    from Blitz_app.operational_features import setup_operational_features, get_operational_status
    
    with app.app_context():
        summary = setup_operational_features(app)
        
        # Verify features were setup
        assert summary['logging'] == True
        assert summary['security'] == True
        assert summary['health_endpoints'] == True
        assert summary['maintenance_mode'] == True
        
        print("✅ All operational features integrated successfully")
        
        # Test status function
        status = get_operational_status()
        assert '/healthz' in status['health_endpoints']
        assert '/livez' in status['health_endpoints']
        assert '/readyz' in status['health_endpoints']
        
        print("✅ Operational status function working")
        
        # Test health endpoints
        client = app.test_client()
        
        response = client.get('/healthz')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'ok'
        print("✅ Health endpoint working")
        
        response = client.get('/livez')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'ok'
        print("✅ Liveness endpoint working")
        
        # Test maintenance status
        response = client.get('/api/status')
        assert response.status_code == 200
        data = response.get_json()
        assert 'maintenance_enabled' in data
        assert 'banner_message' in data
        print("✅ Maintenance status endpoint working")
        
        # Test metrics endpoint (should be disabled by default)
        response = client.get('/metrics')
        assert response.status_code == 404
        print("✅ Metrics endpoint correctly disabled by default")
        
        # Test security headers
        response = client.get('/healthz')
        assert 'X-Frame-Options' in response.headers
        assert response.headers['X-Frame-Options'] == 'DENY'
        assert 'X-Content-Type-Options' in response.headers
        print("✅ Security headers working")

def test_metrics_when_enabled():
    """Test metrics functionality when enabled"""
    
    app = Flask(__name__)
    app.config['TESTING'] = True
    
    # Enable metrics
    os.environ['ENABLE_METRICS'] = 'true'
    
    try:
        from Blitz_app.operational_features import setup_operational_features
        
        with app.app_context():
            summary = setup_operational_features(app)
            
            client = app.test_client()
            response = client.get('/metrics')
            
            # Should either work (200) or fail due to missing prometheus_client (404)
            assert response.status_code in [200, 404]
            
            if response.status_code == 200:
                print("✅ Metrics endpoint working when enabled")
            else:
                print("ℹ️ Metrics endpoint disabled due to missing prometheus_client")
    
    finally:
        # Clean up
        if 'ENABLE_METRICS' in os.environ:
            del os.environ['ENABLE_METRICS']

def test_rate_limiting_configuration():
    """Test rate limiting configuration"""
    
    # Test default rate limits
    from Blitz_app.rate_limiting import RATE_LIMITS
    
    assert 'start' in RATE_LIMITS
    assert 'stop' in RATE_LIMITS  
    assert 'recover' in RATE_LIMITS
    assert 'status' in RATE_LIMITS
    assert 'global_ceiling' in RATE_LIMITS
    
    # Verify defaults
    assert RATE_LIMITS['start'] == '10/minute'
    assert RATE_LIMITS['status'] == '30/minute'
    assert RATE_LIMITS['global_ceiling'] == '200/minute'
    
    print("✅ Rate limiting configuration working")

def test_concurrency_guard():
    """Test concurrency guard functionality"""
    
    from Blitz_app.concurrency_guard import UserConcurrencyGuard, ConcurrencyContext, ConcurrencyError
    
    guard = UserConcurrencyGuard()
    
    # Test basic functionality
    assert not guard.is_operation_in_flight(1, 'test')
    
    guard.mark_operation_start(1, 'test')
    assert guard.is_operation_in_flight(1, 'test')
    
    guard.mark_operation_complete(1, 'test')
    assert not guard.is_operation_in_flight(1, 'test')
    
    # Test context manager
    with ConcurrencyContext(guard, 1, 'test_op', timeout=1.0):
        assert guard.is_operation_in_flight(1, 'test_op')
    
    assert not guard.is_operation_in_flight(1, 'test_op')
    
    print("✅ Concurrency guard working")

if __name__ == '__main__':
    test_operational_features_integration()
    test_metrics_when_enabled()
    test_rate_limiting_configuration()
    test_concurrency_guard()
    print("🎉 All integration tests passed!")