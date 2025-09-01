# Blitz_app/models/proxy_status_log.py

from datetime import datetime
from Blitz_app.extensions import db

class ProxyStatusLog(db.Model):
    __tablename__ = 'proxy_status_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    message = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<ProxyStatusLog user={self.user_id} time={self.timestamp}>"
