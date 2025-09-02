#!/usr/bin/env python3
"""
Test for the bot manager /tmp permission fix
"""

import os
import sys
import tempfile
import shutil
from unittest.mock import Mock, patch, MagicMock

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_bot_manager_configuration():
    """Test that BotManager properly configures directories and executables"""
    
    # Mock Flask app and dependencies to avoid database requirements
    mock_app = Mock()
    mock_app.app_context.return_value.__enter__ = Mock(return_value=None)
    mock_app.app_context.return_value.__exit__ = Mock(return_value=None)
    
    # Test with environment variables set
    test_dir = tempfile.mkdtemp()
    test_python = sys.executable
    
    try:
        with patch.dict(os.environ, {
            'BOT_RUNNER_DIR': test_dir,
            'BLITZ_PYTHON': test_python
        }):
            with patch('Blitz_app.bot_manager.User') as mock_user:
                mock_user.query.filter_by.return_value.first.return_value = None
                
                from Blitz_app.bot_manager import BotManager
                
                manager = BotManager(mock_app)
                
                # Verify configuration
                assert manager.bot_runner_dir == test_dir, f"Expected {test_dir}, got {manager.bot_runner_dir}"
                assert manager.python_executable == test_python, f"Expected {test_python}, got {manager.python_executable}"
                
                print(f"✅ Bot runner directory: {manager.bot_runner_dir}")
                print(f"✅ Python executable: {manager.python_executable}")
        
        # Test fallback behavior when directory doesn't exist
        bad_dir = "/nonexistent/directory"
        with patch.dict(os.environ, {'BOT_RUNNER_DIR': bad_dir}):
            with patch('Blitz_app.bot_manager.User') as mock_user:
                mock_user.query.filter_by.return_value.first.return_value = None
                
                manager2 = BotManager(mock_app)
                
                # Should fallback to project-local directory
                expected_fallback = os.path.join(os.getcwd(), 'runtime', 'bot_runners')
                assert manager2.bot_runner_dir == expected_fallback, f"Expected fallback to {expected_fallback}, got {manager2.bot_runner_dir}"
                
                print(f"✅ Fallback directory: {manager2.bot_runner_dir}")
                
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)

def test_script_creation_and_execution():
    """Test that scripts are created in the right place with proper permissions"""
    
    # Create temporary directory for testing
    test_dir = tempfile.mkdtemp()
    
    try:
        # Mock Flask app and database models
        mock_app = Mock()
        mock_app.app_context.return_value.__enter__ = Mock(return_value=None)
        mock_app.app_context.return_value.__exit__ = Mock(return_value=None)
        
        # Mock user and database interactions
        mock_user = Mock()
        mock_user.id = 123
        mock_user.api_key = "test_key"
        mock_user.api_secret = "test_secret"
        mock_user.telegram_token = "test_token"
        mock_user.telegram_chat_id = "test_chat"
        mock_user.exchange = "bybit"
        mock_user.to_dict.return_value = {"user_id": 123}
        
        mock_user_bot = Mock()
        mock_user_bot.restart_count = 0
        
        with patch.dict(os.environ, {'BOT_RUNNER_DIR': test_dir}):
            with patch('Blitz_app.bot_manager.User') as mock_user_class:
                with patch('Blitz_app.bot_manager.UserBot') as mock_user_bot_class:
                    with patch('Blitz_app.bot_manager.BotEvent') as mock_bot_event:
                        with patch('Blitz_app.bot_manager.db') as mock_db:
                            with patch('subprocess.Popen') as mock_popen:
                                # Setup mocks
                                mock_user_class.query.get.return_value = mock_user
                                mock_user_class.query.filter_by.return_value.first.return_value = None
                                mock_user_bot_class.query.get.return_value = mock_user_bot
                                
                                mock_process = Mock()
                                mock_process.pid = 12345
                                mock_popen.return_value = mock_process
                                
                                from Blitz_app.bot_manager import BotManager
                                
                                manager = BotManager(mock_app)
                                
                                # Test script creation
                                success = manager._start_bot_process(123)
                                
                                assert success, "Bot process should start successfully"
                                
                                # Verify script was created in correct location
                                expected_script = os.path.join(test_dir, "bot_runner_123.py")
                                assert os.path.exists(expected_script), f"Script should exist at {expected_script}"
                                
                                # Verify script permissions (should be readable)
                                file_stat = os.stat(expected_script)
                                assert file_stat.st_mode & 0o640, "Script should have read permissions"
                                
                                # Verify subprocess was called with Python interpreter
                                mock_popen.assert_called_once()
                                call_args = mock_popen.call_args[0][0]
                                assert call_args[0] == manager.python_executable, "Should use configured Python executable"
                                assert call_args[1] == '-u', "Should use unbuffered Python"
                                assert call_args[2] == expected_script, "Should execute the created script"
                                
                                print(f"✅ Script created at: {expected_script}")
                                print(f"✅ Subprocess called with: {' '.join(call_args)}")
                                print(f"✅ File permissions: {oct(file_stat.st_mode)}")
                                
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)

def test_cleanup_functionality():
    """Test that stale runner scripts are properly cleaned up"""
    
    test_dir = tempfile.mkdtemp()
    
    try:
        # Create some test files
        stale_script = os.path.join(test_dir, "bot_runner_999.py")
        active_script = os.path.join(test_dir, "bot_runner_123.py")
        other_file = os.path.join(test_dir, "other_file.txt")
        
        with open(stale_script, 'w') as f:
            f.write("# stale script")
        with open(active_script, 'w') as f:
            f.write("# active script")
        with open(other_file, 'w') as f:
            f.write("# other file")
        
        # Mock Flask app
        mock_app = Mock()
        mock_app.app_context.return_value.__enter__ = Mock(return_value=None)
        mock_app.app_context.return_value.__exit__ = Mock(return_value=None)
        
        with patch.dict(os.environ, {'BOT_RUNNER_DIR': test_dir}):
            with patch('Blitz_app.bot_manager.User') as mock_user_class:
                mock_user_class.query.filter_by.return_value.first.return_value = None
                
                from Blitz_app.bot_manager import BotManager
                
                manager = BotManager(mock_app)
                
                # Mock active users (123 is active, 999 is not)
                with patch.object(manager, '_get_active_users', return_value=[123]):
                    # Set managed bot for user 123
                    manager.managed_bots = {123: {'last_checked': 0}}
                    
                    # Run cleanup
                    manager._cleanup_stale_runner_scripts()
                    
                    # Verify stale script was removed but active script remains
                    assert not os.path.exists(stale_script), "Stale script should be removed"
                    assert os.path.exists(active_script), "Active script should remain"
                    assert os.path.exists(other_file), "Other files should not be affected"
                    
                    print(f"✅ Stale script cleaned up: {stale_script}")
                    print(f"✅ Active script preserved: {active_script}")
                    print(f"✅ Other files unaffected: {other_file}")
                    
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)

def main():
    """Run all tests"""
    print("Running bot manager fix tests...")
    print()
    
    try:
        test_bot_manager_configuration()
        print("✅ Configuration test passed")
        print()
        
        test_script_creation_and_execution()
        print("✅ Script creation test passed")
        print()
        
        test_cleanup_functionality()
        print("✅ Cleanup test passed")
        print()
        
        print("🎉 All tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)