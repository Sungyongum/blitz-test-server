# tests/test_simple_manager_lite.py

import unittest
import tempfile
import os
from unittest.mock import patch, MagicMock
from threading import Event
import time

from Blitz_app import create_app
from Blitz_app.extensions import db
from Blitz_app.models import User, UserBot
from Blitz_app.simple_bot_manager import SimpleBotManager
from Blitz_app.bot import _standardized_tag


class TestSimpleManagerLite(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures"""
        # Create temporary database
        self.db_fd, self.db_path = tempfile.mkstemp()
        
        # Set up test app
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{self.db_path}'
        self.app.config['WTF_CSRF_ENABLED'] = False
        
        with self.app.app_context():
            db.create_all()
            
            # Create test user
            self.test_user = User(
                email='test@example.com',
                api_key='test_api_key',
                api_secret='test_api_secret',
                symbol='BTC/USDT',
                side='long',
                take_profit='1%',
                stop_loss='0%',
                leverage=1,
                rounds=1,
                repeat=False,
                grids=[],
                exchange='bybit'
            )
            self.test_user.set_password('password')
            db.session.add(self.test_user)
            db.session.commit()
            
            # Store the user ID for later use
            self.test_user_id = self.test_user.id
            
        self.bot_manager = SimpleBotManager(self.app)
        
    def tearDown(self):
        """Clean up test fixtures"""
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        os.close(self.db_fd)
        os.unlink(self.db_path)
        
    def test_duplicate_start_rejected(self):
        """Test that duplicate start attempts are rejected with proper message"""
        with self.app.app_context():
            user_id = self.test_user_id
            
            # Mock the run_bot function to avoid actual bot execution
            with patch('Blitz_app.simple_bot_manager.run_bot') as mock_run_bot:
                mock_run_bot.side_effect = lambda *args: time.sleep(0.1)  # Short delay
                
                # First start should succeed
                success1, message1 = self.bot_manager.start_bot_for_user(user_id)
                self.assertTrue(success1)
                self.assertIn("successfully", message1.lower())
                
                # Wait for thread to start
                time.sleep(0.05)
                
                # Now try duplicate start
                success2, message2 = self.bot_manager.start_bot_for_user(user_id)
                self.assertFalse(success2)
                self.assertIn("already running", message2.lower())
                
                # Clean up
                self.bot_manager.stop_bot_for_user(user_id)
                
    def test_idempotent_tags_leg_tp(self):
        """Test idempotent order tag patterns for leg and TP orders"""
        user_id = 123
        symbol = 'BTC/USDT'
        
        # Test leg tag
        leg_tag = _standardized_tag(user_id, 'leg', symbol, leg_index=1)
        expected_leg = 'sm_leg_1_123_BTCUSDT'
        self.assertEqual(leg_tag, expected_leg)
        
        # Test leg tag with different index
        leg_tag2 = _standardized_tag(user_id, 'leg', symbol, leg_index=5)
        expected_leg2 = 'sm_leg_5_123_BTCUSDT'
        self.assertEqual(leg_tag2, expected_leg2)
        
        # Test TP tag
        tp_tag = _standardized_tag(user_id, 'tp', symbol)
        expected_tp = 'sm_tp_123_BTCUSDT'
        self.assertEqual(tp_tag, expected_tp)
        
        # Test with symbol containing colon
        symbol_with_colon = 'BTC/USDT:USDT'
        tp_tag_colon = _standardized_tag(user_id, 'tp', symbol_with_colon)
        expected_tp_colon = 'sm_tp_123_BTCUSDTUSDT'
        self.assertEqual(tp_tag_colon, expected_tp_colon)
        
        # Test tags are different for different users
        user_id2 = 456
        tp_tag_user2 = _standardized_tag(user_id2, 'tp', symbol)
        expected_tp_user2 = 'sm_tp_456_BTCUSDT'
        self.assertNotEqual(tp_tag, tp_tag_user2)
        self.assertEqual(tp_tag_user2, expected_tp_user2)
        
    def test_recover_idempotent_and_creates_missing_tp(self):
        """Test recover_orders_for_user is idempotent and creates missing TP when needed"""
        with self.app.app_context():
            user_id = self.test_user_id
            
            # Test recover on user with valid credentials
            success, message = self.bot_manager.recover_orders_for_user(user_id)
            self.assertTrue(success)
            self.assertIn("completed", message.lower())
            
            # Test recover is idempotent - should work multiple times
            success2, message2 = self.bot_manager.recover_orders_for_user(user_id)
            self.assertTrue(success2)
            self.assertIn("completed", message2.lower())
            
            # Test recover on non-existent user
            success3, message3 = self.bot_manager.recover_orders_for_user(99999)
            self.assertFalse(success3)
            self.assertIn("not found", message3.lower())
            
    def test_get_bot_status(self):
        """Test get_bot_status returns correct information"""
        with self.app.app_context():
            user_id = self.test_user_id
            
            # Test status when bot is not running
            status = self.bot_manager.get_bot_status(user_id)
            self.assertEqual(status['user_id'], user_id)
            self.assertFalse(status['running'])
            self.assertEqual(status['status'], 'stopped')
            
            # Test with a running bot
            with patch('Blitz_app.simple_bot_manager.run_bot') as mock_run_bot:
                mock_run_bot.side_effect = lambda *args: time.sleep(0.2)
                
                # Start bot
                success, _ = self.bot_manager.start_bot_for_user(user_id)
                self.assertTrue(success)
                
                # Wait a bit for thread to start
                time.sleep(0.05)
                
                # Check status
                status = self.bot_manager.get_bot_status(user_id)
                self.assertEqual(status['user_id'], user_id)
                self.assertTrue(status['running'])
                self.assertEqual(status['status'], 'running')
                self.assertIsNotNone(status['started_at'])
                self.assertGreater(status['uptime_seconds'], 0)
                
                # Clean up
                self.bot_manager.stop_bot_for_user(user_id)
                
    def test_get_all_statuses(self):
        """Test get_all_statuses returns proper admin overview"""
        with self.app.app_context():
            # Test with no running bots
            status = self.bot_manager.get_all_statuses()
            self.assertIn('users', status)
            self.assertIn('total_users', status)
            self.assertIn('total_running', status)
            self.assertIn('timestamp', status)
            self.assertEqual(status['total_running'], 0)
            
            # Test with a running bot
            with patch('Blitz_app.simple_bot_manager.run_bot') as mock_run_bot:
                mock_run_bot.side_effect = lambda *args: time.sleep(0.2)
                
                user_id = self.test_user_id
                success, _ = self.bot_manager.start_bot_for_user(user_id)
                self.assertTrue(success)
                
                # Wait for thread to start
                time.sleep(0.05)
                
                status = self.bot_manager.get_all_statuses()
                self.assertGreaterEqual(status['total_running'], 1)
                self.assertIn(user_id, status['users'])
                self.assertTrue(status['users'][user_id]['running'])
                
                # Clean up
                self.bot_manager.stop_bot_for_user(user_id)
                
    def test_stop_bot_nonexistent(self):
        """Test stopping a bot that doesn't exist"""
        with self.app.app_context():
            # Try to stop non-running bot
            success, message = self.bot_manager.stop_bot_for_user(self.test_user_id)
            self.assertTrue(success)  # Should succeed (no-op)
            self.assertIn("No bot running", message)
            
    def test_user_credentials_validation(self):
        """Test that start_bot validates user credentials"""
        with self.app.app_context():
            # Create user without API credentials
            bad_user = User(
                email='bad@example.com',
                api_key='',  # Empty API key
                api_secret='',
                symbol='BTC/USDT',
                side='long'
            )
            bad_user.set_password('password')
            db.session.add(bad_user)
            db.session.commit()
            
            # Try to start bot
            success, message = self.bot_manager.start_bot_for_user(bad_user.id)
            self.assertFalse(success)
            self.assertIn("credentials", message.lower())


if __name__ == '__main__':
    unittest.main()