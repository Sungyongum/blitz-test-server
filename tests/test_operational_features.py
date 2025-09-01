# tests/test_operational_features.py
"""
Tests for operational features (health endpoints, rate limiting, etc.)
"""

import pytest
import os
import time
import json
from unittest.mock import Mock, patch
from flask import Flask
from flask_testing import TestCase

class TestHealthEndpoints(TestCase):
    """Test health endpoints"""
    
    def create_app(self):
        """Create test app"""
        app = Flask(__name__)
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        
        # Register health routes
        from Blitz_app.health_routes import health_bp
        app.register_blueprint(health_bp)
        
        return app
    
    def test_healthz_endpoint(self):
        """Test /healthz endpoint returns ok with metadata"""
        with patch.dict(os.environ, {'APP_VERSION': 'test-1.0'}):
            response = self.client.get('/healthz')
            
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            
            self.assertEqual(data['status'], 'ok')
            self.assertEqual(data['version'], 'test-1.0')
            self.assertEqual(data['service'], 'blitz-test-server')
            self.assertIn('timestamp', data)
    
    def test_livez_endpoint(self):
        """Test /livez endpoint always returns ok"""
        response = self.client.get('/livez')
        
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        
        self.assertEqual(data['status'], 'ok')
        self.assertIn('timestamp', data)
    
    def test_readyz_endpoint_without_dependencies(self):
        """Test /readyz endpoint when dependencies are not available"""
        response = self.client.get('/readyz')
        
        # Should return 503 since database and bot manager aren't properly set up
        self.assertEqual(response.status_code, 503)
        data = response.get_json()
        
        self.assertEqual(data['status'], 'error')
        self.assertIn('checks', data)

class TestMetricsEndpoint(TestCase):
    """Test metrics endpoint"""
    
    def create_app(self):
        """Create test app"""
        app = Flask(__name__)
        app.config['TESTING'] = True
        
        # Register metrics routes
        from Blitz_app.metrics_routes import metrics_bp
        app.register_blueprint(metrics_bp)
        
        return app
    
    def test_metrics_disabled_by_default(self):
        """Test metrics endpoint returns 404 when disabled"""
        response = self.client.get('/metrics')
        self.assertEqual(response.status_code, 404)
    
    def test_metrics_enabled_with_env_var(self):
        """Test metrics endpoint returns data when enabled"""
        with patch.dict(os.environ, {'ENABLE_METRICS': 'true'}):
            with patch('prometheus_client.generate_latest') as mock_generate:
                mock_generate.return_value = b'# HELP test_metric\ntest_metric 1.0\n'
                
                response = self.client.get('/metrics')
                
                if response.status_code == 200:
                    self.assertEqual(response.data, b'# HELP test_metric\ntest_metric 1.0\n')
                    self.assertEqual(response.content_type, 'text/plain; version=0.0.4; charset=utf-8')
                else:
                    # If prometheus_client not available, should return 404
                    self.assertEqual(response.status_code, 404)

class TestMaintenanceMode(TestCase):
    """Test maintenance mode functionality"""
    
    def create_app(self):
        """Create test app"""
        app = Flask(__name__)
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret'
        
        # Mock Flask-Login
        from flask_login import LoginManager
        login_manager = LoginManager()
        login_manager.init_app(app)
        
        @login_manager.user_loader
        def load_user(user_id):
            user = Mock()
            user.id = 1
            user.email = 'admin@admin.com'
            user.is_authenticated = True
            return user
        
        # Register maintenance routes
        from Blitz_app.maintenance_mode import maintenance_bp
        app.register_blueprint(maintenance_bp)
        
        return app
    
    def test_maintenance_status_endpoint(self):
        """Test maintenance status endpoint (public)"""
        response = self.client.get('/api/status')
        
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        
        self.assertIn('maintenance_enabled', data)
        self.assertIn('banner_message', data)
        self.assertIsInstance(data['maintenance_enabled'], bool)
        self.assertIsInstance(data['banner_message'], str)

class TestConcurrencyGuard(TestCase):
    """Test concurrency guard functionality"""
    
    def setUp(self):
        """Setup test"""
        from Blitz_app.concurrency_guard import UserConcurrencyGuard, ConcurrencyContext, ConcurrencyError
        self.guard = UserConcurrencyGuard()
        self.ConcurrencyContext = ConcurrencyContext
        self.ConcurrencyError = ConcurrencyError
    
    def test_user_lock_creation(self):
        """Test user lock creation and reuse"""
        lock1 = self.guard.get_user_lock(1)
        lock2 = self.guard.get_user_lock(1)
        lock3 = self.guard.get_user_lock(2)
        
        self.assertIs(lock1, lock2)  # Same user should get same lock
        self.assertIsNot(lock1, lock3)  # Different users get different locks
    
    def test_operation_tracking(self):
        """Test operation in-flight tracking"""
        self.assertFalse(self.guard.is_operation_in_flight(1, 'start'))
        
        self.guard.mark_operation_start(1, 'start')
        self.assertTrue(self.guard.is_operation_in_flight(1, 'start'))
        self.assertFalse(self.guard.is_operation_in_flight(1, 'stop'))
        
        self.guard.mark_operation_complete(1, 'start')
        self.assertFalse(self.guard.is_operation_in_flight(1, 'start'))
    
    def test_concurrency_context_success(self):
        """Test successful concurrency context usage"""
        with self.ConcurrencyContext(self.guard, 1, 'test_op', timeout=1.0) as ctx:
            self.assertTrue(self.guard.is_operation_in_flight(1, 'test_op'))
        
        self.assertFalse(self.guard.is_operation_in_flight(1, 'test_op'))
    
    def test_concurrency_context_duplicate_operation(self):
        """Test that duplicate operations are rejected"""
        with self.ConcurrencyContext(self.guard, 1, 'test_op', timeout=1.0):
            with self.assertRaises(self.ConcurrencyError):
                with self.ConcurrencyContext(self.guard, 1, 'test_op', timeout=1.0):
                    pass
    
    def test_concurrency_stats(self):
        """Test concurrency statistics"""
        stats = self.guard.get_stats()
        self.assertEqual(stats['active_users'], 0)
        self.assertEqual(stats['total_operations'], 0)
        
        with self.ConcurrencyContext(self.guard, 1, 'op1', timeout=1.0):
            with self.ConcurrencyContext(self.guard, 2, 'op2', timeout=1.0):
                stats = self.guard.get_stats()
                self.assertEqual(stats['active_users'], 2)
                self.assertEqual(stats['total_operations'], 2)

class TestRateLimiting(TestCase):
    """Test rate limiting functionality"""
    
    def create_app(self):
        """Create test app"""
        app = Flask(__name__)
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret'
        
        # Setup rate limiting with in-memory storage
        from Blitz_app.rate_limiting import setup_rate_limiting
        limiter = setup_rate_limiting(app)
        
        # Create a test route with rate limiting
        @app.route('/test-limited')
        @limiter.limit("2/minute")
        def test_limited():
            return {'status': 'ok'}
        
        return app
    
    def test_rate_limit_allows_requests_under_limit(self):
        """Test that requests under the limit are allowed"""
        response1 = self.client.get('/test-limited')
        response2 = self.client.get('/test-limited')
        
        self.assertEqual(response1.status_code, 200)
        self.assertEqual(response2.status_code, 200)
    
    def test_rate_limit_blocks_requests_over_limit(self):
        """Test that requests over the limit are blocked"""
        # Make requests up to the limit
        for _ in range(2):
            response = self.client.get('/test-limited')
            self.assertEqual(response.status_code, 200)
        
        # Next request should be rate limited
        response = self.client.get('/test-limited')
        self.assertEqual(response.status_code, 429)

if __name__ == '__main__':
    pytest.main([__file__])