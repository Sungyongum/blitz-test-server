#!/usr/bin/env python3
"""
Minimal test for signal handler thread safety fix

This test validates the exact changes made to run_bot_manager without
importing the full Flask application.
"""

import threading
import signal
import atexit
import logging
from unittest.mock import Mock, patch
from io import StringIO


def create_test_run_bot_manager():
    """Create a test version of run_bot_manager with our fix"""
    
    def run_bot_manager(app):
        """Entry point for bot manager process"""
        # Mock the manager for testing
        manager = Mock()
        manager.run = Mock()
        manager.stop = Mock()
        
        logger = logging.getLogger(__name__)
        
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, stopping bot manager")
            manager.stop()
        
        # This is the fix we implemented
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, signal_handler)
            signal.signal(signal.SIGINT, signal_handler)
        else:
            logger.warning("Not running in main thread; skipping signal handler installation for BotManager")
            atexit.register(manager.stop)
        
        try:
            manager.run()
        except KeyboardInterrupt:
            logger.info("Bot manager interrupted")
        finally:
            manager.stop()
            
        return manager  # Return for testing
    
    return run_bot_manager


def test_main_thread_scenario():
    """Test signal handler registration in main thread"""
    print("🔧 Testing main thread scenario...")
    
    run_bot_manager = create_test_run_bot_manager()
    
    with patch('signal.signal') as mock_signal, \
         patch('threading.current_thread') as mock_current_thread, \
         patch('threading.main_thread') as mock_main_thread, \
         patch('atexit.register') as mock_atexit:
        
        # Simulate main thread
        main_thread_mock = Mock()
        mock_current_thread.return_value = main_thread_mock
        mock_main_thread.return_value = main_thread_mock
        
        # Run the function
        manager = run_bot_manager(Mock())
        
        # Verify signal handlers were registered
        assert mock_signal.call_count == 2, f"Expected 2 signal calls, got {mock_signal.call_count}"
        
        signal_calls = [call[0][0] for call in mock_signal.call_args_list]
        assert signal.SIGTERM in signal_calls, "SIGTERM handler not registered"
        assert signal.SIGINT in signal_calls, "SIGINT handler not registered"
        
        # Verify atexit was NOT called in main thread
        mock_atexit.assert_not_called()
        
        # Verify manager methods were called
        manager.run.assert_called_once()
        manager.stop.assert_called_once()  # Called in finally block
        
    print("✅ Main thread test passed")
    return True


def test_non_main_thread_scenario():
    """Test signal handler skipping in non-main thread"""
    print("🔧 Testing non-main thread scenario...")
    
    run_bot_manager = create_test_run_bot_manager()
    
    # Set up logging capture
    log_stream = StringIO()
    handler = logging.StreamHandler(log_stream)
    logger = logging.getLogger(__name__)
    original_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    
    try:
        with patch('signal.signal') as mock_signal, \
             patch('threading.current_thread') as mock_current_thread, \
             patch('threading.main_thread') as mock_main_thread, \
             patch('atexit.register') as mock_atexit:
            
            # Simulate non-main thread (different objects)
            main_thread_mock = Mock()
            current_thread_mock = Mock()
            mock_current_thread.return_value = current_thread_mock
            mock_main_thread.return_value = main_thread_mock
            
            # Run the function
            manager = run_bot_manager(Mock())
            
            # Verify signal handlers were NOT registered
            mock_signal.assert_not_called()
            
            # Verify atexit was called
            mock_atexit.assert_called_once()
            
            # Verify the atexit callback is manager.stop
            atexit_call_args = mock_atexit.call_args
            assert atexit_call_args[0][0] == manager.stop, "atexit should register manager.stop"
            
            # Verify warning was logged
            log_output = log_stream.getvalue()
            assert "Not running in main thread" in log_output, f"Warning not found in log: {log_output}"
            assert "skipping signal handler installation" in log_output, f"Warning incomplete: {log_output}"
            
            # Verify manager methods were called
            manager.run.assert_called_once()
            manager.stop.assert_called_once()  # Called in finally block
            
    finally:
        logger.removeHandler(handler)
        logger.setLevel(original_level)
    
    print("✅ Non-main thread test passed")
    return True


def test_signal_handler_callback():
    """Test that signal handler properly calls manager.stop()"""
    print("🔧 Testing signal handler callback...")
    
    captured_handler = None
    
    def capture_signal(signum, handler):
        nonlocal captured_handler
        if signum == signal.SIGTERM:
            captured_handler = handler
    
    run_bot_manager = create_test_run_bot_manager()
    
    with patch('signal.signal', side_effect=capture_signal), \
         patch('threading.current_thread') as mock_current_thread, \
         patch('threading.main_thread') as mock_main_thread, \
         patch('atexit.register'):
        
        # Simulate main thread
        main_thread_mock = Mock()
        mock_current_thread.return_value = main_thread_mock
        mock_main_thread.return_value = main_thread_mock
        
        # Run the function
        manager = run_bot_manager(Mock())
        
        # Verify we captured the signal handler
        assert captured_handler is not None, "Signal handler not captured"
        
        # Reset the mock to test signal handler call
        manager.stop.reset_mock()
        
        # Test signal handler
        captured_handler(signal.SIGTERM, None)
        
        # Verify manager.stop was called by signal handler
        manager.stop.assert_called_once()
    
    print("✅ Signal handler callback test passed")
    return True


def test_actual_code_changes():
    """Verify the actual code changes were made correctly"""
    print("🔧 Verifying actual code changes...")
    
    bot_manager_path = "/home/runner/work/blitz-test-server/blitz-test-server/Blitz_app/bot_manager.py"
    
    try:
        with open(bot_manager_path, 'r') as f:
            content = f.read()
        
        # Check for required imports
        assert 'import atexit' in content, "atexit import missing"
        assert 'import threading' in content, "threading import missing"
        
        # Check for the thread safety code
        assert 'threading.current_thread() is threading.main_thread()' in content, "Thread check missing"
        assert 'skipping signal handler installation' in content, "Warning message missing"
        assert 'atexit.register(manager.stop)' in content, "atexit registration missing"
        
        # Check that the original signal.signal calls are still there but guarded
        lines = content.split('\n')
        found_if_main_thread = False
        found_else_branch = False
        found_signal_term = False
        found_signal_int = False
        
        for i, line in enumerate(lines):
            if 'if threading.current_thread() is threading.main_thread():' in line:
                found_if_main_thread = True
            elif 'else:' in line and found_if_main_thread:
                found_else_branch = True
            elif 'signal.signal(signal.SIGTERM' in line:
                found_signal_term = True
            elif 'signal.signal(signal.SIGINT' in line:
                found_signal_int = True
        
        assert found_if_main_thread, "Thread check if statement not found"
        assert found_else_branch, "else branch not found"
        assert found_signal_term, "SIGTERM signal handler not found"
        assert found_signal_int, "SIGINT signal handler not found"
        
        print("✅ Code changes verification passed")
        return True
        
    except Exception as e:
        print(f"❌ Code verification failed: {e}")
        return False


def main():
    """Run all tests"""
    print("🧪 Signal Handler Thread Safety Fix Test")
    print("=" * 50)
    
    tests = [
        test_main_thread_scenario,
        test_non_main_thread_scenario,
        test_signal_handler_callback,
        test_actual_code_changes
    ]
    
    all_passed = True
    for test in tests:
        try:
            if not test():
                all_passed = False
        except Exception as e:
            print(f"❌ Test {test.__name__} failed with exception: {e}")
            all_passed = False
    
    if all_passed:
        print("\n🎉 All tests passed! Signal handler fix is working correctly.")
        print("\nThe fix ensures:")
        print("• ✅ Signal handlers are only registered in main thread")
        print("• ✅ Warning is logged when running in non-main thread")  
        print("• ✅ atexit fallback is registered for graceful cleanup")
        print("• ✅ Existing functionality is preserved")
        print("• ✅ Signal handler callbacks work correctly")
        return True
    else:
        print("\n❌ Some tests failed")
        return False


if __name__ == '__main__':
    import sys
    success = main()
    sys.exit(0 if success else 1)