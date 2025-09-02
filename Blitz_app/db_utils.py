# Blitz_app/db_utils.py
"""
Database utilities for ensuring performance indices and WAL mode
"""

import os
from flask import current_app
from .extensions import db

def ensure_database_indices():
    """Ensure critical database indices exist for performance at scale"""
    
    indices_to_create = [
        # Users table
        "CREATE INDEX IF NOT EXISTS idx_users_email ON user(email)",
        "CREATE INDEX IF NOT EXISTS idx_users_verification_token ON user(verification_token)",
        
        # Orders/trades (if applicable)
        "CREATE INDEX IF NOT EXISTS idx_trades_user_id ON trade(user_id)" if _table_exists('trade') else None,
        "CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trade(timestamp)" if _table_exists('trade') else None,
        
        # Bot events
        "CREATE INDEX IF NOT EXISTS idx_bot_events_user_id ON bot_event(user_id)" if _table_exists('bot_event') else None,
        "CREATE INDEX IF NOT EXISTS idx_bot_events_type ON bot_event(type)" if _table_exists('bot_event') else None,
        "CREATE INDEX IF NOT EXISTS idx_bot_events_created_at ON bot_event(created_at)" if _table_exists('bot_event') else None,
        
        # User bots
        "CREATE INDEX IF NOT EXISTS idx_user_bots_user_id ON user_bot(user_id)" if _table_exists('user_bot') else None,
        "CREATE INDEX IF NOT EXISTS idx_user_bots_status ON user_bot(status)" if _table_exists('user_bot') else None,
        
        # Sessions (if using database sessions)
        "CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)" if _table_exists('sessions') else None,
        
        # Bot commands
        "CREATE INDEX IF NOT EXISTS idx_bot_commands_user_id ON bot_command(user_id)" if _table_exists('bot_command') else None,
        "CREATE INDEX IF NOT EXISTS idx_bot_commands_status ON bot_command(status)" if _table_exists('bot_command') else None,
    ]
    
    # Filter out None values
    indices_to_create = [idx for idx in indices_to_create if idx is not None]
    
    success_count = 0
    error_count = 0
    
    for index_sql in indices_to_create:
        try:
            db.session.execute(db.text(index_sql))
            db.session.commit()
            success_count += 1
            current_app.logger.debug(f"Index created/verified: {index_sql}")
        except Exception as e:
            error_count += 1
            current_app.logger.warning(f"Failed to create index: {index_sql}, error: {e}")
    
    current_app.logger.info(f"Database indices verified", extra={
        'indices_created': success_count,
        'indices_failed': error_count,
        'total_indices': len(indices_to_create)
    })

def _table_exists(table_name: str) -> bool:
    """Check if a table exists in the database"""
    try:
        result = db.session.execute(db.text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=:table_name"
        ), {"table_name": table_name})
        return result.fetchone() is not None
    except Exception:
        return False

def configure_sqlite_performance():
    """Configure SQLite for better performance at scale"""
    
    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if not db_uri.startswith('sqlite:'):
        current_app.logger.info("Non-SQLite database detected, skipping SQLite optimizations")
        return
    
    # Extract database path
    db_path = db_uri.replace('sqlite:///', '')
    if not os.path.isabs(db_path):
        db_path = os.path.join(current_app.instance_path, db_path)
    
    current_app.logger.info(f"Configuring SQLite performance for: {db_path}")
    
    # Performance settings
    performance_settings = [
        "PRAGMA journal_mode=WAL",  # Write-Ahead Logging for better concurrency
        "PRAGMA synchronous=NORMAL",  # Balance between safety and performance  
        "PRAGMA cache_size=10000",  # Increase cache size (10MB)
        "PRAGMA temp_store=MEMORY",  # Store temp tables in memory
        "PRAGMA mmap_size=268435456",  # 256MB memory map
    ]
    
    success_count = 0
    for setting in performance_settings:
        try:
            db.session.execute(db.text(setting))
            db.session.commit()
            success_count += 1
            current_app.logger.debug(f"Applied SQLite setting: {setting}")
        except Exception as e:
            current_app.logger.warning(f"Failed to apply SQLite setting: {setting}, error: {e}")
    
    current_app.logger.info(f"SQLite performance configured", extra={
        'settings_applied': success_count,
        'total_settings': len(performance_settings),
        'db_path': db_path
    })

def setup_database_optimizations(app):
    """Setup all database optimizations"""
    with app.app_context():
        configure_sqlite_performance()
        ensure_database_indices()