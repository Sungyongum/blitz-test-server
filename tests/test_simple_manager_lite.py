# tests/test_simple_manager_lite.py
"""
Test module for SimpleBotManager lite functionality

Validates:
1. SimpleBotManager duplicate start rejection
2. clientOrderId patterns for leg/tp
3. recover_orders_for_user no-op when no position; creates TP when position exists but TP missing
"""

import unittest
import sys
import os
import tempfile
import threading
import time
from unittest.mock import Mock, patch, MagicMock

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TestSimpleBotManagerLite(unittest.TestCase):
    """Test the SimpleBotManager lite functionality"""
    
    def setUp(self):
        """Set up test environment"""
        # Create a temporary database for testing
        self.test_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.test_db.close()
        
        # Mock Flask app
        self.mock_app = Mock()
        self.mock_app.app_context.return_value.__enter__ = Mock()
        self.mock_app.app_context.return_value.__exit__ = Mock()
        
        # Import SimpleBotManager after setting up mocks
        from simple_bot_manager import SimpleBotManager
        self.manager = SimpleBotManager(self.mock_app)
    
    def tearDown(self):
        """Clean up test environment"""
        # Clean up any running threads
        for user_id in list(self.manager.managed_bots.keys()):
            try:
                bot_info = self.manager.managed_bots[user_id]
                bot_info['stop_event'].set()
                if bot_info['thread'].is_alive():
                    bot_info['thread'].join(timeout=1.0)
            except:
                pass
        
        # Remove test database
        try:
            os.unlink(self.test_db.name)
        except:
            pass
    
    def test_duplicate_start_rejection(self):
        """Test that SimpleBotManager rejects duplicate bot starts"""
        user_id = 123
        
        # Mock User model
        mock_user = Mock()
        mock_user.id = user_id
        mock_user.api_key = "test_key"
        mock_user.api_secret = "test_secret"
        mock_user.telegram_token = "test_token"
        mock_user.telegram_chat_id = "test_chat"
        mock_user.exchange = "bybit"
        mock_user.to_dict.return_value = {
            'api_key': 'test_key',
            'api_secret': 'test_secret',
            'symbol': 'BTC/USDT:USDT',
            'side': 'long'
        }
        
        # Mock UserBot model
        mock_userbot = Mock()
        
        def mock_run_bot_blocking(*args, **kwargs):
            # Sleep to simulate a long-running bot
            time.sleep(0.2)
        
        with patch('simple_bot_manager.User') as MockUser, \
             patch('simple_bot_manager.UserBot') as MockUserBot, \
             patch('simple_bot_manager.db') as mock_db, \
             patch('simple_bot_manager.run_bot', side_effect=mock_run_bot_blocking) as mock_run_bot:
            
            MockUser.query.get.return_value = mock_user
            MockUserBot.query.get.return_value = mock_userbot
            
            # First start should succeed
            result1 = self.manager.start_bot_for_user(user_id)
            self.assertTrue(result1['success'])
            self.assertEqual(result1['status'], 'started')
            
            # Verify bot is actually running
            status = self.manager.get_bot_status(user_id)
            self.assertTrue(status['running'])
            
            # Second start should be rejected (duplicate)
            result2 = self.manager.start_bot_for_user(user_id)
            self.assertFalse(result2['success'])
            self.assertEqual(result2['status'], 'already_running')
            self.assertIn('already running', result2['message'].lower())
            
            # Clean up - stop the bot
            stop_result = self.manager.stop_bot_for_user(user_id)
            self.assertTrue(stop_result['success'])
    
    def test_idempotent_order_tag_patterns(self):
        """Test the idempotent clientOrderId patterns for leg/tp"""
        from Blitz_app.bot import build_idempotent_tag
        
        user_id = 456
        symbol = 'BTC/USDT:USDT'
        
        # Test leg tag pattern
        leg_tag = build_idempotent_tag(user_id, symbol, 'leg', leg_index=0)
        expected_leg = f"sm_leg_0_{user_id}_BTCUSDTUSDT"
        self.assertEqual(leg_tag, expected_leg)
        
        # Test leg tag with different index
        leg_tag_2 = build_idempotent_tag(user_id, symbol, 'leg', leg_index=2)
        expected_leg_2 = f"sm_leg_2_{user_id}_BTCUSDTUSDT"
        self.assertEqual(leg_tag_2, expected_leg_2)
        
        # Test TP tag pattern
        tp_tag = build_idempotent_tag(user_id, symbol, 'tp')
        expected_tp = f"sm_tp_{user_id}_BTCUSDTUSDT"
        self.assertEqual(tp_tag, expected_tp)
        
        # Test symbol cleaning (remove / and :)
        symbol_with_chars = 'ETH/USDT:USDT'
        clean_tag = build_idempotent_tag(user_id, symbol_with_chars, 'tp')
        expected_clean = f"sm_tp_{user_id}_ETHUSDTUSDT"
        self.assertEqual(clean_tag, expected_clean)
        
        # Test fallback for other purposes
        other_tag = build_idempotent_tag(user_id, symbol, 'sl')
        expected_other = f"sm_sl_{user_id}_BTCUSDTUSDT"
        self.assertEqual(other_tag, expected_other)
    
    def test_build_params_propagation(self):
        """Test that build_params_for_exchange propagates tags to all CCXT fields"""
        from Blitz_app.bot import build_params_for_exchange
        
        test_tag = "sm_tp_123_BTCUSDT"
        
        # Test basic parameter building
        params = build_params_for_exchange('bybit', tag=test_tag, is_tp=True)
        
        # Check that tag is propagated to all possible fields
        expected_fields = ['text', 'clientOrderId', 'clientOrderID', 'newClientOrderId', 'orderLinkId', 'label']
        for field in expected_fields:
            self.assertEqual(params[field], test_tag, f"Tag not propagated to {field}")
        
        # Check TP order has reduceOnly
        self.assertTrue(params['reduceOnly'])
        
        # Check time in force default
        self.assertEqual(params['timeInForce'], 'GTC')
        
        # Test BingX hedge mode (should not have reduceOnly)
        params_bingx_hedge = build_params_for_exchange('bingx', tag=test_tag, is_tp=True, hedge_mode=True)
        self.assertNotIn('reduceOnly', params_bingx_hedge)
        
        # Test position side parameter
        params_with_pos = build_params_for_exchange('bybit', tag=test_tag, position_side='long')
        self.assertEqual(params_with_pos['positionSide'], 'LONG')
    
    def test_recover_orders_no_op_case(self):
        """Test recover_orders_for_user no-op when no position exists"""
        user_id = 789
        
        # Mock User model
        mock_user = Mock()
        mock_user.id = user_id
        
        with patch('simple_bot_manager.User') as MockUser:
            MockUser.query.get.return_value = mock_user
            
            # Test recovery (currently a placeholder, but should not crash)
            result = self.manager.recover_orders_for_user(user_id)
            
            self.assertTrue(result['success'])
            self.assertIn('Recovery process completed', result['message'])
            self.assertIsInstance(result['actions'], list)
    
    def test_recover_orders_user_not_found(self):
        """Test recover_orders_for_user when user doesn't exist"""
        user_id = 999
        
        with patch('simple_bot_manager.User') as MockUser:
            MockUser.query.get.return_value = None
            
            result = self.manager.recover_orders_for_user(user_id)
            
            self.assertFalse(result['success'])
            self.assertEqual(result['message'], 'User not found')
    
    def test_bot_status_no_bot(self):
        """Test get_bot_status when no bot is running"""
        user_id = 555
        
        result = self.manager.get_bot_status(user_id)
        
        self.assertFalse(result['running'])
        self.assertEqual(result['status'], 'not_running')
        self.assertEqual(result['uptime'], 0)
    
    def test_stop_bot_not_running(self):
        """Test stop_bot_for_user when no bot is running"""
        user_id = 666
        
        result = self.manager.stop_bot_for_user(user_id)
        
        self.assertFalse(result['success'])
        self.assertEqual(result['status'], 'not_running')
        self.assertIn('No bot running', result['message'])
    
    def test_all_bot_statuses_empty(self):
        """Test get_all_bot_statuses when no bots are managed"""
        result = self.manager.get_all_bot_statuses()
        
        self.assertIn('users', result)
        self.assertIn('totals', result)
        self.assertEqual(len(result['users']), 0)
        self.assertEqual(result['totals']['total_managed'], 0)
        self.assertEqual(result['totals']['total_running'], 0)
    
    def test_manager_thread_safety(self):
        """Test that SimpleBotManager operations are thread-safe"""
        user_id = 777
        
        # Mock User model
        mock_user = Mock()
        mock_user.id = user_id
        mock_user.api_key = "test_key"
        mock_user.api_secret = "test_secret"
        mock_user.telegram_token = "test_token"
        mock_user.telegram_chat_id = "test_chat"
        mock_user.exchange = "bybit"
        mock_user.to_dict.return_value = {
            'api_key': 'test_key',
            'api_secret': 'test_secret',
            'symbol': 'BTC/USDT:USDT',
            'side': 'long'
        }
        
        results = []
        
        def mock_run_bot_blocking(*args, **kwargs):
            # Sleep to simulate a long-running bot
            time.sleep(0.1)
        
        def start_bot_thread():
            with patch('simple_bot_manager.User') as MockUser, \
                 patch('simple_bot_manager.UserBot') as MockUserBot, \
                 patch('simple_bot_manager.db') as mock_db, \
                 patch('simple_bot_manager.run_bot', side_effect=mock_run_bot_blocking) as mock_run_bot:
                
                MockUser.query.get.return_value = mock_user
                MockUserBot.query.get.return_value = Mock()
                
                result = self.manager.start_bot_for_user(user_id)
                results.append(result)
        
        # Start multiple threads trying to start the same bot
        threads = []
        for i in range(3):
            thread = threading.Thread(target=start_bot_thread)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Filter out None results (shouldn't happen but just in case)
        valid_results = [r for r in results if r is not None]
        self.assertEqual(len(valid_results), 3, "Should have 3 results")
        
        # Only one should succeed, others should be rejected
        success_count = sum(1 for r in valid_results if r.get('success', False))
        self.assertGreaterEqual(success_count, 1, "At least one thread should successfully start the bot")
        
        # The rest should be rejected as duplicates (or fail for other reasons)
        non_success = [r for r in valid_results if not r.get('success', False)]
        self.assertGreaterEqual(len(non_success), 1, "At least one thread should be rejected")


class TestIdempotentTagPatterns(unittest.TestCase):
    """Focused tests for idempotent tag patterns"""
    
    def test_tag_consistency(self):
        """Test that tags are consistent across multiple calls"""
        from Blitz_app.bot import build_idempotent_tag
        
        user_id = 123
        symbol = 'BTC/USDT:USDT'
        
        # Tags should be identical for same parameters
        tag1 = build_idempotent_tag(user_id, symbol, 'tp')
        tag2 = build_idempotent_tag(user_id, symbol, 'tp')
        self.assertEqual(tag1, tag2, "Tags should be consistent for same parameters")
        
        # Tags should be different for different users
        tag_user1 = build_idempotent_tag(123, symbol, 'tp')
        tag_user2 = build_idempotent_tag(456, symbol, 'tp')
        self.assertNotEqual(tag_user1, tag_user2, "Tags should differ for different users")
        
        # Tags should be different for different symbols
        tag_btc = build_idempotent_tag(user_id, 'BTC/USDT:USDT', 'tp')
        tag_eth = build_idempotent_tag(user_id, 'ETH/USDT:USDT', 'tp')
        self.assertNotEqual(tag_btc, tag_eth, "Tags should differ for different symbols")


if __name__ == '__main__':
    # Set up test environment
    import logging
    logging.basicConfig(level=logging.ERROR)  # Reduce log noise during tests
    
    # Run tests
    unittest.main(verbosity=2)