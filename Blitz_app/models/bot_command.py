# Blitz_app/models/bot_command.py

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.sqlite import JSON

# We'll import db from the calling module
db = None

def init_bot_models(database):
    """Initialize bot models with the database instance"""
    global db
    db = database
    return BotCommand, BotStatus, OrderPersistence


class BotCommand(object):
    """Bot command queue for database-driven bot control"""
    __tablename__ = 'bot_command'
    
    @classmethod
    def __table_cls__(cls, db):
        return db.Table(
            cls.__tablename__,
            db.Column('id', db.Integer, primary_key=True),
            db.Column('user_id', db.Integer, db.ForeignKey('user.id'), nullable=False),
            db.Column('command_type', db.String(32), nullable=False),  # 'start', 'stop', 'exit_and_stop', 'refresh'
            db.Column('command_data', JSON, nullable=True),  # Additional command parameters
            db.Column('status', db.String(16), default='pending'),  # 'pending', 'processing', 'completed', 'failed'
            db.Column('created_at', db.DateTime, default=datetime.utcnow),
            db.Column('processed_at', db.DateTime, nullable=True),
            db.Column('error_message', db.Text, nullable=True),
        )
    
    def __repr__(self):
        return f'<BotCommand {self.id}: {self.command_type} for user {self.user_id}>'


# Let's create a simpler version integrated directly into single_file_app.py