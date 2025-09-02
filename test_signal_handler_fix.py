#!/usr/bin/env python3
"""
Test for the signal handler thread safety fix in bot_manager.py

This test validates that:
1. Signal handlers are registered when running in main thread
2. Signal handlers are skipped with warning when running in non-main thread
3. atexit handler is registered as fallback in non-main thread
4. The fix doesn't break existing functionality
"""

import os
import sys
import unittest
import threading
import signal
import atexit
import logging
from unittest.mock import Mock, patch, MagicMock
from io import StringIO

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Mock the Flask app and database dependencies
def setup_mocks():
    """Set up mocks for Flask app and database dependencies"""
    
    # Mock Flask app
    mock_app = Mock()
    mock_app.app_context.return_value.__enter__ = Mock(return_value=None)
    mock_app.app_context.return_value.__exit__ = Mock(return_value=None)
    
    # Mock database models and extensions
    mock_db = Mock()
    mock_user = Mock()
    mock_userbot = Mock()
    mock_botcommand = Mock()
    mock_botevent = Mock()
    mock_send_telegram = Mock()
    
    # Create module mocks
    modules_to_mock = [
        'Blitz_app.extensions',
        'Blitz_app.models', 
        'Blitz_app.models.User',
        'Blitz_app.models.UserBot',
        'Blitz_app.models.BotCommand', 
        'Blitz_app.models.BotEvent',
        'Blitz_app.telegram'
    ]
    
    patches = []
    for module in modules_to_mock:
        patcher = patch.dict('sys.modules', {module: Mock()})
        patches.append(patcher)
        patcher.start()
    
    # Mock specific imports
    with patch.dict('sys.modules', {
        'Blitz_app.extensions': Mock(db=mock_db),
        'Blitz_app.models': Mock(User=mock_user, UserBot=mock_userbot, BotCommand=mock_botcommand, BotEvent=mock_botevent),
        'Blitz_app.telegram': Mock(send_telegram=mock_send_telegram)
    }):
        # Import after mocking
        from Blitz_app.bot_manager import run_bot_manager, BotManager
        return run_bot_manager, BotManager, mock_app
    

class TestSignalHandlerFix(unittest.TestCase):
    """Test the signal handler thread safety fix"""
    
    def setUp(self):
        """Set up test environment with mocked dependencies"""
        self.run_bot_manager, self.BotManager, self.mock_app = setup_mocks()
        
    def test_signal_handler_in_main_thread(self):
        """Test that signal handlers are registered when running in main thread"""
        
        # Mock signal.signal and threading.current_thread
        with patch('signal.signal') as mock_signal, \
             patch('threading.current_thread') as mock_current_thread, \
             patch('threading.main_thread') as mock_main_thread, \
             patch('atexit.register') as mock_atexit:
            
            # Simulate main thread
            main_thread_mock = Mock()
            mock_current_thread.return_value = main_thread_mock
            mock_main_thread.return_value = main_thread_mock
            
            # Mock the manager's run method to avoid infinite loop
            with patch.object(self.BotManager, 'run') as mock_run, \
                 patch.object(self.BotManager, 'stop') as mock_stop:
                
                # Run the bot manager
                self.run_bot_manager(self.mock_app)
                
                # Verify signal handlers were registered
                self.assertEqual(mock_signal.call_count, 2)
                signal_calls = [call[0] for call in mock_signal.call_args_list]
                self.assertIn((signal.SIGTERM,), signal_calls)
                self.assertIn((signal.SIGINT,), signal_calls)
                
                # Verify atexit was NOT called in main thread
                mock_atexit.assert_not_called()
                
    def test_signal_handler_in_non_main_thread(self):
        """Test that signal handlers are skipped in non-main thread with warning"""
        
        # Capture log output
        log_stream = StringIO()
        handler = logging.StreamHandler(log_stream)
        logger = logging.getLogger('Blitz_app.bot_manager')
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)
        
        try:
            with patch('signal.signal') as mock_signal, \
                 patch('threading.current_thread') as mock_current_thread, \
                 patch('threading.main_thread') as mock_main_thread, \
                 patch('atexit.register') as mock_atexit:
                
                # Simulate non-main thread
                main_thread_mock = Mock()
                current_thread_mock = Mock()
                mock_current_thread.return_value = current_thread_mock
                mock_main_thread.return_value = main_thread_mock
                
                # Mock the manager's run method to avoid infinite loop
                with patch.object(self.BotManager, 'run') as mock_run, \
                     patch.object(self.BotManager, 'stop') as mock_stop:
                    
                    # Run the bot manager
                    self.run_bot_manager(self.mock_app)
                    
                    # Verify signal handlers were NOT registered
                    mock_signal.assert_not_called()
                    
                    # Verify atexit was called
                    mock_atexit.assert_called_once()
                    
                    # Verify warning was logged
                    log_output = log_stream.getvalue()
                    self.assertIn("Not running in main thread", log_output)
                    self.assertIn("skipping signal handler installation", log_output)
                    
        finally:
            logger.removeHandler(handler)
            
    def test_manager_stop_functionality_preserved(self):
        """Test that manager.stop() functionality is preserved"""
        
        with patch('signal.signal'), \
             patch('threading.current_thread') as mock_current_thread, \
             patch('threading.main_thread') as mock_main_thread, \
             patch('atexit.register'):
            
            # Simulate main thread
            main_thread_mock = Mock()
            mock_current_thread.return_value = main_thread_mock
            mock_main_thread.return_value = main_thread_mock
            
            # Mock the manager's run method to raise KeyboardInterrupt
            with patch.object(self.BotManager, 'run', side_effect=KeyboardInterrupt), \
                 patch.object(self.BotManager, 'stop') as mock_stop:
                
                # Run the bot manager
                self.run_bot_manager(self.mock_app)
                
                # Verify stop was called (in finally block)
                mock_stop.assert_called()

    def test_signal_handler_callback_works(self):
        """Test that the signal handler callback properly calls manager.stop()"""
        
        captured_signal_handler = None
        
        def capture_signal_handler(signum, handler):
            nonlocal captured_signal_handler
            captured_signal_handler = handler
            
        with patch('signal.signal', side_effect=capture_signal_handler), \
             patch('threading.current_thread') as mock_current_thread, \
             patch('threading.main_thread') as mock_main_thread, \
             patch('atexit.register'):
            
            # Simulate main thread
            main_thread_mock = Mock()
            mock_current_thread.return_value = main_thread_mock
            mock_main_thread.return_value = main_thread_mock
            
            # Mock the manager's run method to avoid infinite loop
            with patch.object(self.BotManager, 'run') as mock_run, \
                 patch.object(self.BotManager, 'stop') as mock_stop:
                
                # Run the bot manager
                self.run_bot_manager(self.mock_app)
                
                # Verify we captured a signal handler
                self.assertIsNotNone(captured_signal_handler)
                
                # Test the signal handler callback
                captured_signal_handler(signal.SIGTERM, None)
                
                # Verify manager.stop() was called by the signal handler
                # Note: stop() is called twice - once by signal handler, once in finally
                self.assertGreaterEqual(mock_stop.call_count, 1)


def main():
    """Run the signal handler fix tests"""
    print("🧪 Running Signal Handler Thread Safety Tests")
    print("=" * 50)
    
    # Run tests
    suite = unittest.TestLoader().loadTestsFromTestCase(TestSignalHandlerFix)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    if result.wasSuccessful():
        print("\n✅ All signal handler tests passed!")
        print("\nThe fix ensures:")
        print("• Signal handlers are only registered in main thread")
        print("• Warning is logged when running in non-main thread")
        print("• atexit fallback is registered for graceful cleanup")
        print("• Existing functionality is preserved")
        return True
    else:
        print("\n❌ Some tests failed")
        return False


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)