#!/usr/bin/env python3
"""
Demonstration of the signal handler thread safety fix

This script shows the difference between before and after the fix,
demonstrating that the fix prevents the "signal only works in main thread" error.
"""

import threading
import signal
import atexit
import logging
import time
from unittest.mock import Mock

# Set up logging to see the warning messages
logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def old_run_bot_manager_broken(app):
    """The old broken version that would fail in non-main thread"""
    manager = Mock()
    
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, stopping bot manager")
        manager.stop()
    
    # This would fail with "signal only works in main thread" if called from non-main thread
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    print("✅ Old version: Signal handlers registered (only works in main thread)")
    return manager


def new_run_bot_manager_fixed(app):
    """The new fixed version that works in both main and non-main threads"""
    manager = Mock()
    
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, stopping bot manager")
        manager.stop()
    
    # Our fix: check if we're in main thread before registering signal handlers
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        print("✅ New version: Signal handlers registered (main thread)")
    else:
        logger.warning("Not running in main thread; skipping signal handler installation for BotManager")
        atexit.register(manager.stop)
        print("✅ New version: Signal handlers skipped, atexit fallback registered (non-main thread)")
    
    return manager


def test_in_main_thread():
    """Test the fix when running in main thread"""
    print("\n🔧 Testing in main thread:")
    print("Current thread:", threading.current_thread().name)
    print("Is main thread:", threading.current_thread() is threading.main_thread())
    
    # Both old and new versions should work in main thread
    print("\n📊 Old version:")
    old_manager = old_run_bot_manager_broken(Mock())
    
    print("\n📊 New version:")
    new_manager = new_run_bot_manager_fixed(Mock())


def test_in_background_thread():
    """Test the fix when running in background thread"""
    print("\n🔧 Testing in background thread:")
    
    def thread_function():
        print("Current thread:", threading.current_thread().name)
        print("Is main thread:", threading.current_thread() is threading.main_thread())
        
        # Old version would fail here with "signal only works in main thread"
        print("\n📊 Old version would fail here:")
        try:
            old_manager = old_run_bot_manager_broken(Mock())
            print("❌ This should have failed!")
        except ValueError as e:
            print(f"✅ Expected error: {e}")
        
        # New version works fine
        print("\n📊 New version:")
        new_manager = new_run_bot_manager_fixed(Mock())
    
    # Create and run background thread
    thread = threading.Thread(target=thread_function, name="BackgroundThread")
    thread.start()
    thread.join()


def main():
    """Demonstrate the signal handler thread safety fix"""
    print("🧪 Signal Handler Thread Safety Fix Demonstration")
    print("=" * 60)
    
    print("\nThis demo shows how the fix prevents 'signal only works in main thread' errors")
    print("when BotManager is started from a background thread.")
    
    # Test in main thread (both should work)
    test_in_main_thread()
    
    # Test in background thread (old fails, new works)
    test_in_background_thread()
    
    print("\n🎉 Demo completed!")
    print("\nSummary of the fix:")
    print("• ✅ Main thread: Signal handlers registered normally")
    print("• ✅ Non-main thread: Signal handlers skipped with warning")
    print("• ✅ Non-main thread: atexit fallback registered for cleanup")
    print("• ✅ No more 'signal only works in main thread' crashes")


if __name__ == '__main__':
    main()